"""Regression tests for v1.2.0 modernization, correctness, and accounting invariants.

Covers:
1. Free-tier guard validation ordering (filter usable scannable images first, then project units).
2. Scan worker persistence isolation and counter consistency (processed == successful + failed on DB error).
3. Billable unit cost calculation across free-tier boundary crossings.
4. last_seen_on_disk updating on unchanged observed images without rehashing.
5. Migration 004 deduplication safely preserving human-reviewed classification, notes, and timestamps.
6. Post-migration foreign key check enforcement.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from PIL import Image

from backend.models import (
    ImageOut,
)
from backend.providers.base import (
    ProviderResult,
    SearchResultItem,
)
from backend.repositories.image_repo import ImageRepository
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.usage_repo import UsageRepository, get_current_billing_period
from backend.services.scan_engine import ScanEngine
from backend.services.usage_tracker import UsageTracker


def test_free_tier_guard_validation_ordering(repos, sample_images_dir: Path):
    """Verifies that free-tier guard evaluates scannable images after filtering missing/offline images."""
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]
    settings_repo = repos["settings_repo"]
    usage_repo = repos["usage_repo"]
    scan_engine = repos["scan_engine"]

    # Index sample images
    lib = lib_repo.create(path=str(sample_images_dir), name="OrderingTest")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) >= 2

    img1 = images[0]
    img2 = images[1]

    # Configure Google Vision settings with free-tier guard enabled
    settings_repo.update_settings({
        "active_provider": "google_vision",
        "free_tier_monthly_units": 1000,
        "block_on_free_tier_exceeded": True,
    })

    # Set current usage to 999 units (1 unit remaining before guard triggers)
    period = get_current_billing_period()
    usage_repo.conn.execute(
        "DELETE FROM provider_calls WHERE billing_period = ? AND provider = 'google_vision'",
        (period,),
    )
    usage_repo.record_call(
        provider="google_vision",
        billing_period=period,
        scan_session_id=None,
        image_id=None,
        attempted_units=999,
        successful_units=999,
        failed_units=0,
        request_status="SUCCESS",
        estimated_cost=0.0,
    )
    assert usage_repo.get_period_units(period, provider="google_vision") == 999

    # Mark img2 as missing on disk (is_present_on_disk = 0)
    img_repo.conn.execute(
        "UPDATE images SET is_present_on_disk = 0 WHERE id = ?",
        (img2.id,),
    )
    img_repo.conn.commit()

    # Case A: Request scan with [img1, img2].
    # Total requested: 2. Usable: 1 (img1).
    # Correct ordering: usable (1) + current (999) = 1000 <= 1000 allowance.
    # Should PASS validation without error and return img1.
    usable, missing = scan_engine.validate_scan_request(
        image_ids=[img1.id, img2.id],
        provider_override="google_vision",
        force_override_guard=False,
    )
    assert len(usable) == 1
    assert usable[0].id == img1.id
    assert missing == [img2.id]

    # Case B: Mark img2 back present on disk.
    # Now both img1 and img2 are usable (2 images).
    # Usable (2) + current (999) = 1001 > 1000 allowance.
    # Guard MUST trigger and block.
    img_repo.conn.execute(
        "UPDATE images SET is_present_on_disk = 1 WHERE id = ?",
        (img2.id,),
    )
    img_repo.conn.commit()

    with pytest.raises(ValueError, match="Scan blocked by free tier allowance guard"):
        scan_engine.validate_scan_request(
            image_ids=[img1.id, img2.id],
            provider_override="google_vision",
            force_override_guard=False,
        )


def test_scan_worker_persistence_error_isolation_and_counter_consistency(repos, sample_images_dir: Path, monkeypatch):
    """Verifies two-phase persistence isolation:
    If match persistence fails with a database error:
    - Provider call accounting remains durably committed (Phase A).
    - Failed match transaction rolls back (Phase B).
    - Session records failed += 1, processed += 1, successful += 0.
    - Invariant holds: processed == successful + failed.
    """
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]
    usage_repo = repos["usage_repo"]
    scan_engine = repos["scan_engine"]
    settings_repo = repos["settings_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="WorkerIsolationTest")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) > 0
    test_img = images[0]

    # Create a scan session
    session = usage_repo.create_scan_session(
        provider="mock",
        total_images=1,
    )

    # Monkeypatch MatchRepository.upsert_match to simulate SQLite disk failure during match persistence
    def failing_upsert(*args, **kwargs):
        raise sqlite3.DatabaseError("Simulated disk error during match persistence")

    monkeypatch.setattr(MatchRepository, "upsert_match", failing_upsert)

    settings = settings_repo.get_app_settings()

    # Run the worker synchronously
    scan_engine._run_scan_worker(
        session_id=session.id,
        ordered_image_ids=[test_img.id],
        provider_id="mock",
        credentials_path=None,
        free_tier_allowance=settings.free_tier_monthly_units,
        unit_price_usd=settings.unit_price_usd,
        db_path=scan_engine.db_path,
    )

    # Inspect final session state in DB
    updated_session = usage_repo.get_scan_session(session.id)
    assert updated_session is not None
    assert updated_session.total_images == 1
    assert updated_session.successful_images == 0
    assert updated_session.failed_images == 1
    assert updated_session.processed_images == 1
    assert updated_session.processed_images == (updated_session.successful_images + updated_session.failed_images)
    assert updated_session.status == "FAILED"

    # Verify that the provider call was durably recorded in Phase A
    calls = usage_repo.conn.execute(
        "SELECT COUNT(*) FROM provider_calls WHERE scan_session_id = ?",
        (session.id,),
    ).fetchone()[0]
    assert calls == 1

    # Verify that an ERROR scan item was recorded
    cur = usage_repo.conn.cursor()
    cur.execute(
        "SELECT status, error_message FROM scan_items WHERE scan_session_id = ?",
        (session.id,),
    )
    items = cur.fetchall()
    assert len(items) == 1
    assert items[0]["status"] == "ERROR"
    assert "Database persistence error" in (items[0]["error_message"] or "")


def test_billable_unit_cost_calculation_boundaries(repos):
    """Verifies mathematical correctness of incremental billable units across boundary crossings."""
    settings_repo = repos["settings_repo"]
    usage_repo = repos["usage_repo"]
    tracker = repos["tracker"]

    settings_repo.update_settings({
        "active_provider": "google_vision",
        "free_tier_monthly_units": 1000,
        "unit_price_usd": 0.0035,
        "block_on_free_tier_exceeded": False,
    })
    period = get_current_billing_period()

    def set_usage(units: int):
        usage_repo.conn.execute("DELETE FROM provider_calls WHERE billing_period = ?", (period,))
        if units > 0:
            usage_repo.record_call(
                provider="google_vision",
                billing_period=period,
                scan_session_id=None,
                image_id=None,
                attempted_units=units,
                successful_units=units,
                failed_units=0,
                request_status="SUCCESS",
                estimated_cost=0.0,
            )
        usage_repo.conn.commit()

    # Scenario 1: 999 used, 1 attempted -> 0 billable, $0.00 cost
    set_usage(999)
    resp1 = tracker.prepare_scan_projection(image_count=1)
    assert resp1.estimated_incremental_cost_usd == 0.0
    assert resp1.free_tier_exceeded is False

    # Scenario 2: 1000 used, 1 attempted -> 1 billable, $0.0035 cost
    set_usage(1000)
    resp2 = tracker.prepare_scan_projection(image_count=1)
    assert round(resp2.estimated_incremental_cost_usd, 4) == 0.0035
    assert resp2.free_tier_exceeded is True

    # Scenario 3: 999 used, 2 attempted -> 1 billable, $0.0035 cost
    set_usage(999)
    resp3 = tracker.prepare_scan_projection(image_count=2)
    assert round(resp3.estimated_incremental_cost_usd, 4) == 0.0035
    assert resp3.free_tier_exceeded is True

    # Scenario 4: 1005 used, 10 attempted -> 10 billable, $0.0350 cost
    set_usage(1005)
    resp4 = tracker.prepare_scan_projection(image_count=10)
    assert round(resp4.estimated_incremental_cost_usd, 4) == 0.0350


def test_last_seen_on_disk_updated_for_unchanged_files(repos, sample_images_dir: Path):
    """Verifies that indexing an unchanged file refreshes last_seen_on_disk and is_present_on_disk without rehashing."""
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]

    lib = lib_repo.create(path=str(sample_images_dir), name="TouchTest")
    res1 = indexer.index_library(lib.id)
    assert res1["added_or_updated"] > 0

    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) > 0
    img = images[0]

    # Artificially set an old timestamp and mark offline
    old_ts = "2020-01-01 00:00:00"
    img_repo.conn.execute(
        "UPDATE images SET last_seen_on_disk = ?, is_present_on_disk = 0 WHERE id = ?",
        (old_ts, img.id),
    )
    img_repo.conn.commit()

    # Re-index library
    res2 = indexer.index_library(lib.id)
    assert res2["unchanged"] > 0

    # Verify record was refreshed
    updated_img = img_repo.get_by_id(img.id)
    assert updated_img is not None
    assert updated_img.is_present_on_disk == 1
    assert updated_img.last_seen_on_disk > old_ts


def test_migration_004_deduplication_preserves_human_review(db_conn):
    """Verifies that migration 004 deduplication preserves human-reviewed classifications, notes, and span timestamps."""
    cur = db_conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    # Drop the unique index to simulate pre-migration-004 database state
    cur.execute("DROP INDEX IF EXISTS idx_matches_unique_identity")

    # Create dummy library and image
    cur.execute("INSERT INTO libraries (path, name, created_at) VALUES ('/test/photos', 'DedupLib', ?)", (now,))
    lib_id = cur.lastrowid
    cur.execute(
        """
        INSERT INTO images (
            library_id, sha256, file_path, filename, file_size, file_modified_at,
            indexed_at, last_seen_on_disk
        ) VALUES (?, 'dummyhash', '/test/photos/a.jpg', 'a.jpg', 100, 1.0, ?, ?)
        """,
        (lib_id, now, now),
    )
    img_id = cur.lastrowid

    # Insert two duplicate matches for the same image_id and domain
    # Row 1: unreviewed, early timestamp, is_new=1
    cur.execute(
        """
        INSERT INTO matches (
            image_id, domain, match_type, classification, notes, is_new,
            first_seen_at, last_seen_at, provider
        ) VALUES (?, 'dedup-test.com', 'FULL', 'UNREVIEWED', NULL, 1, '2026-01-01 10:00:00', '2026-01-02 10:00:00', 'mock')
        """,
        (img_id,),
    )
    row1_id = cur.lastrowid

    # Row 2: human reviewed, later timestamp, is_new=0
    cur.execute(
        """
        INSERT INTO matches (
            image_id, domain, match_type, classification, notes, is_new,
            first_seen_at, last_seen_at, provider
        ) VALUES (?, 'dedup-test.com', 'FULL', 'UNAUTHORIZED', 'Client infringement notice', 0, '2026-01-03 10:00:00', '2026-01-05 10:00:00', 'mock')
        """,
        (img_id,),
    )
    row2_id = cur.lastrowid
    db_conn.commit()

    # Execute the deduplication logic from migration_004
    from backend.migrations.runner import migration_004_matches_asset_only_and_uniqueness
    migration_004_matches_asset_only_and_uniqueness(db_conn)
    db_conn.commit()

    # Check remaining records
    cur.execute("SELECT id, classification, notes, is_new, first_seen_at, last_seen_at FROM matches WHERE image_id = ? AND domain = 'dedup-test.com'", (img_id,))
    rows = cur.fetchall()

    # Exactly 1 row must survive
    assert len(rows) == 1
    survivor = rows[0]

    # Must retain human classification and notes
    assert survivor["classification"] == "UNAUTHORIZED"
    assert survivor["notes"] == "Client infringement notice"
    assert survivor["is_new"] == 0

    # Must preserve spanning first_seen_at and last_seen_at
    assert survivor["first_seen_at"] == "2026-01-01 10:00:00"
    assert survivor["last_seen_at"] == "2026-01-05 10:00:00"


def test_post_migration_foreign_key_check(db_conn):
    """Verifies that PRAGMA foreign_key_check detects integrity violations."""
    cur = db_conn.cursor()
    now = datetime.now(timezone.utc).isoformat()
    cur.execute("PRAGMA foreign_keys = OFF")
    # Insert orphan image pointing to non-existent library 99999
    cur.execute(
        """
        INSERT INTO images (
            library_id, sha256, file_path, filename, file_size, file_modified_at,
            indexed_at, last_seen_on_disk
        ) VALUES (99999, 'orphan_hash', '/nowhere/orphan.jpg', 'orphan.jpg', 50, 1.0, ?, ?)
        """,
        (now, now),
    )
    cur.execute("PRAGMA foreign_keys = ON")

    # Running foreign_key_check directly must report the violation
    cur.execute("PRAGMA foreign_key_check")
    violations = cur.fetchall()
    assert len(violations) > 0
    assert violations[0][0] == "images"

    # Clean up orphan
    cur.execute("DELETE FROM images WHERE sha256 = 'orphan_hash'")
    db_conn.commit()
