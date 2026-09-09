"""Tests for library folder indexing and non-destructive photo analysis."""
from __future__ import annotations

import hashlib
from pathlib import Path
from PIL import Image

def test_indexing_discovers_photos_and_never_modifies_source(repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]

    # Compute source file hashes before indexing
    pre_hashes = {}
    for p in sample_images_dir.glob("*"):
        if p.is_file():
            with open(p, "rb") as f:
                pre_hashes[p.name] = hashlib.sha256(f.read()).hexdigest()

    # Create library
    lib = lib_repo.create(path=str(sample_images_dir), name="Test Library")
    assert lib.id is not None
    assert lib.image_count == 0

    # Run indexing
    result = indexer.index_library(lib.id)
    assert result["scanned"] == 5
    assert result["added_or_updated"] == 5
    assert result["unchanged"] == 0

    # Verify source file hashes after indexing are 100% IDENTICAL
    for p in sample_images_dir.glob("*"):
        if p.is_file():
            with open(p, "rb") as f:
                post_hash = hashlib.sha256(f.read()).hexdigest()
            assert post_hash == pre_hashes[p.name], f"Source file {p.name} was altered!"

    # Verify indexed metadata
    images, total = img_repo.list_images(library_id=lib.id)
    assert total == 5
    for img in images:
        assert img.sha256 == pre_hashes[img.filename]
        assert img.width is not None and img.width > 0
        assert img.height is not None and img.height > 0
        assert img.scan_count == 0

    # Second index run should detect unchanged files without re-indexing
    result2 = indexer.index_library(lib.id)
    assert result2["scanned"] == 5
    assert result2["added_or_updated"] == 0
    assert result2["unchanged"] == 5

def test_recursive_vs_non_recursive(repos, temp_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]

    # Setup nested folders
    parent = temp_dir / "parent_photos"
    child = parent / "sub_album"
    parent.mkdir()
    child.mkdir()

    im1 = Image.new("RGB", (100, 100), color=(10, 10, 10))
    im1.save(parent / "root_photo.jpg")
    im2 = Image.new("RGB", (100, 100), color=(20, 20, 20))
    im2.save(child / "nested_photo.jpg")

    # 1. Non-recursive library
    lib_non_rec = lib_repo.create(path=str(parent), name="Non Recursive", recursive=False)
    indexer.index_library(lib_non_rec.id)
    images_non_rec, total_non_rec = img_repo.list_images(library_id=lib_non_rec.id)
    assert total_non_rec == 1
    assert images_non_rec[0].filename == "root_photo.jpg"

    # 2. Update to recursive
    lib_repo.update(lib_non_rec.id, recursive=True)
    indexer.index_library(lib_non_rec.id)
    images_rec, total_rec = img_repo.list_images(library_id=lib_non_rec.id)
    assert total_rec == 2
