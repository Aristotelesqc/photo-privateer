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


def test_replaced_file_creates_new_identity_and_does_not_inherit_matches(repos, temp_dir: Path):
    """Verify that replacing a file at path X with different image content (different SHA-256):
    1. Creates a brand new image identity (new image_id).
    2. Preserves the old historical record marked is_present_on_disk = 0.
    3. Never migrates historical matches, classifications, or notes to the new image.
    """
    import pytest
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    match_repo = repos["match_repo"]

    folder = temp_dir / "replace_identity_test"
    folder.mkdir()
    target_path = folder / "photo.jpg"

    # 1. Save original Image A and index it
    im_a = Image.new("RGB", (300, 300), color=(100, 20, 20))
    im_a.save(target_path, format="JPEG")

    lib = lib_repo.create(path=str(folder), name="Identity Test Lib")
    indexer.index_library(lib.id)

    images_step1, count_step1 = img_repo.list_images(library_id=lib.id)
    assert count_step1 == 1
    image_a = images_step1[0]
    id_a = image_a.id
    sha_a = image_a.sha256

    # 2. Associate a match with note and classification on Image A
    match_a, is_new = match_repo.upsert_match(
        image_id=id_a,
        scan_session_id=None,
        domain="unauthorized-blog.com",
        match_type="FULL",
        provider="mock",
        page_url="https://unauthorized-blog.com/post-1",
        default_classification="UNAUTHORIZED",
    )
    match_repo.update_classification_and_notes(match_a.id, notes="Infringement documented")

    # 3. Replace the file at target_path with completely different Image B (different SHA-256)
    im_b = Image.new("RGB", (300, 300), color=(20, 150, 20))
    im_b.save(target_path, format="JPEG")

    # 4. Re-index library
    indexer.index_library(lib.id)

    # 5. Verify the new file got its own new identity
    img_b = img_repo.get_by_path(str(target_path))
    assert img_b is not None
    assert img_b.id != id_a, "New file must have a different image_id!"
    assert img_b.sha256 != sha_a, "New file must have its own SHA-256!"
    assert img_b.is_present_on_disk is True

    # 6. Verify Image B inherited NO matches
    matches_b, count_b = match_repo.list_matches(image_id=img_b.id)
    assert count_b == 0
    assert len(matches_b) == 0

    # 7. Verify Image A's historical record and matches are safely preserved
    old_record = img_repo.get_by_id(id_a)
    assert old_record is not None
    assert old_record.sha256 == sha_a
    assert old_record.is_present_on_disk is False
    assert "#archived-" in old_record.file_path

    matches_a, count_a = match_repo.list_matches(image_id=id_a)
    assert count_a == 1
    assert matches_a[0].domain == "unauthorized-blog.com"
    assert matches_a[0].classification == "UNAUTHORIZED"
    assert matches_a[0].notes == "Infringement documented"


def test_forbid_overlapping_library_roots(repos, temp_dir: Path):
    """Verify that creating overlapping library roots (child of existing, or parent of existing) is rejected."""
    import pytest
    lib_repo = repos["lib_repo"]

    parent_dir = temp_dir / "root_folder"
    child_dir = parent_dir / "nested_child"
    parent_dir.mkdir()
    child_dir.mkdir()

    # 1. Register parent library
    lib1 = lib_repo.create(path=str(parent_dir), name="Parent Lib")
    assert lib1.id is not None

    # 2. Attempting to register child folder must raise ValueError
    with pytest.raises(ValueError, match="overlaps with existing library"):
        lib_repo.create(path=str(child_dir), name="Child Lib")

    # 3. Create independent sibling folder
    sibling_dir = temp_dir / "sibling_folder"
    sibling_dir.mkdir()
    lib2 = lib_repo.create(path=str(sibling_dir), name="Sibling Lib")
    assert lib2.id is not None

    # 4. Attempting to register temp_dir (parent of parent_dir) must also be rejected
    with pytest.raises(ValueError, match="overlaps with existing library"):
        lib_repo.create(path=str(temp_dir), name="Grandparent Lib")


def test_symlink_containment_ignores_external_symlink(repos, temp_dir: Path):
    """Verify that a symlink inside a library directory pointing outside is ignored during indexing."""
    import os
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]

    lib_dir = temp_dir / "contained_lib"
    external_dir = temp_dir / "external_secret"
    lib_dir.mkdir()
    external_dir.mkdir()

    # Create real file in library
    inside_img = lib_dir / "inside.jpg"
    Image.new("RGB", (100, 100), color=(10, 10, 10)).save(inside_img)

    # Create secret file outside library
    outside_img = external_dir / "secret_external.jpg"
    Image.new("RGB", (100, 100), color=(99, 99, 99)).save(outside_img)

    # Try creating symlink inside lib_dir pointing to outside_img
    symlink_path = lib_dir / "symlinked_secret.jpg"
    try:
        os.symlink(str(outside_img), str(symlink_path))
    except (OSError, NotImplementedError):
        # On Windows without Developer Mode, symlinks may require admin; skip if privilege not held
        return

    # Index library
    lib = lib_repo.create(path=str(lib_dir), name="Symlink Test Lib")
    indexer.index_library(lib.id)

    images, count = img_repo.list_images(library_id=lib.id)
    filenames = [img.filename for img in images]

    # Only inside.jpg should be indexed; symlinked_secret.jpg must be strictly excluded!
    assert "inside.jpg" in filenames
    assert "symlinked_secret.jpg" not in filenames

