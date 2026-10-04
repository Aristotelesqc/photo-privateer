"""Repository for photo libraries."""
from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from backend.models import LibraryOut

logger = logging.getLogger("photo_privateer.libraries")

class LibraryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def list_libraries(self, include_archived: bool = True) -> list[LibraryOut]:
        cur = self.conn.cursor()
        where_clause = "" if include_archived else "WHERE l.is_archived = 0"
        cur.execute(f"""
            SELECT l.id, l.path, l.name, l.enabled, l.recursive, l.created_at, l.last_indexed_at,
                   COALESCE(l.is_archived, 0) as is_archived,
                   COALESCE(l.subfolders_as_projects, 1) as subfolders_as_projects,
                   COUNT(i.id) as image_count
            FROM libraries l
            LEFT JOIN images i ON l.id = i.library_id
            {where_clause}
            GROUP BY l.id
            ORDER BY l.created_at ASC
        """)
        rows = cur.fetchall()
        return [
            LibraryOut(
                id=r["id"],
                path=r["path"],
                name=r["name"],
                enabled=bool(r["enabled"]),
                recursive=bool(r["recursive"]),
                is_archived=bool(r["is_archived"]),
                subfolders_as_projects=bool(r["subfolders_as_projects"]),
                created_at=r["created_at"],
                last_indexed_at=r["last_indexed_at"],
                image_count=r["image_count"],
            )
            for r in rows
        ]

    def get_by_id(self, library_id: int) -> Optional[LibraryOut]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT l.id, l.path, l.name, l.enabled, l.recursive, l.created_at, l.last_indexed_at,
                   COALESCE(l.is_archived, 0) as is_archived,
                   COALESCE(l.subfolders_as_projects, 1) as subfolders_as_projects,
                   COUNT(i.id) as image_count
            FROM libraries l
            LEFT JOIN images i ON l.id = i.library_id
            WHERE l.id = ?
            GROUP BY l.id
        """, (library_id,))
        r = cur.fetchone()
        if not r:
            return None
        return LibraryOut(
            id=r["id"],
            path=r["path"],
            name=r["name"],
            enabled=bool(r["enabled"]),
            recursive=bool(r["recursive"]),
            is_archived=bool(r["is_archived"]),
            subfolders_as_projects=bool(r["subfolders_as_projects"]),
            created_at=r["created_at"],
            last_indexed_at=r["last_indexed_at"],
            image_count=r["image_count"],
        )

    def get_by_path(self, path: str) -> Optional[LibraryOut]:
        norm_path = str(Path(path).resolve())
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM libraries WHERE path = ?", (norm_path,))
        r = cur.fetchone()
        if not r:
            return None
        return self.get_by_id(r["id"])

    def create(
        self,
        path: str,
        name: Optional[str] = None,
        recursive: bool = True,
        subfolders_as_projects: bool = True,
    ) -> LibraryOut:
        import os
        norm_path = str(Path(path).resolve())

        # Forbid overlapping library roots with existing libraries (including archived)
        for existing in self.list_libraries(include_archived=True):
            existing_root = str(Path(existing.path).resolve())
            try:
                common = os.path.commonpath([existing_root, norm_path])
                if common in (existing_root, norm_path):
                    raise ValueError(
                        f"Cannot register library: '{norm_path}' overlaps with existing library '{existing.name}' ({existing_root}). "
                        f"Overlapping library roots are forbidden to maintain deterministic photo containment."
                    )
            except ValueError as err:
                if "overlaps with" in str(err):
                    raise
                pass  # Different drives on Windows cannot overlap

        folder_name = name or Path(norm_path).name or norm_path
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO libraries (path, name, enabled, recursive, is_archived, subfolders_as_projects, created_at)
            VALUES (?, ?, 1, ?, 0, ?, ?)
        """, (norm_path, folder_name, int(recursive), int(subfolders_as_projects), now))
        lib_id = cur.lastrowid
        self.conn.commit()
        return self.get_by_id(lib_id)  # type: ignore

    def update(
        self,
        library_id: int,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
        recursive: Optional[bool] = None,
        is_archived: Optional[bool] = None,
        subfolders_as_projects: Optional[bool] = None,
    ) -> Optional[LibraryOut]:
        fields = []
        params = []
        if name is not None:
            fields.append("name = ?")
            params.append(name)
        if enabled is not None:
            fields.append("enabled = ?")
            params.append(int(enabled))
        if recursive is not None:
            fields.append("recursive = ?")
            params.append(int(recursive))
        if is_archived is not None:
            fields.append("is_archived = ?")
            params.append(int(is_archived))
        if subfolders_as_projects is not None:
            fields.append("subfolders_as_projects = ?")
            params.append(int(subfolders_as_projects))
        if not fields:
            return self.get_by_id(library_id)

        params.append(library_id)
        sql = f"UPDATE libraries SET {', '.join(fields)} WHERE id = ?"
        cur = self.conn.cursor()
        cur.execute(sql, tuple(params))
        self.conn.commit()
        return self.get_by_id(library_id)

    def archive(self, library_id: int) -> bool:
        """Non-destructively archives a library (stops monitoring without deleting images or matches)."""
        cur = self.conn.cursor()
        cur.execute("UPDATE libraries SET is_archived = 1, enabled = 0 WHERE id = ?", (library_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def unarchive(self, library_id: int) -> bool:
        """Restores an archived library to active monitoring with overlap checking against active libraries."""
        lib = self.get_by_id(library_id)
        if not lib:
            return False
        import os
        norm_path = str(Path(lib.path).resolve())
        for existing in self.list_libraries(include_archived=False):
            if existing.id == library_id:
                continue
            existing_root = str(Path(existing.path).resolve())
            try:
                common = os.path.commonpath([existing_root, norm_path])
                if common in (existing_root, norm_path):
                    raise ValueError(
                        f"Cannot unarchive library: '{norm_path}' overlaps with active library '{existing.name}' ({existing_root}). "
                        f"Overlapping library roots are forbidden."
                    )
            except ValueError as err:
                if "overlaps with" in str(err):
                    raise
                pass

        cur = self.conn.cursor()
        cur.execute("UPDATE libraries SET is_archived = 0, enabled = 1 WHERE id = ?", (library_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def purge(self, library_id: int) -> bool:
        """Transactionally purges a library and its catalog metadata from SQLite.
        Cleans up empty scan sessions and evicts cached thumbnails from disk.
        ORIGINAL SOURCE FILES ON DISK ARE NEVER MODIFIED, RENAMED, OR DELETED.
        """
        from backend.utils import chunked
        cur = self.conn.cursor()
        # Concurrency safety: block permanent purge if any scan is actively running
        cur.execute("SELECT 1 FROM scan_sessions WHERE status = 'RUNNING' LIMIT 1")
        if cur.fetchone():
            raise ValueError("Cannot permanently purge library while a scan session is running.")

        try:
            # Find all images and their content hashes belonging to this library
            cur.execute("SELECT id, sha256 FROM images WHERE library_id = ?", (library_id,))
            image_rows = cur.fetchall()
            image_ids = [r["id"] if isinstance(r, sqlite3.Row) else r[0] for r in image_rows]
            sha_hashes = [r["sha256"] if isinstance(r, sqlite3.Row) else r[1] for r in image_rows]

            # Hand over logical discoveries held by purged photos to observations other photos made
            # of the same web use (photo groups), so purging never deletes another photo's discovery
            if image_ids:
                from backend.repositories.discovery_merge import release_discoveries, refresh_match_counts
                refresh_match_counts(self.conn, release_discoveries(self.conn, image_ids))

            candidate_session_ids = set()
            if image_ids:
                for chunk in chunked(image_ids, 500):
                    placeholders = ",".join("?" for _ in chunk)
                    # Track sessions associated with these images before item deletion
                    cur.execute(f"SELECT DISTINCT scan_session_id FROM scan_items WHERE image_id IN ({placeholders}) AND scan_session_id IS NOT NULL", tuple(chunk))
                    candidate_session_ids.update(r["scan_session_id"] if isinstance(r, sqlite3.Row) else r[0] for r in cur.fetchall())
                    # Nullify provider_calls image reference so history is preserved without FK collision
                    cur.execute(f"UPDATE provider_calls SET image_id = NULL WHERE image_id IN ({placeholders})", tuple(chunk))
                    # Delete matches associated with these images
                    cur.execute(f"DELETE FROM matches WHERE image_id IN ({placeholders})", tuple(chunk))
                    # Delete scan_items
                    cur.execute(f"DELETE FROM scan_items WHERE image_id IN ({placeholders})", tuple(chunk))
                    # Delete images
                    cur.execute(f"DELETE FROM images WHERE id IN ({placeholders})", tuple(chunk))

            cur.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
            lib_deleted = cur.rowcount > 0

            # Clean up empty scan sessions that belonged to purged images and are not active RUNNING sessions
            if candidate_session_ids:
                sess_placeholders = ",".join("?" for _ in candidate_session_ids)
                cur.execute(f"""
                    DELETE FROM scan_sessions
                    WHERE id IN ({sess_placeholders})
                      AND status != 'RUNNING'
                      AND id NOT IN (SELECT DISTINCT scan_session_id FROM scan_items WHERE scan_session_id IS NOT NULL)
                """, tuple(candidate_session_ids))

            from backend.repositories.group_repo import PhotoGroupRepository
            PhotoGroupRepository(self.conn).repair_groups()

            self.conn.commit()

        except Exception:
            self.conn.rollback()
            raise

        # The purge has committed. Cache cleanup failure cannot undo that commit.
        self._evict_unreferenced_thumbnails(set(sha_hashes))
        return lib_deleted

    def _evict_unreferenced_thumbnails(self, sha_hashes: set[str]) -> None:
        """Check all surviving references while reserving SQLite's writer slot.

        BEGIN IMMEDIATE closes the check/unlink race with every catalog writer,
        including an indexer on another connection. Archived, disabled and
        offline sources count equally. Cleanup is best effort after purge commit.
        """
        from backend.config import get_thumbnails_dir

        try:
            thumb_dir = get_thumbnails_dir()
            self.conn.execute("BEGIN IMMEDIATE")
            for sha in sha_hashes:
                if self.conn.execute("SELECT 1 FROM images WHERE sha256 = ? LIMIT 1", (sha,)).fetchone():
                    continue
                try:
                    (thumb_dir / f"{sha}.webp").unlink(missing_ok=True)
                except OSError:
                    logger.warning("A purged library's unreferenced thumbnail could not be removed.")
            self.conn.commit()
        except Exception:
            self.conn.rollback()  # Only the cleanup reservation, never the completed purge.
            logger.warning("Library purge completed; thumbnail cleanup was deferred.")

    def delete(self, library_id: int, purge_permanently: bool = False) -> bool:
        """Removes folder from monitoring. Defaults to non-destructive archive unless purge_permanently is explicitly True."""
        if not purge_permanently:
            return self.archive(library_id)
        return self.purge(library_id)

    def update_last_indexed(self, library_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("UPDATE libraries SET last_indexed_at = ? WHERE id = ?", (now, library_id))
        self.conn.commit()
