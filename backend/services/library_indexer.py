"""Filesystem scanner and photo metadata indexer."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Generator
from PIL import Image, ImageOps

from backend.config import SUPPORTED_EXTENSIONS
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.perceptual import compute_dhash, is_candidate_representation, DHASH_UNAVAILABLE

def calculate_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

class LibraryIndexer:
    def __init__(
        self,
        library_repo: LibraryRepository,
        image_repo: ImageRepository,
        thumbnail_cache: ThumbnailCache,
    ):
        self.library_repo = library_repo
        self.image_repo = image_repo
        self.thumbnail_cache = thumbnail_cache

    def _discover_files(self, root_dir: Path, recursive: bool) -> Generator[Path, None, None]:
        if not root_dir.is_dir():
            return

        resolved_root = root_dir.resolve()
        if recursive:
            for root, _, files in os.walk(root_dir):
                for filename in files:
                    p = Path(root) / filename
                    if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        try:
                            real_p = p.resolve()
                            if os.path.commonpath([str(resolved_root), str(real_p)]) == str(resolved_root):
                                yield p
                        except (ValueError, OSError):
                            continue
        else:
            for item in root_dir.iterdir():
                if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                    try:
                        real_p = item.resolve()
                        if os.path.commonpath([str(resolved_root), str(real_p)]) == str(resolved_root):
                            yield item
                    except (ValueError, OSError):
                        continue

    def index_library(self, library_id: int) -> dict[str, int]:
        lib = self.library_repo.get_by_id(library_id)
        if not lib:
            raise ValueError(f"Library with id {library_id} not found")

        root = Path(lib.path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Library directory does not exist: {root}")

        scanned = 0
        added_or_updated = 0
        unchanged = 0
        observed_paths: set[str] = set()
        unchanged_ids: list[int] = []
        pending_dhashes: list[tuple[str, int]] = []

        for file_path in self._discover_files(root, lib.recursive):
            scanned += 1
            norm_path = str(file_path.resolve())
            observed_paths.add(norm_path)
            stat = file_path.stat()
            file_size = stat.st_size
            mtime = stat.st_mtime
            mtime_ns = stat.st_mtime_ns

            # Determine project based on immediate parent folder
            detected_project = None
            if getattr(lib, "subfolders_as_projects", True):
                try:
                    rel_p = file_path.resolve().relative_to(root)
                    if len(rel_p.parts) > 1:
                        detected_project = rel_p.parts[-2]
                except Exception:
                    pass

            # Check if file exists in database with identical mtime and size
            existing = self.image_repo.get_by_path(norm_path)
            is_mtime_match = False
            if existing:
                if existing.file_modified_at_ns is not None and existing.file_modified_at_ns > 0:
                    is_mtime_match = (existing.file_modified_at_ns == mtime_ns)
                else:
                    is_mtime_match = (abs(existing.file_modified_at - mtime) < 0.0001)

            if existing and is_mtime_match and existing.file_size == file_size:
                unchanged += 1
                unchanged_ids.append(existing.id)
                # Opportunistic upgrade for legacy rows
                if existing.file_modified_at_ns is None:
                    self.image_repo.update_mtime_ns(existing.id, mtime_ns)
                if existing.dhash is None:
                    if self.image_repo.conn.in_transaction:
                        self.image_repo.conn.commit()
                    try:
                        computed_hash = compute_dhash(file_path)
                    except Exception:
                        computed_hash = None
                    pending_dhashes.append((computed_hash or DHASH_UNAVAILABLE, existing.id))
                    if len(pending_dhashes) >= 100:
                        self.image_repo.update_dhashes(pending_dhashes)
                        pending_dhashes.clear()
                if len(unchanged_ids) >= 500:
                    self.image_repo.touch_observed_images(unchanged_ids)
                    unchanged_ids.clear()
                # Auto-assign detected project if photo currently has no project
                if getattr(lib, "subfolders_as_projects", True) and not existing.project and detected_project:
                    self.image_repo.update_project_auto(existing.id, detected_project)
                # If marked missing previously, mark back present on disk
                if not existing.is_present_on_disk:
                    self.image_repo.reconcile_image_location(
                        image_id=existing.id,
                        library_id=library_id,
                        new_path=norm_path,
                        new_filename=file_path.name,
                        new_size=file_size,
                        new_mtime=mtime,
                        new_mtime_ns=mtime_ns,
                    )
                # Ensure thumbnail exists in cache
                if not self.thumbnail_cache.has_thumbnail(existing.sha256):
                    try:
                        self.thumbnail_cache.get_or_create_thumbnail(file_path, existing.sha256)
                    except Exception:
                        pass
                continue

            # Compute hash and extract dimensions safely
            sha256 = calculate_sha256(file_path)

            # Photo identity replacement check:
            # If an existing record was at this path but has a DIFFERENT sha256,
            # detach the old record to an archive alias to preserve its history without inheriting to new file.
            # A photographer re-exporting an edit over the same file keeps the photo's place in its
            # group, but only when the new content is perceptually a re-export of the old one: a path
            # reused for an unrelated photograph must not be folded into another photo's group (it
            # would then never be searched on its own). Low-information or unavailable hashes fail
            # open: the new photo stays ungrouped and surfaces through normal candidate review.
            replaced_grouped = None
            if existing:
                if existing.sha256 != sha256:
                    if existing.photo_group_id is not None:
                        replaced_grouped = existing
                    archive_alias = f"{norm_path}#archived-{existing.id}"
                    self.image_repo.detach_archived_image(existing.id, archive_alias)
                    existing = None

            # Check if this is a renamed or moved file with identical content hash
            if not existing:
                candidates = self.image_repo.get_all_by_sha256(sha256)
                # An unambiguous rename is when EXACTLY ONE existing record with identical SHA-256 no longer exists at its old path
                missing_candidates = [c for c in candidates if not Path(c.file_path).exists()]
                reconciled = False
                if len(missing_candidates) == 1:
                    candidate = missing_candidates[0]
                    # Old path is gone -> reconcile existing image ID to new path
                    self.image_repo.reconcile_image_location(
                        image_id=candidate.id,
                        library_id=library_id,
                        new_path=norm_path,
                        new_filename=file_path.name,
                        new_size=file_size,
                        new_mtime=mtime,
                        new_mtime_ns=mtime_ns,
                    )
                    if detected_project and not candidate.project:
                        self.image_repo.update_project_auto(candidate.id, detected_project)
                    if (
                        replaced_grouped is not None
                        and candidate.photo_group_id is None
                        and is_candidate_representation(replaced_grouped.dhash or "", candidate.dhash or "")
                    ):
                        # The known photo adopts the replaced record's lineage: its discoveries are
                        # coalesced with the replaced record's (exactly once, triage preserved), then it
                        # joins the group, whose discoveries are coalesced in turn.
                        self.image_repo.transfer_representation_history(replaced_grouped.id, candidate.id)
                        self.image_repo.inherit_group_membership(
                            candidate.id,
                            replaced_grouped.photo_group_id,
                            replaced_grouped.is_primary_representation == 1,
                        )
                    # Ensure thumbnail cached
                    if not self.thumbnail_cache.has_thumbnail(sha256):
                        try:
                            self.thumbnail_cache.get_or_create_thumbnail(file_path, sha256)
                        except Exception:
                            pass
                    added_or_updated += 1
                    reconciled = True
                if reconciled:
                    continue

            width: int | None = None
            height: int | None = None
            img_format: str | None = None

            try:
                with Image.open(file_path) as img:
                    img_format = img.format or file_path.suffix.lstrip(".").upper()
                    img = ImageOps.exif_transpose(img)
                    width, height = img.size
            except Exception:
                img_format = file_path.suffix.lstrip(".").upper()

            # Same draft-mode hashing as the backfill path, so hashes are comparable across both
            dhash = compute_dhash(file_path) or DHASH_UNAVAILABLE

            # Pre-generate thumbnail
            try:
                self.thumbnail_cache.get_or_create_thumbnail(file_path, sha256)
            except Exception:
                pass

            # Upsert into database with project_source='auto'
            upserted = self.image_repo.upsert_image(
                library_id=library_id,
                sha256=sha256,
                file_path=norm_path,
                filename=file_path.name,
                file_size=file_size,
                file_modified_at=mtime,
                width=width,
                height=height,
                format=img_format,
                project=detected_project,
                project_source="auto",
                file_modified_at_ns=mtime_ns,
                dhash=dhash,
            )
            if replaced_grouped is not None and is_candidate_representation(replaced_grouped.dhash or "", dhash):
                # Validated re-export: same representation lineage, so it keeps the group role and the
                # discoveries and triage recorded against the replaced content.
                self.image_repo.transfer_representation_history(replaced_grouped.id, upserted.id)
                self.image_repo.inherit_group_membership(
                    upserted.id,
                    replaced_grouped.photo_group_id,
                    replaced_grouped.is_primary_representation == 1,
                )
            added_or_updated += 1

        if pending_dhashes:
            self.image_repo.update_dhashes(pending_dhashes)
            pending_dhashes.clear()

        if unchanged_ids:
            self.image_repo.touch_observed_images(unchanged_ids)
            unchanged_ids.clear()

        # Mark indexed files not observed on disk as missing (never delete history!)
        missing_count = self.image_repo.mark_missing_images_in_library(library_id, observed_paths)


        # Repair group integrity once for the whole pass (groups left with < 2 members by
        # replaced files, dangling preferred representations). Runs on every pass, so damage left
        # by an earlier interrupted pass is healed even when this pass detaches nothing.
        from backend.repositories.group_repo import PhotoGroupRepository
        PhotoGroupRepository(self.image_repo.conn).repair_groups()

        # Update library last indexed timestamp
        self.library_repo.update_last_indexed(library_id)
        self.image_repo.conn.commit()

        return {
            "scanned": scanned,
            "added_or_updated": added_or_updated,
            "unchanged": unchanged,
            "missing": missing_count,
        }

    def detect_and_apply_subfolder_projects(self, library_id: int) -> int:
        """Retroactively detects and sets project names based on immediate parent subfolders.
        Preserves manually assigned projects (never overwrites project_source == 'manual').
        """
        lib = self.library_repo.get_by_id(library_id)
        if not lib:
            raise ValueError(f"Library {library_id} not found")
        root = Path(lib.path).resolve()
        cur = self.image_repo.conn.cursor()
        cur.execute("SELECT id, file_path FROM images WHERE library_id = ?", (library_id,))
        rows = cur.fetchall()
        updated = 0
        for r in rows:
            img_id = r["id"]
            img_path = Path(r["file_path"]).resolve()
            try:
                rel = img_path.relative_to(root)
                if len(rel.parts) > 1:
                    proj = rel.parts[-2]  # Immediate parent folder
                    if self.image_repo.update_project_auto(img_id, proj):
                        updated += 1
                else:
                    if self.image_repo.update_project_auto(img_id, None):
                        updated += 1
            except Exception:
                pass
        self.image_repo.conn.commit()
        return updated
