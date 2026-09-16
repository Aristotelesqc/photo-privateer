"""Tests for perceptual source hashing, photo grouping, candidate discovery, and scan deduplication."""
from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw

from backend.database import get_db, init_db
from backend.models import ImageOut, PhotoGroupCreate, DismissCandidateRequest, SetPreferredRequest
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.group_repo import PhotoGroupRepository, PhotoGroupNotFoundError
from backend.repositories.match_repo import MatchRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.services.library_indexer import LibraryIndexer
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.scan_engine import ScanEngine
from backend.services.usage_tracker import UsageTracker
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

        # 5. Validation guards
        import pytest
        # Setting preferred on non-existent group raises PhotoGroupNotFoundError
        with pytest.raises((PhotoGroupNotFoundError, KeyError)):
            group_repo.set_preferred_image(99999, img_web.id)

        # Setting preferred to non-member raises ValueError
        with pytest.raises(ValueError):
            group_repo.set_preferred_image(group.id, 99999)

        # Dismissing identical IDs raises ValueError
        with pytest.raises(ValueError):
            group_repo.dismiss_candidate_pair(img_web.id, img_web.id)

        # 6. Remove image from group dissolves group when <= 1 remains
        dissolved = group_repo.remove_image_from_group(group.id, img_web.id)
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


def test_scan_completed_marks_group_variants_as_scanned(temp_dir: Path):
    db_file = temp_dir / "test_grouping_scan.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    p1 = photos_dir / "photo_v1.jpg"
    p2 = photos_dir / "photo_v2.jpg"
    _create_sample_image(p1, (100, 100, 100), "Version 1")
    with Image.open(p1) as img:
        img.resize((160, 160)).save(p2, format="JPEG", quality=85)

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

        lib = lib_repo.create(str(photos_dir), name="Scan Group Gallery")
        indexer.index_library(lib.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))

        group = group_repo.create_group(
            image_ids=[img1.id, img2.id],
            preferred_image_id=img1.id,
            name="Pair",
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

        # Before scan, both have scan_count == 0
        assert img_repo.get_by_id(img1.id).scan_count == 0
        assert img_repo.get_by_id(img2.id).scan_count == 0
        assert img_repo.get_by_id(img2.id).last_scanned_at is None

        # Start background scan with only img1 (or img1 & img2 which collapses to img1)
        sess = scan_engine.start_background_scan(
            image_ids=[img1.id, img2.id],
            provider_override="mock",
        )

        # Wait for scan worker thread to finish
        import threading
        for t in threading.enumerate():
            if t.name == f"scan-worker-{sess.id}":
                t.join(timeout=10.0)

        # Both representative (img1) and sibling variant (img2) must be marked scanned
        updated_img1 = img_repo.get_by_id(img1.id)
        updated_img2 = img_repo.get_by_id(img2.id)

        assert updated_img1.scan_count == 1
        assert updated_img1.last_scanned_at is not None
        assert updated_img2.scan_count == 1
        assert updated_img2.last_scanned_at is not None
        assert updated_img2.last_scanned_at == updated_img1.last_scanned_at


def test_add_image_to_existing_group(temp_dir: Path):
    db_file = temp_dir / "test_add_group.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    p1 = photos_dir / "photo_v1.jpg"
    p2 = photos_dir / "photo_v2.jpg"
    p3 = photos_dir / "photo_v3.jpg"
    _create_sample_image(p1, (80, 80, 80), "Version 1")
    with Image.open(p1) as img:
        img.resize((170, 170)).save(p2, format="JPEG", quality=90)
        img.resize((150, 150)).save(p3, format="JPEG", quality=80)

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib = lib_repo.create(str(photos_dir), name="Add Group Gallery")
        indexer.index_library(lib.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))
        img3 = img_repo.get_by_path(str(p3.resolve()))

        # Initial group with img1 and img2
        group = group_repo.create_group(
            image_ids=[img1.id, img2.id],
            preferred_image_id=img1.id,
            name="Initial Group",
        )
        assert len(group.images) == 2

        # Add img3 to existing group
        updated_group = group_repo.add_image_to_group(
            group_id=group.id,
            image_id=img3.id,
            set_preferred=False,
        )
        assert len(updated_group.images) == 3
        member_ids = {img.id for img in updated_group.images}
        assert member_ids == {img1.id, img2.id, img3.id}

        # img3 should have photo_group_id set and is_primary_representation == 0
        reloaded_img3 = img_repo.get_by_id(img3.id)
        assert reloaded_img3.photo_group_id == group.id
        assert reloaded_img3.is_primary_representation == 0

        # Cannot add an image that is already in a group
        try:
            group_repo.add_image_to_group(group.id, img3.id)
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "already belongs to a photo group" in str(exc)

        # find_candidate_pairs must filter out pairs where both images are already grouped
        candidates = group_repo.find_candidate_pairs(threshold=16)
        # All 3 images are grouped -> 0 candidate pairs between them
        assert len(candidates) == 0


def test_preferred_image_in_archived_library_falls_back_to_active_variant(temp_dir: Path):
    db_file = temp_dir / "test_archived_fallback.sqlite"
    init_db(db_file)
    lib1_dir = temp_dir / "lib1"
    lib2_dir = temp_dir / "lib2"
    lib1_dir.mkdir()
    lib2_dir.mkdir()

    p1 = lib1_dir / "active_img.jpg"
    p2 = lib2_dir / "archived_img.jpg"
    _create_sample_image(p1, (120, 120, 120), "Active")
    with Image.open(p1) as img:
        img.resize((180, 180)).save(p2, format="JPEG")

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

        lib1 = lib_repo.create(str(lib1_dir), name="Active Library")
        lib2 = lib_repo.create(str(lib2_dir), name="Archive Me")

        indexer.index_library(lib1.id)
        indexer.index_library(lib2.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))

        # Group them with img2 (in lib2) as preferred
        group_repo.create_group(
            image_ids=[img1.id, img2.id],
            preferred_image_id=img2.id,
            name="Cross-Lib Group",
        )

        # Now archive lib2
        lib_repo.archive(lib2.id)

        scan_engine = ScanEngine(
            image_repo=img_repo,
            match_repo=match_repo,
            rule_repo=rule_repo,
            usage_repo=usage_repo,
            settings_repo=settings_repo,
            library_repo=lib_repo,
            group_repo=group_repo,
        )

        # Selecting img1 should fall back to img1 as canonical representation instead of failing
        scannable, missing = scan_engine.validate_scan_request(
            image_ids=[img1.id],
            provider_override="mock",
        )
        assert len(scannable) == 1
        assert scannable[0].id == img1.id
        assert len(missing) == 0


def test_dhash_backfill_does_not_hold_write_lock(temp_dir: Path):
    db_file = temp_dir / "test_dhash_lock.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    p1 = photos_dir / "img1.jpg"
    p2 = photos_dir / "img2.jpg"
    _create_sample_image(p1, (50, 60, 70), "P1")
    _create_sample_image(p2, (80, 90, 100), "P2")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib = lib_repo.create(str(photos_dir), name="Lock Test")
        indexer.index_library(lib.id)

        # Manually reset dhash to NULL to simulate legacy pre-v1.3.0 photos needing backfill
        cur = conn.cursor()
        cur.execute("UPDATE images SET dhash = NULL")
        conn.commit()

        # Re-indexing will trigger unchanged-file dhash calculation
        # It must commit any active transaction before calling compute_dhash
        res = indexer.index_library(lib.id)
        assert res["unchanged"] == 2

        # Verify dhash values were safely backfilled
        cur.execute("SELECT COUNT(*) FROM images WHERE dhash IS NOT NULL AND dhash != ''")
        assert cur.fetchone()[0] == 2


def test_scan_prepare_missing_count_with_grouped_variants(temp_dir: Path):
    db_file = temp_dir / "test_missing_count.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    p1 = photos_dir / "photo_v1.jpg"
    p2 = photos_dir / "photo_v2.jpg"
    _create_sample_image(p1, (110, 110, 110), "V1")
    with Image.open(p1) as img:
        img.resize((150, 150)).save(p2, format="JPEG")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        usage_repo = UsageRepository(conn)
        settings_repo = SettingsRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)
        tracker = UsageTracker(usage_repo, settings_repo)

        lib = lib_repo.create(str(photos_dir), name="Gallery")
        indexer.index_library(lib.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))

        # Group img1 and img2
        group_repo.create_group(
            image_ids=[img1.id, img2.id],
            preferred_image_id=img1.id,
            name="Variants",
        )

        scan_engine = ScanEngine(
            image_repo=img_repo,
            match_repo=MatchRepository(conn),
            rule_repo=DomainRuleRepository(conn),
            usage_repo=usage_repo,
            settings_repo=settings_repo,
            library_repo=lib_repo,
            group_repo=group_repo,
        )

        # 2 images selected, both exist, collapsed to 1 representative
        usable, missing_ids = scan_engine.validate_scan_request(
            image_ids=[img1.id, img2.id],
            provider_override="mock",
        )
        assert len(usable) == 1
        assert len(missing_ids) == 0

        # When missing_count is explicitly passed as len(missing_ids)
        projection = tracker.prepare_scan_projection(
            image_count=2,
            usable_count=len(usable),
            provider_override="mock",
            missing_count=len(missing_ids),
        )
        assert projection.selected_count == 2
        assert projection.usable_count == 1
        # Crucial check: deduplicated variants must NOT be reported as missing files!
        assert projection.missing_count == 0


def test_purge_library_repairs_orphan_groups(temp_dir: Path):
    db_file = temp_dir / "test_purge_repair.sqlite"
    init_db(db_file)
    lib1_dir = temp_dir / "lib1"
    lib2_dir = temp_dir / "lib2"
    lib1_dir.mkdir()
    lib2_dir.mkdir()

    p1 = lib1_dir / "img1.jpg"
    p2 = lib1_dir / "img2.jpg"
    p3 = lib2_dir / "img3.jpg"
    _create_sample_image(p1, (10, 10, 10), "1")
    _create_sample_image(p2, (20, 20, 20), "2")
    _create_sample_image(p3, (30, 30, 30), "3")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib1 = lib_repo.create(str(lib1_dir), name="Lib 1")
        lib2 = lib_repo.create(str(lib2_dir), name="Lib 2")
        indexer.index_library(lib1.id)
        indexer.index_library(lib2.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))
        img3 = img_repo.get_by_path(str(p3.resolve()))

        g1 = group_repo.create_group(image_ids=[img1.id, img2.id], preferred_image_id=img1.id)
        group_repo.add_image_to_group(g1.id, img3.id, set_preferred=False)

        # Purging lib1 deletes img1 and img2, leaving only img3
        lib_repo.purge(lib1.id)

        # Group 1 had 3 images, 2 deleted -> only 1 remaining (img3)
        # repair_groups() in purge() dissolves < 2 member groups into singletons
        reloaded_img3 = img_repo.get_by_id(img3.id)
        assert reloaded_img3.photo_group_id is None
        assert reloaded_img3.is_primary_representation == 1

        # Photo group must be completely deleted
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM photo_groups WHERE id = ?", (g1.id,))
        assert cur.fetchone()[0] == 0


def test_photo_group_not_found_error_formatting_no_quotes():
    from backend.repositories.group_repo import PhotoGroupNotFoundError
    err = PhotoGroupNotFoundError("Photo group #999 not found.")
    # Standard Exception formatting produces clean string without outer single quotes
    assert str(err) == "Photo group #999 not found."
    assert not str(err).startswith("'")
    assert not str(err).endswith("'")


def test_create_group_concurrency_race_condition(temp_dir: Path):
    db_file = temp_dir / "test_concurrency_race.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    p1 = photos_dir / "img1.jpg"
    p2 = photos_dir / "img2.jpg"
    _create_sample_image(p1, (40, 50, 60), "1")
    _create_sample_image(p2, (70, 80, 90), "2")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib = lib_repo.create(str(photos_dir), name="Race Test")
        indexer.index_library(lib.id)

        img1 = img_repo.get_by_path(str(p1.resolve()))
        img2 = img_repo.get_by_path(str(p2.resolve()))

        # If img1 is concurrently claimed by another group
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO photo_groups (name, created_at, updated_at) VALUES ('Other Group', '2026-01-01', '2026-01-01')"
        )
        other_gid = cur.lastrowid
        cur.execute("UPDATE images SET photo_group_id = ? WHERE id = ?", (other_gid, img1.id))
        conn.commit()

        # create_group should fail and roll back without creating a lingering group
        try:
            group_repo.create_group(image_ids=[img1.id, img2.id])
            assert False, "Should have raised ValueError"
        except ValueError as exc:
            assert "already belongs to a photo group" in str(exc) or "concurrently" in str(exc)

        # Ensure no new group was left in photo_groups (only other_gid remains)
        cur.execute("SELECT COUNT(*) FROM photo_groups WHERE id != ?", (other_gid,))
        assert cur.fetchone()[0] == 0


def test_candidate_search_loop_heap_tuple_ordering(temp_dir: Path):
    db_file = temp_dir / "test_heap_tuple.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()

    p1 = photos_dir / "img1.jpg"
    p2 = photos_dir / "img2.jpg"
    p3 = photos_dir / "img3.jpg"
    p4 = photos_dir / "img4.jpg"

    _create_sample_image(p1, (100, 100, 100), "Base")
    with Image.open(p1) as img:
        img.resize((190, 190)).save(p2, format="JPEG", quality=90)
        img.resize((180, 180)).save(p3, format="JPEG", quality=85)
        img.resize((170, 170)).save(p4, format="JPEG", quality=80)

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        group_repo = PhotoGroupRepository(conn)
        thumb_cache = ThumbnailCache(temp_dir / "thumbs")
        indexer = LibraryIndexer(lib_repo, img_repo, thumb_cache)

        lib = lib_repo.create(str(photos_dir), name="Heap Test")
        indexer.index_library(lib.id)

        candidates = group_repo.find_candidate_pairs(threshold=16, limit=2)
        assert len(candidates) <= 2
        for c in candidates:
            assert isinstance(c.hamming_distance, int)
            assert c.hamming_distance <= 16
