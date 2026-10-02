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

    # Safely deduplicate historical duplicates, preserving human review state and full timestamp spans
    cur.execute("""
        SELECT image_id, source_kind, COALESCE(page_url, '') AS p_url, COALESCE(candidate_image_url, '') AS c_url, COUNT(*) AS cnt
        FROM matches
        GROUP BY image_id, source_kind, COALESCE(page_url, ''), COALESCE(candidate_image_url, '')
        HAVING cnt > 1
    """)
    duplicate_groups = cur.fetchall()

    for group in duplicate_groups:
        cur.execute("""
            SELECT * FROM matches
            WHERE image_id = ? AND source_kind = ?
              AND COALESCE(page_url, '') = ? AND COALESCE(candidate_image_url, '') = ?
            ORDER BY
                (classification != 'UNREVIEWED') DESC,
                (notes IS NOT NULL AND TRIM(notes) != '') DESC,
                (is_new = 0) DESC,
                id DESC
        """, (group["image_id"], group["source_kind"], group["p_url"], group["c_url"]))
        rows = cur.fetchall()

        keeper = rows[0]
        other_ids = [r["id"] for r in rows[1:]]

        earliest_first = min(r["first_seen_at"] for r in rows if r["first_seen_at"])
        latest_last = max(r["last_seen_at"] for r in rows if r["last_seen_at"])

        best_class = keeper["classification"]
        best_classified_at = keeper["classified_at"]
        if best_class == "UNREVIEWED":
            for r in rows:
                if r["classification"] != "UNREVIEWED":
                    best_class = r["classification"]
                    best_classified_at = r["classified_at"]
                    break

        best_notes = keeper["notes"]
        if not best_notes or not best_notes.strip():
            for r in rows:
                if r["notes"] and r["notes"].strip():
                    best_notes = r["notes"]
                    break

        is_new = 0 if any(r["is_new"] == 0 for r in rows) else keeper["is_new"]
        ack_at = keeper["acknowledged_at"]
        if not ack_at:
            for r in rows:
                if r["acknowledged_at"]:
                    ack_at = r["acknowledged_at"]
                    break

        cur.execute("""
            UPDATE matches
            SET first_seen_at = ?,
                last_seen_at = ?,
                classification = ?,
                classified_at = ?,
                notes = ?,
                is_new = ?,
                acknowledged_at = ?
            WHERE id = ?
        """, (earliest_first, latest_last, best_class, best_classified_at, best_notes, is_new, ack_at, keeper["id"]))

        placeholders = ",".join("?" for _ in other_ids)
        cur.execute(f"DELETE FROM matches WHERE id IN ({placeholders})", tuple(other_ids))


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

def migration_006_project_classification(conn: sqlite3.Connection) -> None:
    """Adds project column to images and subfolders_as_projects to libraries."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(images)")
    image_cols = {row[1] for row in cur.fetchall()}
    if "project" not in image_cols:
        conn.execute("ALTER TABLE images ADD COLUMN project TEXT;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_images_project ON images(project);")

    cur.execute("PRAGMA table_info(libraries)")
    lib_cols = {row[1] for row in cur.fetchall()}
    if "subfolders_as_projects" not in lib_cols:
        conn.execute("ALTER TABLE libraries ADD COLUMN subfolders_as_projects INTEGER NOT NULL DEFAULT 1;")

def migration_007_project_source_and_atomic_running_scan(conn: sqlite3.Connection) -> None:
    """Adds project_source to images, marks legacy orphaned running sessions as interrupted, and creates atomic partial unique index for running scans."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(images)")
    image_cols = {row[1] for row in cur.fetchall()}
    if "project_source" not in image_cols:
        conn.execute("ALTER TABLE images ADD COLUMN project_source TEXT NOT NULL DEFAULT 'auto';")

    # Clean orphaned running sessions before indexing
    conn.execute("UPDATE scan_sessions SET status = 'INTERRUPTED' WHERE status = 'RUNNING';")

    # Create atomic partial unique index guaranteeing only one active RUNNING scan at database level
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_single_running_scan 
        ON scan_sessions(status) 
        WHERE status = 'RUNNING';
    """)

def migration_008_image_mtime_ns(conn: sqlite3.Connection) -> None:
    """Adds file_modified_at_ns column to images table without lossy float backfill."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(images)")
    image_cols = {row[1] for row in cur.fetchall()}
    if "file_modified_at_ns" not in image_cols:
        conn.execute("ALTER TABLE images ADD COLUMN file_modified_at_ns INTEGER;")

def migration_009_perceptual_grouping(conn: sqlite3.Connection) -> None:
    """Creates photo_groups and dismissed_group_candidates tables, adds dhash, photo_group_id,
    and is_primary_representation to images table.
    """
    # 1. Create photo_groups table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS photo_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            preferred_image_id INTEGER REFERENCES images(id) ON DELETE SET NULL,
            notes TEXT
        );
    """)

    # 2. Create dismissed_group_candidates table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS dismissed_group_candidates (
            image_a_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
            image_b_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (image_a_id, image_b_id)
        );
    """)

    # 3. Add columns to images table
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(images)")
    image_cols = {row[1] for row in cur.fetchall()}
    if "dhash" not in image_cols:
        conn.execute("ALTER TABLE images ADD COLUMN dhash TEXT;")
    if "photo_group_id" not in image_cols:
        conn.execute("ALTER TABLE images ADD COLUMN photo_group_id INTEGER REFERENCES photo_groups(id) ON DELETE SET NULL;")
    if "is_primary_representation" not in image_cols:
        conn.execute("ALTER TABLE images ADD COLUMN is_primary_representation INTEGER NOT NULL DEFAULT 1;")

    # 4. Create indexes
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_group ON images(photo_group_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_images_dhash ON images(dhash);")

def migration_010_group_candidate_generation(conn: sqlite3.Connection) -> None:
    """Creates a single-row generation counter bumped by triggers whenever any input of the
    candidate pair search changes (hashes, group membership, disk presence, library state,
    dismissals). The candidate search caches its results keyed on this counter.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_candidate_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            instance_token TEXT NOT NULL,
            generation INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.execute(
        "INSERT OR IGNORE INTO group_candidate_state (id, instance_token, generation) "
        "VALUES (1, lower(hex(randomblob(16))), 0);"
    )

    bump = "UPDATE group_candidate_state SET generation = generation + 1 WHERE id = 1;"
    triggers = {
        "trg_candidates_images_insert": "AFTER INSERT ON images",
        "trg_candidates_images_delete": "AFTER DELETE ON images",
        "trg_candidates_images_update": (
            "AFTER UPDATE ON images WHEN "
            "OLD.sha256 IS NOT NEW.sha256 OR OLD.dhash IS NOT NEW.dhash "
            "OR OLD.photo_group_id IS NOT NEW.photo_group_id "
            "OR OLD.is_present_on_disk IS NOT NEW.is_present_on_disk "
            "OR OLD.library_id IS NOT NEW.library_id"
        ),
        "trg_candidates_libraries_update": (
            "AFTER UPDATE ON libraries WHEN "
            "OLD.enabled IS NOT NEW.enabled OR OLD.is_archived IS NOT NEW.is_archived"
        ),
        "trg_candidates_libraries_delete": "AFTER DELETE ON libraries",
        "trg_candidates_dismissed_insert": "AFTER INSERT ON dismissed_group_candidates",
        "trg_candidates_dismissed_delete": "AFTER DELETE ON dismissed_group_candidates",
    }
    for name, clause in triggers.items():
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {name} {clause} BEGIN {bump} END;")

def migration_011_match_observation_folding(conn: sqlite3.Connection) -> None:
    """Keeps every physical provider observation while presenting one logical discovery per
    identity within a photo group. A row with canonical_match_id IS NULL is a logical discovery
    (and its own observation); a folded row is an observation of the logical discovery it points
    to, keeping its own original triage as provenance. Folding is reversible (ungroup, purge).
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(matches)")
    cols = {row[1] for row in cur.fetchall()}
    if "canonical_match_id" not in cols:
        conn.execute(
            "ALTER TABLE matches ADD COLUMN canonical_match_id INTEGER "
            "REFERENCES matches(id) ON DELETE SET NULL;"
        )
    if "fold_kind" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN fold_kind TEXT;")
    if "folded_at" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN folded_at TEXT;")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_canonical ON matches(canonical_match_id);")

def migration_012_observation_original_triage(conn: sqlite3.Connection) -> None:
    """Preserves a physical observation's own triage before its row starts carrying a merged
    logical discovery state (it becomes the canonical row of a group or receives a handover).
    obs_captured_at marks rows whose original triage lives in the obs_* columns.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(matches)")
    cols = {row[1] for row in cur.fetchall()}
    for name, sql_type in (
        ("obs_classification", "TEXT"),
        ("obs_classified_at", "TEXT"),
        ("obs_rule_id", "INTEGER"),
        ("obs_notes", "TEXT"),
        ("obs_is_new", "INTEGER"),
        ("obs_acknowledged_at", "TEXT"),
        ("obs_captured_at", "TEXT"),
    ):
        if name not in cols:
            conn.execute(f"ALTER TABLE matches ADD COLUMN {name} {sql_type};")

def migration_013_match_triage_conflict(conn: sqlite3.Connection) -> None:
    """Marks a logical discovery whose merged observations carry incompatible reviewed decisions.
    The mark persists through further merges until the user explicitly classifies the discovery.
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(matches)")
    cols = {row[1] for row in cur.fetchall()}
    if "triage_conflict" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN triage_conflict INTEGER NOT NULL DEFAULT 0;")

def migration_014_match_explicit_review(conn: sqlite3.Connection) -> None:
    """Records when the user explicitly reviewed a discovery (classification, acknowledgement or
    notes through the API), independently of the resulting values. Automatic merges and domain
    rules never set it. Used to decide whether a dissolved group's former canonical discovery
    returns to its original triage."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(matches)")
    cols = {row[1] for row in cur.fetchall()}
    if "explicit_review_at" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN explicit_review_at TEXT;")
    # When the logical discovery began carrying merged state (travels with handovers)
    if "merged_at" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN merged_at TEXT;")

def migration_015_discovery_inheritance(conn: sqlite3.Connection) -> None:
    """Records discoveries inherited from a permanently purged photo of the same group (handover
    or re-homing), which must never be "restored" away later, and adds the missing candidate
    generation trigger for new libraries."""
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(matches)")
    cols = {row[1] for row in cur.fetchall()}
    if "inherited_at" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN inherited_at TEXT;")
    if "inherited_from" not in cols:
        conn.execute("ALTER TABLE matches ADD COLUMN inherited_from TEXT;")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS trg_candidates_libraries_insert AFTER INSERT ON libraries "
        "BEGIN UPDATE group_candidate_state SET generation = generation + 1 WHERE id = 1; END;"
    )

MIGRATIONS: list[Migration] = [
    Migration(1, "001_initial_schema", migration_001_initial_schema),
    Migration(2, "002_library_archiving_and_disk_presence", migration_002_library_archiving_and_disk_presence),
    Migration(3, "003_scan_cancellation_and_recovery", migration_003_scan_cancellation_and_recovery),
    Migration(4, "004_matches_asset_only_and_uniqueness", migration_004_matches_asset_only_and_uniqueness),
    Migration(5, "005_library_fk_safety", migration_005_library_fk_safety),
    Migration(6, "006_project_classification", migration_006_project_classification),
    Migration(7, "007_project_source_and_atomic_running_scan", migration_007_project_source_and_atomic_running_scan),
    Migration(8, "008_image_mtime_ns", migration_008_image_mtime_ns),
    Migration(9, "009_perceptual_grouping", migration_009_perceptual_grouping),
    Migration(10, "010_group_candidate_generation", migration_010_group_candidate_generation),
    Migration(11, "011_match_observation_folding", migration_011_match_observation_folding),
    Migration(12, "012_observation_original_triage", migration_012_observation_original_triage),
    Migration(13, "013_match_triage_conflict", migration_013_match_triage_conflict),
    Migration(14, "014_match_explicit_review", migration_014_match_explicit_review),
    Migration(15, "015_discovery_inheritance", migration_015_discovery_inheritance),
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
                fk_cur = conn.cursor()
                fk_cur.execute("PRAGMA foreign_key_check;")
                violations = fk_cur.fetchall()
                if violations:
                    summary = [f"table={r[0]}, rowid={r[1]}, parent={r[2]}, fkid={r[3]}" for r in violations]
                    raise sqlite3.IntegrityError(
                        f"Foreign key integrity violation after migration {migration.version:03d}_{migration.name}: "
                        f"{'; '.join(summary)}"
                    )
                conn.commit()

                # Re-enable foreign keys after transaction commit and verify pragma state
                conn.execute("PRAGMA foreign_keys = ON;")
                fk_cur.execute("PRAGMA foreign_keys;")
                fk_state = fk_cur.fetchone()[0]
                if fk_state != 1:
                    raise sqlite3.IntegrityError(f"Failed to re-enable PRAGMA foreign_keys after migration {migration.version:03d}")

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
