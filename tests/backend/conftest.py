"""Shared test fixtures for backend tests."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
import pytest
from PIL import Image
from fastapi.testclient import TestClient

# Force an isolated temporary directory for the entire pytest session BEFORE any backend import
SESSION_TEMP_DATA_DIR = Path(tempfile.mkdtemp(prefix="photo_privateer_pytest_data_")).resolve()
os.environ["PHOTO_PRIVATEER_DATA_DIR"] = str(SESSION_TEMP_DATA_DIR)
os.environ["PHOTO_PRIVATEER_TEST_MODE"] = "1"

from backend.database import init_db, get_connection, set_db_path, get_db_path
set_db_path(SESSION_TEMP_DATA_DIR / "session_test.db")

from backend.services.thumbnail_cache import ThumbnailCache
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.services.library_indexer import LibraryIndexer
from backend.services.domain_rules_engine import DomainRulesEngine
from backend.services.usage_tracker import UsageTracker
from backend.services.scan_engine import ScanEngine
from backend.main import app
from backend.api import deps

@pytest.fixture(scope="session", autouse=True)
def cleanup_session_temp():
    yield
    shutil.rmtree(SESSION_TEMP_DATA_DIR, ignore_errors=True)

@pytest.fixture(autouse=True)
def assert_no_real_db_touch():
    """Safety guard: asserts that under no circumstances does any backend test resolve or touch ~/.photo_privateer."""
    real_db = (Path.home() / ".photo_privateer" / "photo_privateer.sqlite").resolve()
    active_db = get_db_path().resolve()
    assert active_db != real_db, f"CRITICAL SECURITY BREACH: Test is about to access real user DB: {real_db}"
    yield
    assert get_db_path().resolve() != real_db, f"CRITICAL SECURITY BREACH: Test accessed real user DB during run: {real_db}"

@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    d = Path(tempfile.mkdtemp(prefix="photo_privateer_test_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)

@pytest.fixture
def db_path(temp_dir: Path) -> Generator[Path, None, None]:
    p = temp_dir / "test.db"
    set_db_path(p)
    app.state.db_path = p
    init_db(p)
    try:
        yield p
    finally:
        set_db_path(None)
        if hasattr(app.state, "db_path"):
            delattr(app.state, "db_path")

@pytest.fixture
def db_conn(db_path: Path):
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()

@pytest.fixture
def sample_images_dir(temp_dir: Path) -> Path:
    img_dir = temp_dir / "sample_photos"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 1. Standard photo
    im1 = Image.new("RGB", (800, 600), color=(180, 50, 50))
    im1.save(img_dir / "mountain_landscape.jpg", format="JPEG")

    # 2. PNG photo
    im2 = Image.new("RGBA", (1024, 768), color=(50, 180, 50, 255))
    im2.save(img_dir / "forest_canopy.png", format="PNG")

    # 3. Clean photo (mock returns 0 results)
    im3 = Image.new("RGB", (640, 480), color=(50, 50, 180))
    im3.save(img_dir / "clean_portrait.jpg", format="JPEG")

    # 4. Error photo (mock returns simulated error)
    im4 = Image.new("RGB", (640, 480), color=(200, 200, 50))
    im4.save(img_dir / "error_test_photo.jpg", format="JPEG")

    # 5. Multi photo (mock returns multiple results on 1 domain)
    im5 = Image.new("RGB", (640, 480), color=(200, 50, 200))
    im5.save(img_dir / "multi_domain_photo.jpg", format="JPEG")

    return img_dir

@pytest.fixture
def repos(db_conn, temp_dir: Path):
    thumb_cache = ThumbnailCache(cache_dir=temp_dir / "thumbs")
    lib_repo = LibraryRepository(db_conn)
    img_repo = ImageRepository(db_conn)
    rule_repo = DomainRuleRepository(db_conn)
    match_repo = MatchRepository(db_conn)
    usage_repo = UsageRepository(db_conn)
    settings_repo = SettingsRepository(db_conn)
    indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)
    rules_engine = DomainRulesEngine(rule_repo)
    tracker = UsageTracker(usage_repo, settings_repo)
    scan_engine = ScanEngine(img_repo, match_repo, rule_repo, usage_repo, settings_repo, lib_repo)


    return {
        "lib_repo": lib_repo,
        "img_repo": img_repo,
        "rule_repo": rule_repo,
        "match_repo": match_repo,
        "usage_repo": usage_repo,
        "settings_repo": settings_repo,
        "indexer": indexer,
        "rules_engine": rules_engine,
        "tracker": tracker,
        "scan_engine": scan_engine,
        "thumb_cache": thumb_cache,
    }

@pytest.fixture
def client(db_conn, repos) -> Generator[TestClient, None, None]:
    # Override FastAPI dependencies
    def override_get_db_conn():
        yield db_conn

    def override_get_library_repo():
        return repos["lib_repo"]

    def override_get_image_repo():
        return repos["img_repo"]

    def override_get_domain_rule_repo():
        return repos["rule_repo"]

    def override_get_match_repo():
        return repos["match_repo"]

    def override_get_usage_repo():
        return repos["usage_repo"]

    def override_get_settings_repo():
        return repos["settings_repo"]

    def override_get_thumbnail_cache():
        return repos["thumb_cache"]

    def override_get_library_indexer():
        return repos["indexer"]

    def override_get_usage_tracker():
        return repos["tracker"]

    def override_get_scan_engine():
        return repos["scan_engine"]

    app.dependency_overrides[deps.get_db_conn] = override_get_db_conn
    app.dependency_overrides[deps.get_library_repo] = override_get_library_repo
    app.dependency_overrides[deps.get_image_repo] = override_get_image_repo
    app.dependency_overrides[deps.get_domain_rule_repo] = override_get_domain_rule_repo
    app.dependency_overrides[deps.get_match_repo] = override_get_match_repo
    app.dependency_overrides[deps.get_usage_repo] = override_get_usage_repo
    app.dependency_overrides[deps.get_settings_repo] = override_get_settings_repo
    app.dependency_overrides[deps.get_thumbnail_cache] = override_get_thumbnail_cache
    app.dependency_overrides[deps.get_library_indexer] = override_get_library_indexer
    app.dependency_overrides[deps.get_usage_tracker] = override_get_usage_tracker
    app.dependency_overrides[deps.get_scan_engine] = override_get_scan_engine

    with TestClient(app) as tc:
        yield tc

    app.dependency_overrides.clear()
