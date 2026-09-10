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
import threading
import time
import shutil
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


def test_scan_worker_fails_closed_on_accounting_persistence_failure(repos, sample_images_dir: Path, monkeypatch):
    """Verifies that if provider call accounting cannot be durably recorded after a request,
    the worker immediately FAILS CLOSED, aborts the batch, and prevents subsequent images
    from being sent to the provider.
    """
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]
    usage_repo = repos["usage_repo"]
    scan_engine = repos["scan_engine"]
    settings_repo = repos["settings_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="FailClosedLib")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) >= 3
    img1, img2, img3 = images[0], images[1], images[2]

    session = usage_repo.create_scan_session(
        provider="Google Cloud Vision",
        total_images=3,
    )

    # Provider spy counting search invocations
    call_count = 0
    def search_spy(image_path, **kwargs):
        nonlocal call_count
        call_count += 1
        return ProviderResult(
            success=True,
            items=[
                SearchResultItem(
                    page_url="https://example.com/photo.jpg",
                    domain="example.com",
                    match_type="FULL",
                )
            ],
            units_consumed=1,
        )

    mock_provider = MagicMock()
    mock_provider.provider_id = "google_vision"
    mock_provider.search.side_effect = search_spy

    # Monkeypatch get_provider in scan_engine module to return our spy
    import backend.services.scan_engine as se_module
    monkeypatch.setattr(se_module, "get_provider", lambda **kwargs: mock_provider)

    # Monkeypatch record_call to simulate SQLite write failure during provider call accounting
    def failing_record_call(*args, **kwargs):
        raise sqlite3.DatabaseError("Simulated disk error during provider call accounting")

    monkeypatch.setattr(UsageRepository, "record_call", failing_record_call)

    settings = settings_repo.get_app_settings()

    # Run scan worker synchronously
    scan_engine._run_scan_worker(
        session_id=session.id,
        ordered_image_ids=[img1.id, img2.id, img3.id],
        provider_id="google_vision",
        credentials_path=None,
        free_tier_allowance=settings.free_tier_monthly_units,
        unit_price_usd=settings.unit_price_usd,
        db_path=scan_engine.db_path,
    )

    # Invariant 1: Provider was invoked for image 1, but NOT for image 2 or 3
    assert call_count == 1, f"Provider was called {call_count} times instead of stopping after 1!"

    # Invariant 2: Session marked FAILED with explanatory notes
    updated_session = usage_repo.get_scan_session(session.id)
    assert updated_session is not None
    assert updated_session.status == "FAILED"
    assert "Halted to prevent unmetered" in (updated_session.notes or "")

    # Invariant 3: Accounting failure item recorded as ERROR
    cur = usage_repo.conn.cursor()
    cur.execute("SELECT status, error_message FROM scan_items WHERE scan_session_id = ?", (session.id,))
    items = cur.fetchall()
    assert len(items) == 1
    assert items[0]["status"] == "ERROR"
    assert "Durable accounting persistence failed" in items[0]["error_message"]

    # Invariant 4: processed == successful + failed
    assert updated_session.processed_images == 1
    assert updated_session.failed_images == 1
    assert updated_session.successful_images == 0
    assert updated_session.processed_images == (updated_session.successful_images + updated_session.failed_images)


def test_duplicate_image_ids_deduplicated(client, repos, sample_images_dir: Path):
    """Verifies that duplicate image IDs in scan requests are deduplicated server-side,
    preventing duplicate provider calls and ensuring correct total_images and usable_count.
    """
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]
    scan_engine = repos["scan_engine"]

    lib = lib_repo.create(path=str(sample_images_dir), name="DedupLib")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) >= 2
    img1, img2 = images[0], images[1]

    # Pass duplicates: [img1.id, img1.id, img2.id, img1.id]
    duplicated_ids = [img1.id, img1.id, img2.id, img1.id]

    # 1. validate_scan_request should return exactly 2 usable images
    usable, missing = scan_engine.validate_scan_request(
        image_ids=duplicated_ids,
        provider_override="mock",
    )
    assert len(usable) == 2
    assert [img.id for img in usable] == [img1.id, img2.id]
    assert len(missing) == 0

    # 2. /api/scans/prepare endpoint should report usable_count = 2 and selected_count = 2
    prep_res = client.post("/api/scans/prepare", json={"image_ids": duplicated_ids})
    assert prep_res.status_code == 200
    prep_data = prep_res.json()
    assert prep_data["usable_count"] == 2
    assert prep_data["selected_count"] == 2

    # 3. /api/scans/start endpoint should create session with total_images = 2
    start_res = client.post("/api/scans/start", json={"image_ids": duplicated_ids})
    assert start_res.status_code == 200
    start_data = start_res.json()
    assert start_data["total_images"] == 2


def test_scan_worker_zombie_session_auto_recovery(repos, sample_images_dir: Path):
    """Verifies that a dead/crashed scan session marked RUNNING without an active worker
    thread is automatically detected and transitioned to FAILED, preventing zombie deadlocks.
    """
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]
    usage_repo = repos["usage_repo"]
    scan_engine = repos["scan_engine"]

    lib = lib_repo.create(path=str(sample_images_dir), name="ZombieRecoveryLib")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) >= 1

    # Simulate an abandoned / crashed scan session that was left RUNNING
    zombie = usage_repo.create_scan_session(
        provider="mock",
        total_images=5,
    )
    # Ensure no worker thread is alive for this session
    for t in threading.enumerate():
        if t.name == f"scan-worker-{zombie.id}" and t.is_alive():
            t.join(timeout=2.0)
    assert not any(t.name == f"scan-worker-{zombie.id}" and t.is_alive() for t in threading.enumerate())

    # Attempt to validate a new scan request: scan engine should detect zombie, mark it FAILED, and allow the request
    usable, missing = scan_engine.validate_scan_request(
        image_ids=[images[0].id],
        provider_override="mock",
    )
    assert len(usable) == 1

    # Invariant: the zombie session was recovered to FAILED
    recovered = usage_repo.get_scan_session(zombie.id)
    assert recovered is not None
    assert recovered.status == "FAILED"
    assert "Auto-recovered from crashed worker thread" in (recovered.notes or "")


def test_google_auth_offline_in_test_mode(repos, monkeypatch):
    """Verifies that test_google_auth returns mock_test_mode in PHOTO_PRIVATEER_TEST_MODE
    without making external OAuth2 token refresh network calls.
    """
    settings_repo = repos["settings_repo"]
    monkeypatch.setenv("PHOTO_PRIVATEER_TEST_MODE", "1")
    monkeypatch.setattr(settings_repo, "_check_adc", lambda: (True, "test-mock-project"))

    res = settings_repo.test_google_auth()
    assert res["valid"] is True
    assert res["auth_mode"] == "mock_test_mode"
    assert "Offline test mode active" in res["message"]


def test_library_purge_cleans_empty_scan_sessions_and_thumbnails(repos, temp_dir: Path):
    """Verifies that library purge deletes thumbnails on disk and cleans empty scan sessions."""
    from backend.config import get_thumbnails_dir

    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    usage_repo = repos["usage_repo"]

    # Create dummy image in a dedicated folder
    lib_folder = temp_dir / "purge_lib_test"
    lib_folder.mkdir()
    img_file = lib_folder / "photo.jpg"
    img = Image.new("RGB", (100, 100), color=(128, 64, 32))
    img.save(img_file, format="JPEG")

    lib = lib_repo.create(path=str(lib_folder), name="PurgeTestLib")
    repos["indexer"].index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) == 1
    image = images[0]

    # Generate a thumbnail file on disk for this image
    thumb_dir = get_thumbnails_dir()
    thumb_path = thumb_dir / f"{image.sha256}.webp"
    thumb_path.write_bytes(b"dummy_webp_data")
    assert thumb_path.exists()

    # Create a scan session and a scan item referencing this image
    session = usage_repo.create_scan_session(
        provider="mock",
        total_images=1,
    )
    usage_repo.record_scan_item(
        session_id=session.id,
        image_id=image.id,
        status="SUCCESS",
    )

    # Purge the library
    lib_repo.purge(lib.id)

    # Invariant 1: Image deleted
    assert img_repo.get_by_id(image.id) is None

    # Invariant 2: Thumbnail file unlinked from disk
    assert not thumb_path.exists()

    # Invariant 3: Empty scan session pruned
    assert usage_repo.get_scan_session(session.id) is None


def test_unarchive_rejects_overlapping_active_library(repos, sample_images_dir: Path):
    """Verifies that unarchiving a library fails if an active library with an overlapping root exists."""
    lib_repo = repos["lib_repo"]

    # Create active Library B pointing to sample_images_dir
    lib_b = lib_repo.create(path=str(sample_images_dir), name="LibB")
    assert lib_repo.get_by_id(lib_b.id).is_archived == 0

    # Insert an archived Library A pointing to a child subfolder directly into database
    subfolder = sample_images_dir / "subfolder"
    subfolder.mkdir(exist_ok=True)
    cur = lib_repo.conn.cursor()
    cur.execute(
        "INSERT INTO libraries (path, name, is_archived, enabled, created_at) VALUES (?, 'LibA', 1, 0, datetime('now'))",
        (str(subfolder),),
    )
    lib_a_id = cur.lastrowid
    lib_repo.conn.commit()

    # Attempting to unarchive Library A must raise ValueError due to overlapping directory with active Library B
    with pytest.raises(ValueError, match="overlaps with active library"):
        lib_repo.unarchive(lib_a_id)


def test_migration_007_preserves_legacy_manual_projects(temp_dir: Path):
    """Verifies that migration 007 migrates non-empty legacy project values to project_source = 'manual'."""
    from backend.migrations.runner import run_migrations, MIGRATIONS

    db_file = temp_dir / "migration_007_test.sqlite"

    # Run migrations up to 006
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = OFF;")
    conn.execute("CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);")

    for v, desc, fn in MIGRATIONS[:6]:
        fn(conn)
        conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, datetime('now'));", (v, desc))
    conn.commit()

    # Insert test library and image with a legacy project
    conn.execute(
        "INSERT INTO libraries (id, path, name, created_at) "
        "VALUES (1, 'C:/photos', 'TestLib', datetime('now'));"
    )
    conn.execute(
        "INSERT INTO images (id, library_id, file_path, filename, file_size, file_modified_at, sha256, indexed_at, last_seen_on_disk, project) "
        "VALUES (1, 1, 'C:/photos/portrait.jpg', 'portrait.jpg', 1024, 0.0, 'hash123', datetime('now'), datetime('now'), 'Summer Wedding');"
    )
    conn.commit()

    # Now run all migrations through runner
    run_migrations(conn)

    # Check that image 1 now has project_source = 'manual'
    cur = conn.cursor()
    cur.execute("SELECT project, project_source FROM images WHERE id = 1")
    row = cur.fetchone()
    assert row["project"] == "Summer Wedding"
    assert row["project_source"] == "manual"
    conn.close()


def test_unambiguous_sha_rename_with_multiple_missing_candidates(repos, temp_dir: Path):
    """Verifies that when two images share the same SHA256 and both go missing,
    a newly added file with that SHA256 is treated as a new image rather than arbitrarily binding history.
    """
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]

    folder = temp_dir / "sha_ambiguity_test"
    folder.mkdir()
    # Create file A
    f_a = folder / "a.jpg"
    img_data = Image.new("RGB", (50, 50), color=(10, 20, 30))
    img_data.save(f_a, format="JPEG")

    # Create file B with identical content
    f_b = folder / "b.jpg"
    shutil.copyfile(f_a, f_b)

    lib = lib_repo.create(path=str(folder), name="ShaAmbiguityLib")
    indexer.index_library(lib.id)

    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) == 2
    sha = images[0].sha256
    assert images[1].sha256 == sha

    # Delete both file A and file B
    f_a.unlink()
    f_b.unlink()

    # Index again to mark them missing on disk
    indexer.index_library(lib.id)
    missing, _ = img_repo.list_images(library_id=lib.id, filter_status="missing")
    assert len(missing) == 2

    # Now create file C with the same content
    f_c = folder / "c.jpg"
    img_data.save(f_c, format="JPEG")

    # Index again
    indexer.index_library(lib.id)

    # Invariant: Because len(missing_candidates) == 2 > 1, file C is created as a NEW image (total 3 records)
    all_images, _ = img_repo.list_images(library_id=lib.id)
    assert len(all_images) == 3


def test_csrf_origin_protection_blocks_cross_origin_mutations(client, repos, sample_images_dir: Path):
    """Verifies that enforce_local_origin_protection middleware rejects cross-origin and cross-site requests."""
    lib = repos["lib_repo"].create(path=str(sample_images_dir), name="CsrfTestLib")
    repos["indexer"].index_library(lib.id)
    images, _ = repos["img_repo"].list_images(library_id=lib.id)
    img_id = images[0].id

    # 1. POST from evil.com is blocked
    res1 = client.post("/api/scans/prepare", json={"image_ids": [img_id]}, headers={"Origin": "http://evil.com"})
    assert res1.status_code == 403
    assert "Forbidden origin" in res1.json()["detail"]

    # 2. POST with Sec-Fetch-Site: cross-site is blocked
    res2 = client.post("/api/scans/prepare", json={"image_ids": [img_id]}, headers={"Sec-Fetch-Site": "cross-site"})
    assert res2.status_code == 403
    assert "Cross-site requests to Photo Privateer API are forbidden" in res2.json()["detail"]

    # 3. POST with loopback origin is permitted
    res3 = client.post("/api/scans/prepare", json={"image_ids": [img_id]}, headers={"Origin": "http://127.0.0.1:8765"})
    assert res3.status_code == 200

    # 4. Safe read GET with cross-origin is permitted
    res4 = client.get("/api/photos", headers={"Origin": "http://evil.com"})
    assert res4.status_code == 200
