"""SQLite database connection and schema management for Photo Privateer."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional
from pathlib import Path
from backend.config import get_db_path as default_get_db_path

_OVERRIDE_DB_PATH: Optional[Path] = None

def set_db_path(path: Path | str | None) -> None:
    """Sets an explicit database file path override (primarily used in tests and custom environments)."""
    global _OVERRIDE_DB_PATH
    _OVERRIDE_DB_PATH = Path(path).resolve() if path is not None else None

def get_db_path() -> Path:
    """Returns currently active database file path (override or default canonical)."""
    if _OVERRIDE_DB_PATH is not None:
        return _OVERRIDE_DB_PATH
    return default_get_db_path()

def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target_path = Path(db_path).resolve() if db_path is not None else get_db_path()
    conn = sqlite3.connect(str(target_path), check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 10000;")
    return conn

@contextmanager
def get_db(db_path: Path | str | None = None) -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path: Path | str | None = None) -> list[int]:
    target_path = Path(db_path).resolve() if db_path is not None else get_db_path()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(target_path) as conn:
        from backend.migrations.runner import run_migrations
        applied = run_migrations(conn)
        return applied

