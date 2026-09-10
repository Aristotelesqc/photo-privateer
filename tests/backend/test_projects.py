"""Tests for Photo Project classification and subfolder auto-detection."""
import sqlite3
import pytest
from pathlib import Path
from PIL import Image

from backend.database import get_db
from backend.migrations.runner import run_migrations, get_applied_migrations
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.library_indexer import LibraryIndexer
from backend.main import app
from fastapi.testclient import TestClient

@pytest.fixture
def project_test_env(tmp_path):
    db_path = tmp_path / "test_projects.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    run_migrations(conn)

    thumb_dir = tmp_path / "thumbnails"
    thumb_dir.mkdir()
    thumb_cache = ThumbnailCache(thumb_dir)

    lib_repo = LibraryRepository(conn)
    img_repo = ImageRepository(conn)
    indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

    # Create dummy folder hierarchy
    root_photos = tmp_path / "photos"
    root_photos.mkdir()
    
    # Root photo (no project)
    img0 = Image.new("RGB", (100, 100), color="white")
    img0.save(root_photos / "root_photo.jpg")

    # Project A photos
    proj_a = root_photos / "Wedding_Smith"
    proj_a.mkdir()
    img1 = Image.new("RGB", (100, 100), color="red")
    img1.save(proj_a / "ceremony_01.jpg")
    img2 = Image.new("RGB", (100, 100), color="blue")
    img2.save(proj_a / "reception_02.jpg")

    # Project B photos
    proj_b = root_photos / "Commercial_Tesla"
    proj_b.mkdir()
    img3 = Image.new("RGB", (100, 100), color="green")
    img3.save(proj_b / "model_s.jpg")

    yield {
        "conn": conn,
        "lib_repo": lib_repo,
        "img_repo": img_repo,
        "indexer": indexer,
        "root_photos": root_photos,
    }
    conn.close()

def test_migration_006_applied(project_test_env):
    conn = project_test_env["conn"]
    applied = get_applied_migrations(conn)
    assert 6 in applied

    cur = conn.cursor()
    cur.execute("PRAGMA table_info(images)")
    img_cols = {r[1] for r in cur.fetchall()}
    assert "project" in img_cols

    cur.execute("PRAGMA table_info(libraries)")
    lib_cols = {r[1] for r in cur.fetchall()}
    assert "subfolders_as_projects" in lib_cols

def test_indexing_auto_detects_subfolder_projects(project_test_env):
    lib_repo = project_test_env["lib_repo"]
    img_repo = project_test_env["img_repo"]
    indexer = project_test_env["indexer"]
    root = project_test_env["root_photos"]

    lib = lib_repo.create(str(root), name="Client Work", recursive=True, subfolders_as_projects=True)
    assert lib.subfolders_as_projects is True

    res = indexer.index_library(lib.id)
    assert res["added_or_updated"] == 4

    images, _ = img_repo.list_images(library_id=lib.id, sort_by="filename", sort_dir="asc")
    by_fn = {img.filename: img for img in images}

    # Root photo has no subfolder -> project is None
    assert by_fn["root_photo.jpg"].project is None

    # Subfolder photos have their immediate parent subfolder as project
    assert by_fn["ceremony_01.jpg"].project == "Wedding_Smith"
    assert by_fn["reception_02.jpg"].project == "Wedding_Smith"
    assert by_fn["model_s.jpg"].project == "Commercial_Tesla"

def test_project_filtering_and_distinct_list(project_test_env):
    lib_repo = project_test_env["lib_repo"]
    img_repo = project_test_env["img_repo"]
    indexer = project_test_env["indexer"]
    root = project_test_env["root_photos"]

    lib = lib_repo.create(str(root), recursive=True, subfolders_as_projects=True)
    indexer.index_library(lib.id)

    # Distinct projects
    projs = img_repo.get_distinct_projects()
    assert projs == ["Commercial_Tesla", "Wedding_Smith"]

    # Filter by specific project
    smith_imgs, total_smith = img_repo.list_images(project="Wedding_Smith")
    assert total_smith == 2
    assert all(img.project == "Wedding_Smith" for img in smith_imgs)

    # Filter by unassigned
    unassigned, total_unassigned = img_repo.list_images(project="__unassigned__")
    assert total_unassigned == 1
    assert unassigned[0].filename == "root_photo.jpg"

def test_batch_update_project(project_test_env):
    lib_repo = project_test_env["lib_repo"]
    img_repo = project_test_env["img_repo"]
    indexer = project_test_env["indexer"]
    root = project_test_env["root_photos"]

    lib = lib_repo.create(str(root), recursive=True, subfolders_as_projects=False)
    indexer.index_library(lib.id)

    images, total = img_repo.list_images(library_id=lib.id)
    assert total == 4
    # All are None because subfolders_as_projects=False
    assert all(img.project is None for img in images)

    # Batch assign all to "Custom Campaign"
    ids = [img.id for img in images]
    updated = img_repo.batch_update_project(ids, "Custom Campaign")
    assert updated == 4

    updated_imgs, _ = img_repo.list_images(project="Custom Campaign")
    assert len(updated_imgs) == 4

    # Clear project for first two
    img_repo.batch_update_project(ids[:2], None)
    cleared_imgs, _ = img_repo.list_images(project="__unassigned__")
    assert len(cleared_imgs) == 2

def test_retroactive_detect_projects_endpoint(project_test_env):
    lib_repo = project_test_env["lib_repo"]
    img_repo = project_test_env["img_repo"]
    indexer = project_test_env["indexer"]
    root = project_test_env["root_photos"]

    # Index initially without subfolders_as_projects
    lib = lib_repo.create(str(root), recursive=True, subfolders_as_projects=False)
    indexer.index_library(lib.id)

    images, _ = img_repo.list_images(library_id=lib.id)
    assert all(img.project is None for img in images)

    # Now retroactively detect projects
    updated = indexer.detect_and_apply_subfolder_projects(lib.id)
    assert updated == 4

    images_after, _ = img_repo.list_images(library_id=lib.id)
    by_fn = {img.filename: img for img in images_after}
    assert by_fn["root_photo.jpg"].project is None
    assert by_fn["ceremony_01.jpg"].project == "Wedding_Smith"
    assert by_fn["model_s.jpg"].project == "Commercial_Tesla"
