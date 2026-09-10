"""SQLite database connection and schema management for Photo Privateer."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator
from pathlib import Path
from backend.config import DB_PATH

SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    recursive INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_indexed_at TEXT
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    sha256 TEXT NOT NULL,
    file_path TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    file_modified_at REAL NOT NULL,
    width INTEGER,
    height INTEGER,
    format TEXT,
    indexed_at TEXT NOT NULL,
    last_seen_on_disk TEXT NOT NULL,
    last_scanned_at TEXT,
    scan_count INTEGER NOT NULL DEFAULT 0,
    match_count INTEGER NOT NULL DEFAULT 0,
    unreviewed_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scan_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    provider TEXT NOT NULL,
    total_images INTEGER NOT NULL,
    processed_images INTEGER NOT NULL DEFAULT 0,
    successful_images INTEGER NOT NULL DEFAULT 0,
    failed_images INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS scan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_session_id INTEGER NOT NULL REFERENCES scan_sessions(id) ON DELETE CASCADE,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    error_message TEXT,
    matches_found INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain TEXT UNIQUE NOT NULL,
    classification TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    scan_session_id INTEGER REFERENCES scan_sessions(id) ON DELETE SET NULL,
    page_url TEXT NOT NULL,
    page_title TEXT,
    page_score REAL,
    domain TEXT NOT NULL,
    candidate_image_url TEXT,
    match_type TEXT NOT NULL,
    provider TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    is_new INTEGER NOT NULL DEFAULT 1,
    classification TEXT NOT NULL DEFAULT 'UNREVIEWED',
    classified_at TEXT,
    auto_classified_by_rule_id INTEGER REFERENCES domain_rules(id) ON DELETE SET NULL,
    notes TEXT,
    UNIQUE(image_id, page_url, candidate_image_url)
);

CREATE TABLE IF NOT EXISTS provider_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    billing_period TEXT NOT NULL,
    scan_session_id INTEGER REFERENCES scan_sessions(id) ON DELETE SET NULL,
    image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
    attempted_units INTEGER NOT NULL DEFAULT 1,
    successful_units INTEGER NOT NULL DEFAULT 0,
    failed_units INTEGER NOT NULL DEFAULT 0,
    request_status TEXT NOT NULL,
    estimated_cost REAL NOT NULL DEFAULT 0.0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_images_library_id ON images(library_id);
CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);
CREATE INDEX IF NOT EXISTS idx_matches_image_id ON matches(image_id);
CREATE INDEX IF NOT EXISTS idx_matches_domain ON matches(domain);
CREATE INDEX IF NOT EXISTS idx_matches_classification ON matches(classification);
CREATE INDEX IF NOT EXISTS idx_provider_calls_period ON provider_calls(billing_period);
"""

def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    target_path = db_path if db_path is not None else DB_PATH
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
    target_path = db_path if db_path is not None else DB_PATH
    Path(target_path).parent.mkdir(parents=True, exist_ok=True)
    with get_connection(target_path) as conn:
        from backend.migrations.runner import run_migrations
        applied = run_migrations(conn)
        return applied

