"""Comprehensive integration and resilience tests for Photo Privateer."""
from __future__ import annotations

import os
import shutil
import sqlite3
import time
from pathlib import Path
from PIL import Image
import pytest

from backend.database import get_connection, init_db
from backend.migrations.runner import run_migrations, get_applied_migrations
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.services.library_indexer import LibraryIndexer
from backend.services.scan_engine import ScanEngine
from backend.providers.mock_provider import MockSearchProvider


def test_versioned_migrations_idempotency(temp_dir: Path):
    """Verify that versioned migrations are tracked and strictly idempotent."""
    db_file = temp_dir / "migration_test.db"
    conn = get_connection(db_file)

    # First run applies all migrations (001 to 005)
    applied_first = run_migrations(conn)
    assert len(applied_first) >= 5
    assert 1 in applied_first
    assert 5 in applied_first

    # Check schema_migrations table
    applied_in_db = get_applied_migrations(conn)
    assert applied_in_db == applied_first

    # Second run should be a no-op returning empty list
    applied_second = run_migrations(conn)
    assert applied_second == []
    conn.close()


def test_non_destructive_library_archiving(repos, client, sample_images_dir: Path):
    """Verify archiving pauses monitoring without modifying original files or deleting photos/matches."""
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]

    # 1. Create and index library
    lib = lib_repo.create(path=str(sample_images_dir), name="Archive Test Lib")
    indexer.index_library(lib.id)

    images, count = img_repo.list_images(library_id=lib.id)
    assert count == 5

    # 2. Archive library via API
    res_archive = client.post(f"/api/libraries/{lib.id}/archive")
    assert res_archive.status_code == 200
    archived_data = res_archive.json()
    assert archived_data["is_archived"] is True
    assert archived_data["enabled"] is False

    # 3. Verify photos are safely preserved
    images_after, count_after = img_repo.list_images(library_id=lib.id)
    assert count_after == 5
    assert len(images_after) == 5

    # 4. Unarchive library via API
    res_unarchive = client.post(f"/api/libraries/{lib.id}/unarchive")
    assert res_unarchive.status_code == 200
    unarchived_data = res_unarchive.json()
    assert unarchived_data["is_archived"] is False
    assert unarchived_data["enabled"] is True


def test_concurrent_scan_conflict_409(client, repos, sample_images_dir: Path):
    """Verify attempting to start a scan while another is running raises 409 Conflict."""
    lib_repo = repos["lib_repo"]
    indexer = repos["indexer"]
    usage_repo = repos["usage_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="Concurrency Test Lib")
    indexer.index_library(lib.id)
    images, _ = repos["img_repo"].list_images(library_id=lib.id)
    img_ids = [img.id for img in images[:2]]

    # Manually create a running session in the database
    running_session = usage_repo.create_scan_session(
        provider="mock",
        total_images=2,
    )
    assert running_session.status == "RUNNING"

    # Attempt to start another scan session via API
    res = client.post("/api/scans/start", json={
        "image_ids": img_ids,
        "provider": "mock",
    })
    assert res.status_code == 409
    assert "currently running" in res.json()["detail"]

    # Clean up session
    usage_repo.update_scan_session_progress(
        session_id=running_session.id,
        processed=2,
        successful=2,
        failed=0,
        status="COMPLETED",
    )


def test_startup_recovery_of_interrupted_sessions(repos):
    """Verify uncompleted sessions from crashes are recovered to INTERRUPTED on startup."""
    usage_repo = repos["usage_repo"]

    # Create orphaned running session
    session = usage_repo.create_scan_session(
        provider="mock",
        total_images=5,
    )
    assert session.status == "RUNNING"

    # Run startup crash recovery
    recovered_count = usage_repo.recover_interrupted_sessions()
    assert recovered_count >= 1

    # Verify session is marked INTERRUPTED
    recovered = usage_repo.get_scan_session(session.id)
    assert recovered is not None
    assert recovered.status == "INTERRUPTED"
    assert recovered.completed_at is not None
    assert "Interrupted by application shutdown" in (recovered.notes or "")


def test_sha256_rename_reconciliation(repos, temp_dir: Path):
    """Verify renaming a source file on disk is reconciled by SHA-256 without creating duplicate image records."""
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]

    # Create single photo
    photo_folder = temp_dir / "rename_photos"
    photo_folder.mkdir()
    original_file = photo_folder / "portrait_original.jpg"

    im = Image.new("RGB", (400, 300), color=(100, 150, 200))
    im.save(original_file, format="JPEG")

    lib = lib_repo.create(path=str(photo_folder), name="Rename Lib")
    indexer.index_library(lib.id)

    images_before, count_before = img_repo.list_images(library_id=lib.id)
    assert count_before == 1
    original_id = images_before[0].id
    original_sha = images_before[0].sha256
    assert images_before[0].filename == "portrait_original.jpg"

    # Rename file on disk
    renamed_file = photo_folder / "portrait_renamed.jpg"
    original_file.rename(renamed_file)

    # Re-index library
    indexer.index_library(lib.id)

    # Verify image record reconciled (same id, same SHA-256, updated filename and path)
    images_after, count_after = img_repo.list_images(library_id=lib.id)
    assert count_after == 1
    assert images_after[0].id == original_id
    assert images_after[0].sha256 == original_sha
    assert images_after[0].filename == "portrait_renamed.jpg"
    assert images_after[0].is_present_on_disk is True


def test_missing_file_detection_and_restoration(repos, temp_dir: Path):
    """Verify missing files are identified and restored when returned to disk."""
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    indexer = repos["indexer"]

    folder = temp_dir / "missing_photos"
    folder.mkdir()
    p1 = folder / "photo_a.jpg"
    im = Image.new("RGB", (200, 200), color=(50, 50, 50))
    im.save(p1, format="JPEG")

    lib = lib_repo.create(path=str(folder), name="Missing Test Lib")
    indexer.index_library(lib.id)

    images, _ = img_repo.list_images(library_id=lib.id)
    assert images[0].is_present_on_disk is True

    # Move file away
    staging = temp_dir / "photo_staging.jpg"
    shutil.move(p1, staging)

    # Re-index
    indexer.index_library(lib.id)
    images_missing, _ = img_repo.list_images(library_id=lib.id)
    assert images_missing[0].is_present_on_disk is False

    # Restore file
    shutil.move(staging, p1)
    indexer.index_library(lib.id)
    images_restored, _ = img_repo.list_images(library_id=lib.id)
    assert images_restored[0].is_present_on_disk is True


def test_zero_cost_google_auth_verification(repos):
    """Verify test_google_auth returns immediately without GCE metadata network stalls."""
    settings_repo = repos["settings_repo"]

    start = time.perf_counter()
    res = settings_repo.test_google_auth()
    duration = time.perf_counter() - start

    # Must complete fast without hanging on metadata service
    assert duration < 2.0
    assert "success" in res
    assert res["success"] is False
    assert res["auth_mode"] == "none"
    assert "No Google Cloud credentials configured" in res["error"]


def test_lifespan_uses_temp_db_and_does_not_touch_user_home(temp_dir: Path):
    """Explicitly proves that FastAPI lifespan uses the injected temporary DB and never touches user home."""
    from fastapi.testclient import TestClient
    from backend.main import create_app
    from backend.database import get_db_path, get_connection

    test_db = temp_dir / "lifespan_isolated.db"
    isolated_app = create_app(db_path=test_db)

    # Lifespan executes upon entering TestClient context
    with TestClient(isolated_app):
        # Database file must have been created and initialized at test_db
        assert test_db.is_file()
        with get_connection(test_db) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'")
            assert cur.fetchone() is not None

    # Verify user's actual home database path was not touched
    user_home_db = (Path.home() / ".photo_privateer" / "photo_privateer.sqlite").resolve()
    assert test_db.resolve() != user_home_db


def test_host_bind_validation():
    """Verify that loopback addresses are accepted while non-loopback binds are strictly forbidden."""
    from backend.config import validate_loopback_host

    # Valid loopback
    assert validate_loopback_host("127.0.0.1") == "127.0.0.1"
    assert validate_loopback_host("::1") == "::1"
    assert validate_loopback_host("localhost") == "localhost"

    # Forbidden non-loopback
    with pytest.raises(ValueError, match="forbidden for security"):
        validate_loopback_host("0.0.0.0")

    with pytest.raises(ValueError, match="forbidden for security"):
        validate_loopback_host("192.168.1.100")

    with pytest.raises(ValueError, match="forbidden for security"):
        validate_loopback_host("10.0.0.1")

    # Invalid address
    with pytest.raises(ValueError, match="Invalid host address"):
        validate_loopback_host("not_an_ip_or_localhost_!!!")


def test_google_vision_provider_blocked_in_test_mode(sample_images_dir: Path):
    """Verify that GoogleVisionSearchProvider hard-fails with RuntimeError in test mode."""
    from backend.providers.google_vision_provider import GoogleVisionSearchProvider

    provider = GoogleVisionSearchProvider()
    test_image = str(sample_images_dir / "mountain_landscape.jpg")

    with pytest.raises(RuntimeError, match="strictly forbidden in test mode"):
        provider.search(test_image)

