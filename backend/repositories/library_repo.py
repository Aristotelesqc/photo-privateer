"""Repository for photo libraries."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from backend.models import LibraryOut

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
        norm_path = str(Path(path).resolve())
        folder_name = name or Path(norm_path).name or norm_path
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO libraries (path, name, enabled, recursive, is_archived, subfolders_as_projects, created_at)
            VALUES (?, ?, 1, ?, 0, ?, ?)
        """, (norm_path, folder_name, int(recursive), int(subfolders_as_projects), now))
        lib_id = cur.lastrowid
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
        return self.get_by_id(library_id)

    def archive(self, library_id: int) -> bool:
        """Non-destructively archives a library (stops monitoring without deleting images or matches)."""
        cur = self.conn.cursor()
        cur.execute("UPDATE libraries SET is_archived = 1, enabled = 0 WHERE id = ?", (library_id,))
        return cur.rowcount > 0

    def unarchive(self, library_id: int) -> bool:
        """Restores an archived library to active monitoring."""
        cur = self.conn.cursor()
        cur.execute("UPDATE libraries SET is_archived = 0, enabled = 1 WHERE id = ?", (library_id,))
        return cur.rowcount > 0

    def delete(self, library_id: int, purge_permanently: bool = False) -> bool:
        """Safely removes folder from monitoring. Defaults to non-destructive archive."""
        if not purge_permanently:
            return self.archive(library_id)
        cur = self.conn.cursor()
        cur.execute("DELETE FROM libraries WHERE id = ?", (library_id,))
        return cur.rowcount > 0

    def update_last_indexed(self, library_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("UPDATE libraries SET last_indexed_at = ? WHERE id = ?", (now, library_id))
