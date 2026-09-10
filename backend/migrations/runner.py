"""Versioned SQLite schema migration runner for Photo Privateer."""
from __future__ import annotations

import sqlite3
import logging
from datetime import datetime, timezone
from typing import Callable, NamedTuple

logger = logging.getLogger("photo_privateer.migrations")

class Migration(NamedTuple):
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]

# --- Migration Definitions ---

def migration_001_initial_schema(conn: sqlite3.Connection) -> None:
    """Creates baseline schema if starting on a completely fresh database."""
    conn.executescript("""
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
            library_id INTEGER NOT NULL REFERENCES libraries(id),
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
            page_url TEXT,
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
            notes TEXT
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
    """)

def migration_002_library_archiving_and_disk_presence(conn: sqlite3.Connection) -> None:
    """Adds is_archived column to libraries and is_present_on_disk column to images."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(libraries)")
    lib_cols = {row["name"] for row in cur.fetchall()}
    if "is_archived" not in lib_cols:
        conn.execute("ALTER TABLE libraries ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0")

    cur.execute("PRAGMA table_info(images)")
    img_cols = {row["name"] for row in cur.fetchall()}
    if "is_present_on_disk" not in img_cols:
        conn.execute("ALTER TABLE images ADD COLUMN is_present_on_disk INTEGER NOT NULL DEFAULT 1")

def migration_003_scan_cancellation_and_recovery(conn: sqlite3.Connection) -> None:
    """Adds cancel_requested column to scan_sessions."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(scan_sessions)")
    cols = {row["name"] for row in cur.fetchall()}
    if "cancel_requested" not in cols:
        conn.execute("ALTER TABLE scan_sessions ADD COLUMN cancel_requested INTEGER NOT NULL DEFAULT 0")

def migration_004_matches_asset_only_and_uniqueness(conn: sqlite3.Connection) -> None:
    """Adds source_kind and acknowledged_at to matches, and sets up deterministic unique index."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(matches)")
    cols = {row["name"] for row in cur.fetchall()}

    if "source_kind" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'PAGE'")
    if "acknowledged_at" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN acknowledged_at TEXT")

    # Create deterministic unique index that handles NULL candidate_image_url and NULL page_url safely
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_matches_unique_identity 
        ON matches(image_id, source_kind, COALESCE(page_url, ''), COALESCE(candidate_image_url, ''))
    """)

def migration_005_library_fk_safety(conn: sqlite3.Connection) -> None:
    """Ensures images table does not cascade-delete on library deletion."""
    # Check if images table references libraries with ON DELETE CASCADE
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_key_list(images)")
    fks = cur.fetchall()
    has_cascade = any(fk["table"] == "libraries" and fk["on_delete"].upper() == "CASCADE" for fk in fks)
    
    if has_cascade:
        # Recreate images table with ON DELETE RESTRICT to protect historical data
        conn.executescript("""
            CREATE TABLE images_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE RESTRICT,
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
                unreviewed_count INTEGER NOT NULL DEFAULT 0,
                is_present_on_disk INTEGER NOT NULL DEFAULT 1
            );

            INSERT INTO images_new (
                id, library_id, sha256, file_path, filename, file_size, file_modified_at,
                width, height, format, indexed_at, last_seen_on_disk, last_scanned_at,
                scan_count, match_count, unreviewed_count, is_present_on_disk
            )
            SELECT 
                id, library_id, sha256, file_path, filename, file_size, file_modified_at,
                width, height, format, indexed_at, last_seen_on_disk, last_scanned_at,
                scan_count, match_count, unreviewed_count,
                COALESCE(is_present_on_disk, 1)
            FROM images;

            DROP TABLE images;
            ALTER TABLE images_new RENAME TO images;

            CREATE INDEX IF NOT EXISTS idx_images_library_id ON images(library_id);
            CREATE INDEX IF NOT EXISTS idx_images_sha256 ON images(sha256);
        """)

MIGRATIONS: list[Migration] = [
    Migration(1, "001_initial_schema", migration_001_initial_schema),
    Migration(2, "002_library_archiving_and_disk_presence", migration_002_library_archiving_and_disk_presence),
    Migration(3, "003_scan_cancellation_and_recovery", migration_003_scan_cancellation_and_recovery),
    Migration(4, "004_matches_asset_only_and_uniqueness", migration_004_matches_asset_only_and_uniqueness),
    Migration(5, "005_library_fk_safety", migration_005_library_fk_safety),
]

def run_migrations(conn: sqlite3.Connection) -> list[int]:
    """Runs all unapplied migrations in sequential order.
    Returns the list of migration versions applied.
    """
    cur = conn.cursor()
    
    # 1. Ensure schema_migrations table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()

    # 2. Check if this is an existing database from before schema_migrations was introduced
    cur.execute("SELECT COUNT(*) FROM schema_migrations")
    migration_count = cur.fetchone()[0]
    
    if migration_count == 0:
        # Check if legacy tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='libraries'")
        if cur.fetchone() is not None:
            # Legacy DB exists: record migration 1 as already applied
            now = datetime.now(timezone.utc).isoformat()
            cur.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (1, "001_initial_schema", now),
            )
            conn.commit()
            logger.info("Existing legacy database detected. Marked migration 001 as baseline.")

    # 3. Fetch already applied versions
    cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
    applied_versions = {row[0] for row in cur.fetchall()}

    applied_now: list[int] = []

    # 4. Apply unapplied migrations in order
    for migration in MIGRATIONS:
        if migration.version not in applied_versions:
            logger.info(f"Applying migration {migration.version:03d}_{migration.name}...")
            now = datetime.now(timezone.utc).isoformat()
            try:
                # Temporarily disable foreign keys during schema alterations if necessary
                conn.execute("PRAGMA foreign_keys = OFF;")
                migration.up(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, now),
                )
                conn.commit()
                conn.execute("PRAGMA foreign_keys = ON;")
                applied_now.append(migration.version)
                logger.info(f"Migration {migration.version:03d}_{migration.name} applied successfully.")
            except Exception as e:
                conn.rollback()
                conn.execute("PRAGMA foreign_keys = ON;")
                logger.error(f"Migration {migration.version:03d}_{migration.name} failed: {e}")
                raise

    return applied_now


def get_applied_migrations(conn: sqlite3.Connection) -> list[int]:
    """Returns a sorted list of all applied migration versions."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
    if not cur.fetchone():
        return []
    cur.execute("SELECT version FROM schema_migrations ORDER BY version ASC")
    return [row[0] for row in cur.fetchall()]
