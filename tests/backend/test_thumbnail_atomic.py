"""Concurrent requests, failure cleanup and purge cannot expose partial WebP."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
from pathlib import Path
import threading
import time

import pytest
from PIL import Image

from backend.config import get_thumbnails_dir
from backend.services.thumbnail_cache import ThumbnailCache


def source_image(root, name="photo.png", color="red"):
    path = root / name
    Image.new("RGBA", (80, 120), color).save(path)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def decode(content):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        assert image.format == "WEBP"


def test_parallel_requests_across_cache_instances(temp_dir):
    source, sha = source_image(temp_dir)
    original = source.read_bytes()
    caches = [ThumbnailCache(temp_dir / "cache") for _ in range(8)]
    barrier = threading.Barrier(8)

    def request(cache):
        barrier.wait(timeout=5)
        return cache.read_thumbnail(sha, source)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, caches))
    for result in results:
        decode(result)
    assert len(set(results)) == 1
    assert not list(caches[0].cache_dir.glob("*.tmp"))
    assert source.read_bytes() == original


def test_parallel_different_hashes_have_complete_outputs(temp_dir):
    sources = [source_image(temp_dir, f"{i}.png", color) for i, color in enumerate(["red", "blue", "green"])]
    cache = ThumbnailCache(temp_dir / "cache")
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda pair: cache.read_thumbnail(pair[1], pair[0]), sources))
    for result in results:
        decode(result)
    assert len(list(cache.cache_dir.glob("*.webp"))) == 3


@pytest.mark.parametrize("stage", ["encode", "replace"])
def test_failed_writer_removes_temp_and_can_retry(temp_dir, monkeypatch, stage):
    source, sha = source_image(temp_dir)
    cache = ThumbnailCache(temp_dir / "cache")
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError(f"injected {stage} failure")
        if stage == "encode":
            patch.setattr(Image.Image, "save", fail)
        else:
            patch.setattr(os, "replace", fail)
        with pytest.raises(OSError, match="injected"):
            cache.get_or_create_thumbnail(source, sha)
    assert list(cache.cache_dir.iterdir()) == []
    decode(cache.read_thumbnail(sha, source))


def test_temp_publication_is_unique_and_only_completed_output_is_visible(temp_dir, monkeypatch):
    source, sha = source_image(temp_dir)
    cache = ThumbnailCache(temp_dir / "cache")
    paths = []
    original_replace = os.replace

    def inspect_publish(temp, final):
        paths.append(Path(temp))
        assert Path(temp).parent == cache.cache_dir
        assert Path(temp) != cache.cache_dir / f"{sha}.tmp.webp"
        assert not Path(final).exists()
        decode(Path(temp).read_bytes())
        return original_replace(temp, final)

    monkeypatch.setattr(os, "replace", inspect_publish)
    cache.get_or_create_thumbnail(source, sha)
    cache.remove_thumbnail(sha)
    cache.get_or_create_thumbnail(source, sha)
    assert len(set(paths)) == 2
    assert all(not path.exists() for path in paths)


def test_bounded_abandoned_cleanup_preserves_recent_and_foreign_files(temp_dir):
    cache = ThumbnailCache(temp_dir / "cache")
    sha = "a" * 64
    old = cache.cache_dir / f".pp-thumb-{sha}-old.tmp"
    recent = cache.cache_dir / f".pp-thumb-{sha}-recent.tmp"
    foreign = cache.cache_dir / "someone-elses.tmp"
    for path in [old, recent, foreign]:
        path.write_bytes(b"temporary")
    for path in [old, foreign]:
        os.utime(path, (time.time() - 90000, time.time() - 90000))
    assert cache.cleanup_abandoned() == 1
    assert not old.exists() and recent.exists() and foreign.exists()
    for i in range(30):
        path = cache.cache_dir / f".pp-thumb-{sha}-{i}.tmp"
        path.write_bytes(b"abandoned")
        os.utime(path, (time.time() - 90000, time.time() - 90000))
    assert cache.cleanup_abandoned() == 16


def test_thumbnail_response_survives_purge_after_snapshot(client, repos, temp_dir, monkeypatch):
    folder = temp_dir / "library"
    folder.mkdir()
    source, sha = source_image(folder)
    original = source.read_bytes()
    library = repos["lib_repo"].create(str(folder))
    repos["indexer"].index_library(library.id)
    photos, _ = repos["img_repo"].list_images(library_id=library.id)
    cache = ThumbnailCache(get_thumbnails_dir())
    repos["thumb_cache"] = cache
    cache.get_or_create_thumbnail(source, sha)
    original_read = cache.read_thumbnail

    def purge_after_read(*args, **kwargs):
        content = original_read(*args, **kwargs)
        assert repos["lib_repo"].purge(library.id)
        return content

    monkeypatch.setattr(cache, "read_thumbnail", purge_after_read)
    response = client.get(f"/api/photos/{photos[0].id}/thumbnail")
    assert response.status_code == 200
    decode(response.content)
    assert source.read_bytes() == original
    assert not cache.has_thumbnail(sha)


def test_cache_keys_cannot_escape_directory(temp_dir):
    cache = ThumbnailCache(temp_dir / "cache")
    for invalid in ["../source", "a/b", "abc", "A" * 64]:
        with pytest.raises(ValueError):
            cache.get_thumbnail_path(invalid)


def test_purge_waits_until_generation_snapshot_is_complete(temp_dir, monkeypatch):
    source, sha = source_image(temp_dir)
    cache = ThumbnailCache(temp_dir / "cache")
    encoding = threading.Event()
    finish_encoding = threading.Event()
    purge_attempted = threading.Event()
    original_save = Image.Image.save

    def paused_save(image, *args, **kwargs):
        encoding.set()
        assert finish_encoding.wait(timeout=5)
        return original_save(image, *args, **kwargs)

    def purge():
        purge_attempted.set()
        cache.remove_thumbnail(sha)

    monkeypatch.setattr(Image.Image, "save", paused_save)
    with ThreadPoolExecutor(max_workers=2) as pool:
        generation = pool.submit(cache.read_thumbnail, sha, source)
        assert encoding.wait(timeout=5)
        eviction = pool.submit(purge)
        assert purge_attempted.wait(timeout=5)
        finish_encoding.set()
        content = generation.result(timeout=5)
        eviction.result(timeout=5)
    decode(content)
    assert not cache.has_thumbnail(sha)


def test_orientation_and_transparency_remain_supported(temp_dir):
    cache = ThumbnailCache(temp_dir / "cache")
    source, sha = source_image(temp_dir, color=(255, 0, 0, 0))
    with Image.open(io.BytesIO(cache.read_thumbnail(sha, source))) as thumbnail:
        assert thumbnail.mode == "RGBA"
        assert thumbnail.getpixel((0, 0))[3] == 0
    oriented = temp_dir / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (120, 80), "blue").save(oriented, exif=exif)
    oriented_sha = hashlib.sha256(oriented.read_bytes()).hexdigest()
    with Image.open(io.BytesIO(cache.read_thumbnail(oriented_sha, oriented))) as thumbnail:
        assert thumbnail.size == (80, 120)
