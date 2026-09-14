"""Tests for perceptual source hashing, photo grouping, candidate discovery, and scan deduplication."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

from backend.database import get_db, init_db
from backend.models import ImageOut, PhotoGroupCreate, DismissCandidateRequest, SetPreferredRequest
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.group_repo import PhotoGroupRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.services.library_indexer import LibraryIndexer
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.scan_engine import ScanEngine
from backend.services.perceptual import (
    compute_dhash,
    hamming_distance,
    is_candidate_representation,
    DHASH_CANDIDATE_THRESHOLD,
)


def _create_sample_image(path: Path, color: tuple[int, int, int], text: str = "") -> None:
    img = Image.new("RGB", (200, 200), color=color)
    draw = ImageDraw.Draw(img)
    if text:
        draw.text((20, 20), text, fill=(255, 255, 255))
    img.save(path, format="JPEG", quality=95)


def test_dhash_calculation_and_hamming_distance(temp_dir: Path):
    p1 = temp_dir / "img1.jpg"
    p2 = temp_dir / "img2.jpg"
    p3 = temp_dir / "img3.jpg"

    # Create base image
    _create_sample_image(p1, (100, 150, 200), "Photo 1")
    # Create minor variation (slightly different quality/resolution of same image)
    img1 = Image.open(p1)
    img_variant = img1.resize((190, 190))
    img_variant.save(p2, format="JPEG", quality=80)
    # Create completely different image
    _create_sample_image(p3, (20, 30, 40), "Completely Different Pattern")

    h1 = compute_dhash(p1)
    h2 = compute_dhash(p2)
    h3 = compute_dhash(p3)

    assert h1 is not None and len(h1) == 16
    assert h2 is not None and len(h2) == 16
    assert h3 is not None and len(h3) == 16

    # Same file has 0 distance
    assert hamming_distance(h1, h1) == 0

    # Variant of same photo has low distance (<= threshold)
    dist_variant = hamming_distance(h1, h2)
    assert dist_variant <= DHASH_CANDIDATE_THRESHOLD
    assert is_candidate_representation(h1, h2)

    # Distant image has distinct hash
    assert h1 != h3


def test_migration_009_schema_and_backward_compatibility(temp_dir: Path):
    db_file = temp_dir / "test_grouping.sqlite"
    applied = init_db(db_file)
    assert 9 in applied

    with get_db(db_file) as conn:
        cur = conn.cursor()
        # Verify tables exist
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cur.fetchall()}
        assert "photo_groups" in tables
        assert "dismissed_group_candidates" in tables

        # Verify image columns exist
        cur.execute("PRAGMA table_info(images)")
        cols = {row["name"] for row in cur.fetchall()}
        assert "dhash" in cols
        assert "photo_group_id" in cols
        assert "is_primary_representation" in cols


def test_photo_group_lifecycle_and_candidate_discovery(temp_dir: Path):
    db_file = temp_dir / "test_grouping.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    # Create two representations of Photo A (e.g., master and web export)
    p_a1 = photos_dir / "sunset_master.jpg"
    p_a2 = photos_dir / "sunset_web.jpg"
    _create_sample_image(p_a1, (200, 100, 50), "Sunset")
    with Image.open(p_a1) as img:
        img.resize((150, 150)).save(p_a2, format="JPEG", quality=80)

    # Create Photo B (distinct)
    p_b = photos_dir / "mountain.jpg"
    _create_sample_image(p_b, (50, 150, 50), "Mountain")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib = lib_repo.create(str(photos_dir), name="Gallery")
        indexer.index_library(lib.id)

        images = img_repo.list_images()[0]
        assert len(images) == 3
        # Check dhashes were populated
        for img in images:
            assert img.dhash is not None

        # 1. Candidate discovery
        candidates = group_repo.find_candidate_pairs(threshold=10)
        assert len(candidates) >= 1
        # Ensure sunset pair is detected
        sunset_pair = next(
            (c for c in candidates if {c.image_a.filename, c.image_b.filename} == {"sunset_master.jpg", "sunset_web.jpg"}),
            None,
        )
        assert sunset_pair is not None
        assert sunset_pair.hamming_distance <= 10

        # 2. Dismiss candidate pair
        group_repo.dismiss_candidate_pair(sunset_pair.image_a.id, sunset_pair.image_b.id)
        remaining_candidates = group_repo.find_candidate_pairs(threshold=10)
        assert not any(
            {c.image_a.id, c.image_b.id} == {sunset_pair.image_a.id, sunset_pair.image_b.id}
            for c in remaining_candidates
        )

        # 3. Create group with preferred image
        img_master = next(i for i in images if i.filename == "sunset_master.jpg")
        img_web = next(i for i in images if i.filename == "sunset_web.jpg")

        group = group_repo.create_group(
            image_ids=[img_master.id, img_web.id],
            preferred_image_id=img_master.id,
            name="Sunset Series",
        )
        assert group.id is not None
        assert group.preferred_image_id == img_master.id
        assert len(group.images) == 2

        # Verify image flags
        upd_master = img_repo.get_by_id(img_master.id)
        upd_web = img_repo.get_by_id(img_web.id)
        assert upd_master.photo_group_id == group.id
        assert upd_master.is_primary_representation == 1
        assert upd_web.photo_group_id == group.id
        assert upd_web.is_primary_representation == 0

        # 4. Change preferred representation
        group_repo.set_preferred_image(group.id, img_web.id)
        upd_master = img_repo.get_by_id(img_master.id)
        upd_web = img_repo.get_by_id(img_web.id)
        assert upd_web.is_primary_representation == 1
        assert upd_master.is_primary_representation == 0

        # 5. Remove image from group dissolves group when <= 1 remains
        dissolved = group_repo.remove_image_from_group(img_web.id)
        assert dissolved is None
        final_master = img_repo.get_by_id(img_master.id)
        assert final_master.photo_group_id is None
        assert final_master.is_primary_representation == 1


def test_scan_deduplication_one_call_per_group(temp_dir: Path):
    db_file = temp_dir / "test_scan_dedup.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    # Create two representations of same photo
    p1 = photos_dir / "photo_v1.jpg"
    p2 = photos_dir / "photo_v2.jpg"
    _create_sample_image(p1, (100, 100, 100), "Version 1")
    with Image.open(p1) as img:
        img.resize((160, 160)).save(p2, format="JPEG", quality=85)

    # Create distinct second photo
    p3 = photos_dir / "photo_solo.jpg"
    _create_sample_image(p3, (200, 200, 200), "Solo")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        match_repo = MatchRepository(conn)
        rule_repo = DomainRuleRepository(conn)
        usage_repo = UsageRepository(conn)
        settings_repo = SettingsRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib = lib_repo.create(str(photos_dir), name="Dedup Gallery")
        indexer.index_library(lib.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))
        img3 = img_repo.get_by_path(str(p3.resolve()))

        # Group p1 and p2 together with p1 as preferred
        group = group_repo.create_group(
            image_ids=[img1.id, img2.id],
            preferred_image_id=img1.id,
            name="Grouped Pair",
        )

        scan_engine = ScanEngine(
            image_repo=img_repo,
            match_repo=match_repo,
            rule_repo=rule_repo,
            usage_repo=usage_repo,
            settings_repo=settings_repo,
            library_repo=lib_repo,
            group_repo=group_repo,
        )

        # Case A: User selects BOTH variants of the group + the solo photo (3 selected images)
        scannable, missing = scan_engine.validate_scan_request(
            image_ids=[img1.id, img2.id, img3.id],
            provider_override="mock",
        )
        # The two variants MUST collapse into exactly 1 scannable image (the preferred representation img1)
        # Plus img3 -> total scannable count = 2 (instead of 3)
        assert len(scannable) == 2
        scannable_ids = [s.id for s in scannable]
        assert img1.id in scannable_ids
        assert img2.id not in scannable_ids
        assert img3.id in scannable_ids

        # Case B: User selects ONLY secondary variant img2
        # Should resolve to preferred representation img1
        scannable_single, _ = scan_engine.validate_scan_request(
            image_ids=[img2.id],
            provider_override="mock",
        )
        assert len(scannable_single) == 1
        assert scannable_single[0].id == img1.id
