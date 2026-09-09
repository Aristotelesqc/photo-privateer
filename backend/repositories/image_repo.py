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
            file_path=r["file_path"],
            filename=r["filename"],
            file_size=r["file_size"],
            file_modified_at=r["file_modified_at"],
            width=r["width"],
            height=r["height"],
            format=r["format"],
            indexed_at=r["indexed_at"],
            last_seen_on_disk=r["last_seen_on_disk"],
            last_scanned_at=r["last_scanned_at"],
            scan_count=r["scan_count"],
            match_count=r["match_count"],
            unreviewed_count=r["unreviewed_count"],
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
        cur.execute("SELECT * FROM images WHERE sha256 = ? LIMIT 1", (sha256,))
        r = cur.fetchone()
        return self._row_to_image(r) if r else None

    def list_images(
        self,
        library_id: Optional[int] = None,
        search: Optional[str] = None,
        filter_status: Optional[str] = None,  # "all", "unscanned", "scanned", "has_matches", "has_unreviewed"
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

        if search:
            where_clauses.append("(filename LIKE ? OR file_path LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term])

        if filter_status == "unscanned":
            where_clauses.append("scan_count = 0")
        elif filter_status == "scanned":
            where_clauses.append("scan_count > 0")
        elif filter_status == "has_matches":
            where_clauses.append("match_count > 0")
        elif filter_status == "has_unreviewed":
            where_clauses.append("unreviewed_count > 0")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        # Total count
        cur = self.conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM images {where_sql}", tuple(params))
        total = cur.fetchone()[0]

        # Sorting whitelist
        allowed_sorts = {
            "indexed_at": "indexed_at",
            "last_scanned_at": "last_scanned_at",
            "filename": "filename",
            "match_count": "match_count",
            "unreviewed_count": "unreviewed_count",
            "file_size": "file_size",
        }
        order_col = allowed_sorts.get(sort_by, "indexed_at")
        direction = "ASC" if sort_dir.lower() == "asc" else "DESC"

        # Paginated fetch
        data_params = list(params)
        data_params.extend([limit, offset])
        cur.execute(
            f"SELECT * FROM images {where_sql} ORDER BY {order_col} {direction} LIMIT ? OFFSET ?",
            tuple(data_params),
        )
        rows = cur.fetchall()
        return [self._row_to_image(r) for r in rows], total

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
    ) -> ImageOut:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO images (
                library_id, sha256, file_path, filename, file_size, file_modified_at,
                width, height, format, indexed_at, last_seen_on_disk
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                sha256 = excluded.sha256,
                filename = excluded.filename,
                file_size = excluded.file_size,
                file_modified_at = excluded.file_modified_at,
                width = excluded.width,
                height = excluded.height,
                format = excluded.format,
                last_seen_on_disk = excluded.last_seen_on_disk
        """, (
            library_id, sha256, file_path, filename, file_size, file_modified_at,
            width, height, format, now, now
        ))
        cur.execute("SELECT * FROM images WHERE file_path = ?", (file_path,))
        r = cur.fetchone()
        return self._row_to_image(r)

    def record_scan_completed(self, image_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            UPDATE images
            SET scan_count = scan_count + 1,
                last_scanned_at = ?
            WHERE id = ?
        """, (now, image_id))
        self.refresh_image_match_counts(image_id)

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
        placeholders = ",".join("?" for _ in image_ids)
        cur = self.conn.cursor()
        cur.execute(f"SELECT * FROM images WHERE id IN ({placeholders})", tuple(image_ids))
        return [self._row_to_image(r) for r in cur.fetchall()]
