"""Reference-aware cache eviction, independent of library availability."""
from pathlib import Path
import shutil
import sqlite3

import pytest
from PIL import Image

from backend.config import get_thumbnails_dir
from backend.database import get_connection
from backend.services.thumbnail_cache import ThumbnailCache


def indexed_library(repos, root, name):
    folder = root / name
    folder.mkdir()
    Image.new("RGB", (40, 40), "red").save(folder / "photo.png")
    library = repos["lib_repo"].create(str(folder))
    repos["indexer"].index_library(library.id)
    photos, _ = repos["img_repo"].list_images(library_id=library.id)
    return library, photos[0], folder


@pytest.mark.parametrize("remaining_state", ["active", "offline", "archived", "disabled"])
@pytest.mark.parametrize("purge_second", [False, True])
def test_shared_thumbnail_survives_until_last_reference(repos, temp_dir, remaining_state, purge_second):
    a, photo, a_folder = indexed_library(repos, temp_dir, "a")
    b, other, b_folder = indexed_library(repos, temp_dir, "b")
    assert photo.sha256 == other.sha256
    purged, survivor, surviving_folder = (b, a, a_folder) if purge_second else (a, b, b_folder)
    cache = ThumbnailCache(get_thumbnails_dir())
    thumb = cache.get_or_create_thumbnail(photo.file_path, photo.sha256)
    original_bytes = (a_folder / "photo.png").read_bytes()
    if remaining_state == "offline":
        # Fixture changes, never production source writes.
        surviving_folder.rename(temp_dir / "offline_source")
        repos["img_repo"].conn.execute("UPDATE images SET is_present_on_disk = 0 WHERE library_id = ?", (survivor.id,))
        repos["img_repo"].conn.commit()
    elif remaining_state == "archived":
        repos["lib_repo"].archive(survivor.id)
    elif remaining_state == "disabled":
        repos["lib_repo"].update(survivor.id, enabled=False)
    assert repos["lib_repo"].purge(purged.id)
    with Image.open(thumb) as image:
        image.load()
    assert repos["lib_repo"].purge(survivor.id)
    assert not thumb.exists()
    for source in temp_dir.rglob("photo.png"):
        assert source.read_bytes() == original_bytes


def test_rolled_back_purge_leaves_cache(repos, temp_dir, monkeypatch):
    library, photo, _ = indexed_library(repos, temp_dir, "rollback")
    thumb = ThumbnailCache(get_thumbnails_dir()).get_or_create_thumbnail(photo.file_path, photo.sha256)

    def fail_repair(self):
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr("backend.repositories.group_repo.PhotoGroupRepository.repair_groups", fail_repair)
    with pytest.raises(RuntimeError):
        repos["lib_repo"].purge(library.id)
    assert repos["lib_repo"].get_by_id(library.id)
    assert repos["img_repo"].get_by_id(photo.id)
    assert thumb.is_file()


def test_cache_failure_does_not_misreport_committed_purge(repos, temp_dir, monkeypatch, caplog):
    library, photo, _ = indexed_library(repos, temp_dir, "failure")
    thumb = ThumbnailCache(get_thumbnails_dir()).get_or_create_thumbnail(photo.file_path, photo.sha256)
    original_unlink = Path.unlink

    def fail_thumbnail(path, *args, **kwargs):
        if path == thumb:
            raise PermissionError("injected cache failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_thumbnail)
    assert repos["lib_repo"].purge(library.id)
    assert repos["lib_repo"].get_by_id(library.id) is None
    assert repos["img_repo"].get_by_id(photo.id) is None
    assert thumb.exists()
    assert "could not be removed" in caplog.text


def test_cleanup_reserves_writer_slot_and_deduplicates_hashes(repos, temp_dir, db_path, monkeypatch):
    library, photo, folder = indexed_library(repos, temp_dir, "race")
    shutil.copyfile(folder / "photo.png", folder / "duplicate.png")
    repos["indexer"].index_library(library.id)
    thumb = ThumbnailCache(get_thumbnails_dir()).get_or_create_thumbnail(photo.file_path, photo.sha256)
    original_unlink = Path.unlink
    attempts = []
    with get_connection(db_path) as writer:
        writer.execute("PRAGMA busy_timeout = 0")

        def competing_write(path, *args, **kwargs):
            if path == thumb:
                attempts.append(True)
                # At the check/unlink boundary every other DB writer must wait.
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    writer.execute("UPDATE libraries SET name = name")
                writer.rollback()
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", competing_write)
        assert repos["lib_repo"].purge(library.id)
    assert len(attempts) == 1
