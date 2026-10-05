"""Explicit offline library root remapping; never touches original source bytes.

Importing this module does not initialize the application, configuration or DB.
The caller selects a profile and owns presentation/confirmation of the dry-run.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
from uuid import uuid4

from backend.services.catalog_backup import DATABASE_NAME, backup_catalog, readonly_database
from backend.services.profile_lock import profile_lease


class RelinkError(ValueError):
    pass


def _path_key(path: Path) -> str:
    # Windows is the supported desktop target. Conservative case folding also
    # catches a Windows profile's case-only collision when inspecting elsewhere.
    return str(path.resolve()).casefold()


def _overlaps(left: Path, right: Path) -> bool:
    left_key, right_key = _path_key(left), _path_key(right)
    return (
        left_key == right_key
        or left_key.startswith(right_key.rstrip("/\\") + os.sep)
        or right_key.startswith(left_key.rstrip("/\\") + os.sep)
    )


def _presence(path: Path, root: Path, sha256: str) -> bool:
    """Hash only contained regular files; fail closed on links escaping the root."""
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise RelinkError(f"Relinked source escapes the new library root: {path}")
    if not os.path.lexists(path):
        return False
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root):
            raise RelinkError(f"Relinked source escapes the new library root: {path}")
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise RelinkError(f"Relinked source must be a regular file: {path}")
        with resolved.open("rb") as stream:
            before = os.fstat(stream.fileno())
            actual_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
        current = path.stat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current) or path.resolve() != resolved:
            raise RelinkError(f"Relinked source changed during verification: {path}")
        if actual_hash != sha256:
            raise RelinkError(f"SHA-256 mismatch for relinked source: {path}")
        return True
    except OSError as exc:
        raise RelinkError(f"Cannot verify relinked source: {path}") from exc


def _projection(conn: sqlite3.Connection, library_id: int, new_root: Path) -> tuple[dict, dict]:
    libraries = [dict(row) for row in conn.execute("SELECT * FROM libraries ORDER BY id")]
    library = next((row for row in libraries if row["id"] == library_id), None)
    if library is None:
        raise RelinkError(f"Library #{library_id} does not exist in this profile")
    old_root = Path(library["path"])
    if not old_root.is_absolute():
        raise RelinkError("Catalog library root must be an absolute path")
    # Relative remapping is lexical. An absent/replaced old drive is not read,
    # and a newly installed symlink at its former path cannot rewrite history.
    old_root = old_root.absolute()
    if not new_root.is_dir():
        raise RelinkError(f"New library root must be an existing directory: {new_root}")
    for other in libraries:
        if other["id"] != library_id and _overlaps(new_root, Path(other["path"])):
            raise RelinkError(f"New root overlaps library #{other['id']} (including archived libraries)")

    rows = [dict(row) for row in conn.execute("SELECT * FROM images ORDER BY id")]
    occupied = {
        _path_key(Path(row["file_path"])): row["id"]
        for row in rows if row["library_id"] != library_id
    }
    changes = []
    seen: dict[str, int] = {}
    for row in rows:
        if row["library_id"] != library_id:
            continue
        old_path = Path(row["file_path"])
        suffix = f"#archived-{row['id']}"
        alias = str(old_path).endswith(suffix)
        base = Path(str(old_path)[:-len(suffix)]) if alias else old_path
        if not base.is_absolute():
            raise RelinkError(f"Image #{row['id']} has a non-absolute catalog path")
        try:
            relative = base.relative_to(old_root)
        except ValueError as exc:
            raise RelinkError(f"Image #{row['id']} does not belong beneath its catalog library root") from exc
        if not relative.parts or ".." in relative.parts:
            raise RelinkError(f"Image #{row['id']} has an unsafe relative source path")
        target_base = new_root / relative
        target = Path(str(target_base) + suffix) if alias else target_base
        # Archive aliases are catalog-only history. Never probe/open them as
        # files, even if an actual file with that sentinel name exists.
        if alias:
            key = str(target.absolute()).casefold()
            present = False
        else:
            key = _path_key(target)
            present = _presence(target, new_root, row["sha256"])
        if key in occupied or key in seen:
            conflicting = occupied.get(key, seen.get(key))
            raise RelinkError(f"Relinked image #{row['id']} collides with catalog image #{conflicting}")
        seen[key] = row["id"]
        changes.append({
            "image_id": row["id"], "old_path": row["file_path"], "new_path": str(target),
            "was_present": bool(row["is_present_on_disk"]), "is_present": present,
            "archived_alias": alias,
        })
    projection = {
        "library_id": library_id, "old_root": str(old_root), "new_root": str(new_root),
        "image_count": len(changes),
        "present_count": sum(change["is_present"] for change in changes),
        "missing_count": sum(not change["is_present"] and not change["archived_alias"] for change in changes),
        "archived_alias_count": sum(change["archived_alias"] for change in changes),
        "changes": changes,
    }
    return projection, {"libraries": libraries, "images": rows}


def relink_library(profile: Path, library_id: int, new_root: Path, apply: bool = False) -> dict:
    """Project by default; apply only after a verified pre-relink backup.

    Only libraries.path and images.file_path/is_present_on_disk change. Missing
    sources remain missing and archive aliases remain absent. Matching files can
    restore presence; library enabled/archive flags still govern eligibility.
    An external process changing original files after verification is outside the
    profile OS lock; the scan/original services still revalidate source access.
    """
    profile, new_root = Path(profile).resolve(), Path(new_root).resolve()
    db_path = profile / DATABASE_NAME
    if not profile.is_dir() or not db_path.is_file() or db_path.resolve().parent != profile:
        raise RelinkError("Selected profile must contain its own existing catalog")
    try:
        with profile_lease(profile):
            with closing(readonly_database(db_path)) as conn:
                projection, source_state = _projection(conn, library_id, new_root)
            if not apply:
                return {**projection, "applied": False, "backup_path": None}

            backups = profile / "backups"
            if backups.resolve().parent != profile or (backups.exists() and not backups.is_dir()):
                raise RelinkError("Profile backup directory must stay inside the selected profile")
            destination = backups / f"relink-{uuid4()}"
            # backup_catalog verifies the complete SQLite/artifact bundle before
            # publishing it and returns only after verification succeeds.
            backup_catalog(db_path, profile, destination)
            with closing(sqlite3.connect(db_path.as_uri() + "?mode=rw", uri=True, timeout=10)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute("BEGIN IMMEDIATE")
                try:
                    # Re-hash and re-check roots/collisions under the writer
                    # reservation. A changed projection must be reviewed again.
                    if _projection(conn, library_id, new_root) != (projection, source_state):
                        raise RelinkError("Catalog/source projection changed; run a new dry-run before applying")
                    # A new root can be nested beneath its former root. Stage
                    # all paths to unique catalog-only sentinels so one old
                    # row cannot temporarily occupy another's final path.
                    token = uuid4()
                    intermediate = [
                        (f"{change['old_path']}#relink-{token}-{change['image_id']}", change["image_id"])
                        for change in projection["changes"]
                    ]
                    for path, image_id in intermediate:
                        if conn.execute("SELECT 1 FROM images WHERE file_path = ?", (path,)).fetchone():
                            raise RelinkError("Temporary relink path collides with catalog history")
                        conn.execute("UPDATE images SET file_path = ? WHERE id = ?", (path, image_id))
                    conn.execute("UPDATE libraries SET path = ? WHERE id = ?", (str(new_root), library_id))
                    conn.executemany(
                        "UPDATE images SET file_path = ?, is_present_on_disk = ? WHERE id = ? AND library_id = ?",
                        [(change["new_path"], int(change["is_present"]), change["image_id"], library_id)
                         for change in projection["changes"]],
                    )
                    if conn.execute("PRAGMA foreign_key_check").fetchall():
                        raise RelinkError("Relink would violate catalog foreign keys")
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise
            return {**projection, "applied": True, "backup_path": str(destination)}
    except (OSError, sqlite3.Error) as exc:
        raise RelinkError("Relink could not complete; the catalog was not partially remapped") from exc
