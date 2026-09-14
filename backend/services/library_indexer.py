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
from backend.services.perceptual import compute_dhash, _dhash_from_pil

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
                    try:
                        computed_hash = compute_dhash(file_path)
                        if computed_hash:
                            self.image_repo.update_dhash(existing.id, computed_hash)
                    except Exception:
                        pass
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
            if existing:
                if existing.sha256 != sha256:
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

            dhash: str | None = None
            try:
                with Image.open(file_path) as img:
                    img = ImageOps.exif_transpose(img)
                    width, height = img.size
                    img_format = img.format or file_path.suffix.lstrip(".").upper()
                    dhash = _dhash_from_pil(img)
            except Exception:
                img_format = file_path.suffix.lstrip(".").upper()

            # Pre-generate thumbnail
            try:
                self.thumbnail_cache.get_or_create_thumbnail(file_path, sha256)
            except Exception:
                pass

            # Upsert into database with project_source='auto'
            self.image_repo.upsert_image(
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
            added_or_updated += 1

        if unchanged_ids:
            self.image_repo.touch_observed_images(unchanged_ids)
            unchanged_ids.clear()

        # Mark indexed files not observed on disk as missing (never delete history!)
        missing_count = self.image_repo.mark_missing_images_in_library(library_id, observed_paths)


        # Update library last indexed timestamp
        self.library_repo.update_last_indexed(library_id)

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
