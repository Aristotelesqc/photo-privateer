"""Repository for indexed photographs."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from backend.models import ImageOut

class ImageRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _row_to_image(self, r: sqlite3.Row) -> ImageOut:
        return ImageOut(
            id=r["id"],
            library_id=r["library_id"],
            sha256=r["sha256"],
            dhash=r["dhash"] if "dhash" in r.keys() else None,
            photo_group_id=r["photo_group_id"] if "photo_group_id" in r.keys() else None,
            is_primary_representation=int(r["is_primary_representation"]) if ("is_primary_representation" in r.keys() and r["is_primary_representation"] is not None) else 1,
            file_path=r["file_path"],
            filename=r["filename"],
            file_size=r["file_size"],
            file_modified_at=r["file_modified_at"],
            file_modified_at_ns=r["file_modified_at_ns"] if "file_modified_at_ns" in r.keys() else None,
            width=r["width"],
            height=r["height"],
            format=r["format"],
            indexed_at=r["indexed_at"],
            last_seen_on_disk=r["last_seen_on_disk"],
            is_present_on_disk=bool(r["is_present_on_disk"]) if "is_present_on_disk" in r.keys() else True,
            project=r["project"] if "project" in r.keys() else None,
            project_source=r["project_source"] if "project_source" in r.keys() else "auto",
            last_scanned_at=r["last_scanned_at"],
            scan_count=r["scan_count"],
            match_count=r["match_count"],
            unreviewed_count=r["unreviewed_count"],
            group_match_count=r["group_match_count"] if "group_match_count" in r.keys() else None,
            group_unreviewed_count=r["group_unreviewed_count"] if "group_unreviewed_count" in r.keys() else None,
            thumbnail_url=f"/api/photos/{r['id']}/thumbnail",
        )

    def get_by_id(self, image_id: int) -> Optional[ImageOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM images WHERE id = ?", (image_id,))
        r = cur.fetchone()
        return self._row_to_image(r) if r else None

    def get_by_path(self, file_path: str) -> Optional[ImageOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM images WHERE file_path = ?", (file_path,))
        r = cur.fetchone()
        return self._row_to_image(r) if r else None

    def get_by_sha256(self, sha256: str) -> Optional[ImageOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM images WHERE sha256 = ? ORDER BY is_present_on_disk DESC, id ASC LIMIT 1", (sha256,))
        r = cur.fetchone()
        return self._row_to_image(r) if r else None

    def get_all_by_sha256(self, sha256: str) -> list[ImageOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM images WHERE sha256 = ? ORDER BY id ASC", (sha256,))
        return [self._row_to_image(r) for r in cur.fetchall()]

    def reconcile_image_location(
        self,
        image_id: int,
        library_id: int,
        new_path: str,
        new_filename: str,
        new_size: int,
        new_mtime: float,
        new_mtime_ns: Optional[int] = None,
    ) -> ImageOut:
        """Reconciles a renamed or moved image file, preserving ID and historical matches."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE images
            SET library_id = ?,
                file_path = ?,
                filename = ?,
                file_size = ?,
                file_modified_at = ?,
                file_modified_at_ns = ?,
                last_seen_on_disk = ?,
                is_present_on_disk = 1
            WHERE id = ?
        """, (library_id, new_path, new_filename, new_size, new_mtime, new_mtime_ns, now, image_id))
        return self.get_by_id(image_id)  # type: ignore

    def mark_missing_images_in_library(self, library_id: int, observed_paths: set[str]) -> int:
        """Marks any images registered to this library that were not observed on disk as missing."""
        from backend.utils import chunked
        cur = self.conn.cursor()
        cur.execute("SELECT id, file_path FROM images WHERE library_id = ? AND is_present_on_disk = 1", (library_id,))
        rows = cur.fetchall()
        missing_ids = [r["id"] for r in rows if r["file_path"] not in observed_paths]
        if missing_ids:
            for chunk in chunked(missing_ids, 500):
                placeholders = ",".join("?" for _ in chunk)
                cur.execute(f"UPDATE images SET is_present_on_disk = 0 WHERE id IN ({placeholders})", tuple(chunk))
            return len(missing_ids)
        return 0

    def touch_observed_images(self, image_ids: list[int]) -> int:
        """Batch updates last_seen_on_disk and ensures is_present_on_disk = 1 for observed files without rehashing."""
        if not image_ids:
            return 0
        from backend.utils import chunked
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        total = 0
        for chunk in chunked(image_ids, 500):
            placeholders = ",".join("?" for _ in chunk)
            cur.execute(f"""
                UPDATE images
                SET last_seen_on_disk = ?,
                    is_present_on_disk = 1
                WHERE id IN ({placeholders})
            """, (now, *chunk))
            total += cur.rowcount
        self.conn.commit()
        return total


    def list_images(
        self,
        library_id: Optional[int] = None,
        search: Optional[str] = None,
        filter_status: Optional[str] = None,  # "all", "unscanned", "scanned", "has_matches", "has_unreviewed", "missing", "grouped", "ungrouped"
        project: Optional[str] = None,
        group_id: Optional[int] = None,
        sort_by: str = "indexed_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ImageOut], int]:
        where_clauses = []
        params: list[object] = []

        if library_id is not None:
            where_clauses.append("library_id = ?")
            params.append(library_id)

        if group_id is not None:
            where_clauses.append("photo_group_id = ?")
            params.append(group_id)

        if search:
            where_clauses.append("(filename LIKE ? OR file_path LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term])

        if project:
            if project == "__unassigned__":
                where_clauses.append("(project IS NULL OR project = '')")
            else:
                where_clauses.append("project = ?")
                params.append(project)

        if filter_status == "unscanned":
            where_clauses.append("scan_count = 0 AND is_present_on_disk = 1")
        elif filter_status == "scanned":
            where_clauses.append("scan_count > 0")
        elif filter_status == "has_matches":
            # Group-aware: a grouped variant shares the discoveries of its group's web search
            where_clauses.append("COALESCE(gc_match_count, match_count) > 0")
        elif filter_status == "has_unreviewed":
            where_clauses.append("COALESCE(gc_unreviewed_count, unreviewed_count) > 0")
        elif filter_status == "missing":
            where_clauses.append("is_present_on_disk = 0")
        elif filter_status == "grouped":
            where_clauses.append("photo_group_id IS NOT NULL")
        elif filter_status == "ungrouped":
            where_clauses.append("photo_group_id IS NULL")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Per-group aggregate counts, so every member of a group reflects the group's discoveries
        from_sql = """
            images
            LEFT JOIN (
                SELECT photo_group_id AS gc_group_id,
                       SUM(match_count) AS gc_match_count,
                       SUM(unreviewed_count) AS gc_unreviewed_count
                FROM images
                WHERE photo_group_id IS NOT NULL
                GROUP BY photo_group_id
            ) gc ON gc.gc_group_id = images.photo_group_id
        """

        # Total count
        cur = self.conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {from_sql} {where_sql}", tuple(params))
        total = cur.fetchone()[0]

        # Sorting whitelist
        allowed_sorts = {
            "indexed_at": "indexed_at",
            "last_scanned_at": "last_scanned_at",
            "filename": "filename",
            "project": "project",
            "match_count": "COALESCE(gc_match_count, match_count)",
            "unreviewed_count": "COALESCE(gc_unreviewed_count, unreviewed_count)",
            "file_size": "file_size",
        }
        order_col = allowed_sorts.get(sort_by, "indexed_at")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

        # Paginated fetch
        data_params = list(params)
        data_params.extend([limit, offset])
        cur.execute(
            f"SELECT images.*, gc_match_count AS group_match_count, gc_unreviewed_count AS group_unreviewed_count "
            f"FROM {from_sql} {where_sql} ORDER BY {order_col} {direction}, images.id {direction} LIMIT ? OFFSET ?",
            tuple(data_params),
        )
        rows = cur.fetchall()
        return [self._row_to_image(r) for r in rows], total

    def detach_archived_image(self, image_id: int, archive_path: str) -> None:
        """Detaches an old image record whose path was replaced by different content,
        relocating its unique file_path constraint to an archive alias and marking it absent.
        """
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE images
            SET file_path = ?,
                is_present_on_disk = 0,
                photo_group_id = NULL,
                is_primary_representation = 1
            WHERE id = ?
            """,
            (archive_path, image_id),
        )
        # Group integrity is repaired once by the caller (LibraryIndexer.index_library) after
        # the whole pass, rather than with a full-table repair per detached row.

    def inherit_group_membership(self, image_id: int, group_id: int, make_primary: bool) -> None:
        """Joins an ungrouped image to an existing group, optionally as its primary representation.
        Used when a grouped photo's file is replaced in place by new content. Does not commit.
        """
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM photo_groups WHERE id = ?", (group_id,))
        if cur.fetchone() is None:
            return
        cur.execute(
            "UPDATE images SET photo_group_id = ?, is_primary_representation = 0 "
            "WHERE id = ? AND photo_group_id IS NULL",
            (group_id, image_id),
        )
        if cur.rowcount != 1 or not make_primary:
            return
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "UPDATE photo_groups SET preferred_image_id = ?, updated_at = ? WHERE id = ?",
            (image_id, now, group_id),
        )
        cur.execute(
            "UPDATE images SET is_primary_representation = CASE WHEN id = ? THEN 1 ELSE 0 END "
            "WHERE photo_group_id = ?",
            (image_id, group_id),
        )

    def upsert_image(
        self,
        library_id: int,
        sha256: str,
        file_path: str,
        filename: str,
        file_size: int,
        file_modified_at: float,
        width: Optional[int],
        height: Optional[int],
        format: Optional[str],
        project: Optional[str] = None,
        project_source: str = "auto",
        file_modified_at_ns: Optional[int] = None,
        dhash: Optional[str] = None,
    ) -> ImageOut:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO images (
                library_id, sha256, dhash, file_path, filename, file_size, file_modified_at, file_modified_at_ns,
                width, height, format, project, project_source, indexed_at, last_seen_on_disk, is_present_on_disk
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(file_path) DO UPDATE SET
                sha256 = excluded.sha256,
                dhash = COALESCE(excluded.dhash, images.dhash),
                filename = excluded.filename,
                file_size = excluded.file_size,
                file_modified_at = excluded.file_modified_at,
                file_modified_at_ns = excluded.file_modified_at_ns,
                width = excluded.width,
                height = excluded.height,
                format = excluded.format,
                project = CASE 
                    WHEN images.project_source = 'manual' THEN images.project
                    ELSE COALESCE(images.project, excluded.project)
                END,
                project_source = CASE
                    WHEN images.project_source = 'manual' THEN 'manual'
                    ELSE excluded.project_source
                END,
                last_seen_on_disk = excluded.last_seen_on_disk,
                is_present_on_disk = 1
        """, (
            library_id, sha256, dhash, file_path, filename, file_size, file_modified_at, file_modified_at_ns,
            width, height, format, project, project_source, now, now
        ))
        cur.execute("SELECT * FROM images WHERE file_path = ?", (file_path,))
        r = cur.fetchone()
        return self._row_to_image(r)

    def update_dhash(self, image_id: int, dhash: str) -> None:
        """Sets the perceptual dHash for an image."""
        cur = self.conn.cursor()
        cur.execute("UPDATE images SET dhash = ? WHERE id = ?", (dhash, image_id))

    def update_dhashes(self, rows: list[tuple[str, int]]) -> None:
        """Batch updates dhash values for multiple images and commits."""
        if not rows:
            return
        cur = self.conn.cursor()
        cur.executemany("UPDATE images SET dhash = ? WHERE id = ?", rows)
        self.conn.commit()

    def get_images_for_group(self, group_id: int) -> list[ImageOut]:
        """Returns all images belonging to a group, ordered with the primary representation first."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT * FROM images WHERE photo_group_id = ? ORDER BY is_primary_representation DESC, id ASC",
            (group_id,),
        )
        return [self._row_to_image(r) for r in cur.fetchall()]

    def update_mtime_ns(self, image_id: int, mtime_ns: int) -> None:
        """Opportunistically upgrades legacy image rows to store exact nanosecond mtime."""
        cur = self.conn.cursor()
        cur.execute("UPDATE images SET file_modified_at_ns = ? WHERE id = ?", (mtime_ns, image_id))

    def update_project(self, image_id: int, project: Optional[str], source: str = "manual") -> Optional[ImageOut]:
        val = project.strip() if (project and project.strip()) else None
        cur = self.conn.cursor()
        cur.execute("UPDATE images SET project = ?, project_source = ? WHERE id = ?", (val, source, image_id))
        return self.get_by_id(image_id)

    def update_project_auto(self, image_id: int, project: Optional[str]) -> bool:
        """Updates project only if current project was auto-detected or is unassigned (never overwrites manual assignment)."""
        val = project.strip() if (project and project.strip()) else None
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE images 
            SET project = ?, project_source = 'auto' 
            WHERE id = ? AND (project_source = 'auto' OR project IS NULL OR project = '')
        """, (val, image_id))
        return cur.rowcount > 0

    def batch_update_project(self, image_ids: list[int], project: Optional[str], source: str = "manual") -> int:
        if not image_ids:
            return 0
        from backend.utils import chunked
        val = project.strip() if (project and project.strip()) else None
        total_updated = 0
        cur = self.conn.cursor()
        for chunk in chunked(image_ids, 500):
            placeholders = ",".join("?" for _ in chunk)
            cur.execute(f"UPDATE images SET project = ?, project_source = ? WHERE id IN ({placeholders})", (val, source, *chunk))
            total_updated += cur.rowcount
        return total_updated

    def get_distinct_projects(self, library_id: Optional[int] = None) -> list[str]:
        cur = self.conn.cursor()
        if library_id is not None:
            cur.execute("""
                SELECT DISTINCT project FROM images
                WHERE library_id = ? AND project IS NOT NULL AND project != ''
                ORDER BY project ASC
            """, (library_id,))
        else:
            cur.execute("""
                SELECT DISTINCT project FROM images
                WHERE project IS NOT NULL AND project != ''
                ORDER BY project ASC
            """)
        return [row[0] for row in cur.fetchall() if row[0]]

    def record_scan_completed(self, image_id: int, scanned_at: Optional[str] = None) -> str:
        now = scanned_at or datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE images
            SET scan_count = scan_count + 1,
                last_scanned_at = ?
            WHERE id = ?
        """, (now, image_id))
        self.refresh_image_match_counts(image_id)
        return now

    def record_group_scan_completed(self, group_id: int, representative_id: int, scanned_at: Optional[str] = None) -> None:
        """Marks sibling group members as scanned when representative was searched."""
        if not group_id:
            return
        now = scanned_at or datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute(
            """
            UPDATE images
            SET scan_count = scan_count + 1,
                last_scanned_at = ?
            WHERE photo_group_id = ? AND id != ?
            """,
            (now, group_id, representative_id),
        )

    def refresh_image_match_counts(self, image_id: int) -> None:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT 
                COUNT(*) as total_matches,
                SUM(CASE WHEN classification = 'UNREVIEWED' THEN 1 ELSE 0 END) as unreviewed_matches
            FROM matches
            WHERE image_id = ?
        """, (image_id,))
        row = cur.fetchone()
        total_m = row["total_matches"] if row else 0
        unrev_m = row["unreviewed_matches"] if (row and row["unreviewed_matches"] is not None) else 0
        cur.execute("""
            UPDATE images
            SET match_count = ?,
                unreviewed_count = ?
            WHERE id = ?
        """, (total_m, unrev_m, image_id))

    def get_by_ids(self, image_ids: list[int]) -> list[ImageOut]:
        if not image_ids:
            return []
        from backend.utils import chunked
        results: list[ImageOut] = []
        cur = self.conn.cursor()
        for chunk in chunked(image_ids, 500):
            placeholders = ",".join("?" for _ in chunk)
            cur.execute(f"SELECT * FROM images WHERE id IN ({placeholders})", tuple(chunk))
            results.extend([self._row_to_image(r) for r in cur.fetchall()])
        return results
