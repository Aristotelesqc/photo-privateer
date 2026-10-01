"""Regression tests for the v1.3.0 perceptual grouping audit remediation."""
from __future__ import annotations

import random
import threading
import time
from itertools import combinations
from pathlib import Path

import pytest
from PIL import Image

from backend.database import get_db, init_db
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
from backend.services.perceptual import compute_dhash, is_candidate_representation, is_informative_dhash_value
from tests.backend.test_perceptual_grouping import _create_sample_image


def _insert_image(conn, lib_id: int, idx: int, dhash_value: int, sha: str | None = None) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO images (library_id, sha256, dhash, file_path, filename, file_size, file_modified_at,
                            indexed_at, last_seen_on_disk, is_present_on_disk)
        VALUES (?, ?, ?, ?, ?, 1, 0, 't', 't', 1)
        """,
        (lib_id, sha or f"sha-{idx}", f"{dhash_value:016x}", f"/virtual/{idx}.jpg", f"{idx}.jpg"),
    )
    return cur.lastrowid


def _brute_force_pairs(rows: list[tuple[int, int]], threshold: int) -> set[tuple[int, int]]:
    result = set()
    for (id_a, h_a), (id_b, h_b) in combinations(rows, 2):
        if not (is_informative_dhash_value(h_a) and is_informative_dhash_value(h_b)):
            continue
        if (h_a ^ h_b).bit_count() <= threshold:
            result.add((min(id_a, id_b), max(id_a, id_b)))
    return result


def _make_library(conn, temp_dir: Path, name: str = "lib") -> int:
    lib_dir = temp_dir / name
    lib_dir.mkdir(exist_ok=True)
    return LibraryRepository(conn).create(str(lib_dir), name=name).id


@pytest.mark.parametrize("threshold", [0, 3, 10, 16])
def test_banded_candidate_search_matches_brute_force(temp_dir: Path, threshold: int):
    """Pigeonhole band bucketing must find exactly the pairs an all-pairs comparison finds."""
    db_file = temp_dir / "banded.sqlite"
    init_db(db_file)
    rng = random.Random(threshold)
    with get_db(db_file) as conn:
        lib_id = _make_library(conn, temp_dir)
        rows: list[tuple[int, int]] = []
        idx = 0
        # Bursts of near-duplicates around random centers, plus unrelated photos
        for _ in range(25):
            center = rng.getrandbits(64)
            for _ in range(rng.randrange(1, 6)):
                value = center
                for bit in rng.sample(range(64), rng.randrange(0, 14)):
                    value ^= 1 << bit
                rows.append((_insert_image(conn, lib_id, idx, value), value))
                idx += 1
        for _ in range(150):
            value = rng.getrandbits(64)
            rows.append((_insert_image(conn, lib_id, idx, value), value))
            idx += 1
        conn.commit()

        repo = PhotoGroupRepository(conn)
        pairs, total = repo.find_candidates_page(threshold=threshold, limit=100000)
        found = {(p.image_a.id, p.image_b.id) for p in pairs}
        expected = _brute_force_pairs(rows, threshold)
        assert found == expected
        assert total == len(expected)
        # Ordering: ascending distance
        distances = [p.hamming_distance for p in pairs]
        assert distances == sorted(distances)


def test_candidate_total_is_reported_beyond_page_limit(client, db_conn, temp_dir: Path):
    lib_id = _make_library(db_conn, temp_dir)
    rng = random.Random(7)
    value = rng.getrandbits(64)
    while not is_informative_dhash_value(value):
        value = rng.getrandbits(64)
    for i in range(12):  # 12 byte-identical files -> 66 exact pairs
        _insert_image(db_conn, lib_id, i, value, sha="same-content")
    db_conn.commit()

    resp = client.get("/api/groups/candidates", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 66
    assert len(body["pairs"]) == 5
    assert all(p["is_exact_duplicate"] for p in body["pairs"])


def test_low_information_hashes_are_not_perceptual_candidates(temp_dir: Path):
    black = temp_dir / "lens_cap.jpg"
    white = temp_dir / "blank_export.png"
    Image.new("RGB", (300, 200), (0, 0, 0)).save(black)
    Image.new("RGB", (300, 200), (255, 255, 255)).save(white)
    h_black, h_white = compute_dhash(black), compute_dhash(white)
    assert h_black == h_white  # both all-zero: identical hashes for unrelated frames
    assert not is_candidate_representation(h_black, h_white)

    db_file = temp_dir / "lowinfo.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib_id = _make_library(conn, temp_dir)
        a = _insert_image(conn, lib_id, 1, 0)
        b = _insert_image(conn, lib_id, 2, 0)
        c = _insert_image(conn, lib_id, 3, 0, sha="dup")
        d = _insert_image(conn, lib_id, 4, 0, sha="dup")
        conn.commit()
        pairs = PhotoGroupRepository(conn).find_candidate_pairs(threshold=10)
        ids = {(p.image_a.id, p.image_b.id) for p in pairs}
        assert (a, b) not in ids
        # Byte-identical files are still reported as exact duplicates
        assert ids == {(c, d)}


def test_candidate_cache_invalidates_on_every_input_change(temp_dir: Path):
    db_file = temp_dir / "cache.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        lib_id = _make_library(conn, temp_dir)
        base = 0x0F0F_F0F0_3C3C_A5A5
        a = _insert_image(conn, lib_id, 1, base)
        b = _insert_image(conn, lib_id, 2, base ^ 0b11)
        c = _insert_image(conn, lib_id, 3, base ^ 0b111)
        conn.commit()
        repo = PhotoGroupRepository(conn)

        def pair_ids():
            return {(p.image_a.id, p.image_b.id) for p in repo.find_candidate_pairs()}

        assert pair_ids() == {(a, b), (a, c), (b, c)}

        # Cache hit: no recomputation when nothing changed
        calls = []
        original = repo._compute_candidate_tuples
        repo._compute_candidate_tuples = lambda *args: calls.append(1) or original(*args)  # type: ignore[method-assign]
        assert pair_ids() == {(a, b), (a, c), (b, c)}
        assert calls == []

        # Dismissal
        repo.dismiss_candidate_pair(a, b)
        assert pair_ids() == {(a, c), (b, c)}

        # Grouping (both members of the pair grouped -> excluded)
        repo.create_group([a, c])
        assert pair_ids() == {(b, c)}

        # dHash change
        conn.execute("UPDATE images SET dhash = ? WHERE id = ?", (f"{~base & (2**64 - 1):016x}", b))
        conn.commit()
        assert pair_ids() == set()
        conn.execute("UPDATE images SET dhash = ? WHERE id = ?", (f"{base ^ 0b11:016x}", b))
        conn.commit()
        assert pair_ids() == {(b, c)}

        # Disk presence
        conn.execute("UPDATE images SET is_present_on_disk = 0 WHERE id = ?", (b,))
        conn.commit()
        assert pair_ids() == set()
        conn.execute("UPDATE images SET is_present_on_disk = 1 WHERE id = ?", (b,))
        conn.commit()
        assert pair_ids() == {(b, c)}

        # Library archive
        lib_repo.archive(lib_id)
        assert pair_ids() == set()
        assert len(calls) == 7


def test_add_image_to_group_applies_preferred_existing_member_atomically(client, db_conn, temp_dir: Path):
    lib_id = _make_library(db_conn, temp_dir)
    i1, i2, i3 = (_insert_image(db_conn, lib_id, n, 0xABCDEF0123456789 + n) for n in range(3))
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group([i1, i2], preferred_image_id=i1)

    # User picked i2 (already grouped, not the current primary) while adding i3
    resp = client.post(f"/api/groups/{group.id}/images", json={"image_id": i3, "preferred_image_id": i2})
    assert resp.status_code == 200
    body = resp.json()
    assert body["preferred_image_id"] == i2
    primaries = {img["id"]: img["is_primary_representation"] for img in body["images"]}
    assert primaries == {i1: 0, i2: 1, i3: 0}

    # An invalid preferred image is rejected without adding the image
    i4 = _insert_image(db_conn, lib_id, 9, 0x1234_5678_9ABC_DEF0)
    db_conn.commit()
    resp = client.post(f"/api/groups/{group.id}/images", json={"image_id": i4, "preferred_image_id": 999999})
    assert resp.status_code == 400
    assert ImageRepository(db_conn).get_by_id(i4).photo_group_id is None


def test_plural_add_images_to_group_was_removed():
    assert not hasattr(PhotoGroupRepository, "add_images_to_group")


def _scan_engine(conn) -> ScanEngine:
    return ScanEngine(
        image_repo=ImageRepository(conn),
        match_repo=MatchRepository(conn),
        rule_repo=DomainRuleRepository(conn),
        usage_repo=UsageRepository(conn),
        settings_repo=SettingsRepository(conn),
        library_repo=LibraryRepository(conn),
        group_repo=PhotoGroupRepository(conn),
    )


def _indexed_pair(conn, temp_dir: Path, names=("multi_master.jpg", "multi_web.jpg")):
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir(exist_ok=True)
    p1, p2 = photos_dir / names[0], photos_dir / names[1]
    _create_sample_image(p1, (120, 90, 60), "Master")
    with Image.open(p1) as img:
        img.resize((170, 170)).save(p2, format="JPEG", quality=85)
    lib_repo = LibraryRepository(conn)
    img_repo = ImageRepository(conn)
    lib = lib_repo.create(str(photos_dir), name="Gallery")
    LibraryIndexer(lib_repo, img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)
    return lib, img_repo.get_by_path(str(p1.resolve())), img_repo.get_by_path(str(p2.resolve())), p1, p2


def _wait_for_scan(session_id: int) -> None:
    for t in threading.enumerate():
        if t.name == f"scan-worker-{session_id}":
            t.join(timeout=15.0)


def test_scan_plan_reports_grouped_variants_and_session_notes(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)

    plan = _scan_engine(db_conn).plan_scan(image_ids=[web.id], provider_override="mock")
    assert [img.id for img in plan.scannable_images] == [master.id]
    assert plan.grouped_variant_ids == [web.id]

    resp = client.post("/api/scans/prepare", json={"image_ids": [master.id, web.id], "provider": "mock"})
    assert resp.status_code == 200
    projection = resp.json()
    assert projection["selected_count"] == 2
    assert projection["usable_count"] == 1
    assert projection["missing_count"] == 0
    assert projection["grouped_variant_count"] == 1

    session = _scan_engine(db_conn).start_background_scan(image_ids=[web.id], provider_override="mock")
    assert "covered by the primary representation" in (session.notes or "")
    _wait_for_scan(session.id)


def test_grouped_variant_shares_group_discoveries_in_filters_and_review(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)

    session = _scan_engine(db_conn).start_background_scan(image_ids=[master.id, web.id], provider_override="mock")
    _wait_for_scan(session.id)
    db_conn.commit()

    img_repo = ImageRepository(db_conn)
    rep = img_repo.get_by_id(master.id)
    assert rep.match_count > 0
    # Discoveries are recorded once, against the searched representation only (no duplicated triage)
    assert img_repo.get_by_id(web.id).match_count == 0

    for status in ("has_matches", "has_unreviewed"):
        listed, _ = img_repo.list_images(filter_status=status)
        assert {img.id for img in listed} == {master.id, web.id}, status
    listed, _ = img_repo.list_images()
    by_id = {img.id: img for img in listed}
    assert by_id[web.id].group_match_count == rep.match_count
    assert by_id[web.id].group_unreviewed_count == rep.unreviewed_count

    # Review from the variant shows the group's discoveries
    resp = client.get("/api/matches", params={"image_id": web.id, "page_size": 100})
    assert resp.status_code == 200
    variant_matches = resp.json()
    match_ids = [m["id"] for m in variant_matches["matches"]]
    assert len(match_ids) == rep.match_count

    # Triage once: both members leave the unreviewed filter
    match_repo = MatchRepository(db_conn)
    for mid in match_ids:
        match_repo.update_classification_and_notes(mid, classification="APPROVED")
    listed, _ = img_repo.list_images(filter_status="has_unreviewed")
    assert listed == []
    listed, _ = img_repo.list_images(filter_status="has_matches")
    assert {img.id for img in listed} == {master.id, web.id}


def test_in_place_reexport_keeps_group_membership_and_primary(temp_dir: Path):
    db_file = temp_dir / "reexport.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib, master, web, p1, _p2 = _indexed_pair(conn, temp_dir)
        group_repo = PhotoGroupRepository(conn)
        group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)

        # Photographer re-exports an edit over the primary file
        time.sleep(0.01)
        _create_sample_image(p1, (124, 90, 60), "Master edit")
        img_repo = ImageRepository(conn)
        LibraryIndexer(LibraryRepository(conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)

        new_master = img_repo.get_by_path(str(p1.resolve()))
        assert new_master.id != master.id  # history of the old content is preserved separately
        refreshed = group_repo.get_group(group.id)
        assert refreshed is not None
        assert {img.id for img in refreshed.images} == {new_master.id, web.id}
        assert refreshed.preferred_image_id == new_master.id
        assert img_repo.get_by_id(new_master.id).is_primary_representation == 1
        assert img_repo.get_by_id(web.id).is_primary_representation == 0
        archived = img_repo.get_by_id(master.id)
        assert archived.photo_group_id is None and not archived.is_present_on_disk


def test_repair_groups_runs_once_per_index_pass(temp_dir: Path, monkeypatch):
    db_file = temp_dir / "repair_once.sqlite"
    init_db(db_file)
    photos_dir = temp_dir / "photos"
    photos_dir.mkdir()
    paths = [photos_dir / f"p{i}.jpg" for i in range(6)]
    for i, p in enumerate(paths):
        _create_sample_image(p, (20 * i, 100, 150), f"P{i}")

    with get_db(db_file) as conn:
        lib_repo = LibraryRepository(conn)
        img_repo = ImageRepository(conn)
        indexer = LibraryIndexer(lib_repo, img_repo, ThumbnailCache(temp_dir / "thumbs"))
        lib = lib_repo.create(str(photos_dir), name="Gallery")
        indexer.index_library(lib.id)

        calls = []
        original = PhotoGroupRepository.repair_groups
        monkeypatch.setattr(PhotoGroupRepository, "repair_groups", lambda self: calls.append(1) or original(self))

        time.sleep(0.01)
        for i, p in enumerate(paths):
            _create_sample_image(p, (20 * i + 3, 100, 150), f"P{i} edit")
        indexer.index_library(lib.id)
        assert calls == [1]


def test_migration_010_triggers_bump_generation(temp_dir: Path):
    db_file = temp_dir / "gen.sqlite"
    applied = init_db(db_file)
    assert 10 in applied
    with get_db(db_file) as conn:
        def gen():
            return conn.execute("SELECT generation FROM group_candidate_state WHERE id = 1").fetchone()[0]

        lib_id = _make_library(conn, temp_dir)
        g0 = gen()
        img = _insert_image(conn, lib_id, 1, 0x1111_2222_3333_4444)
        conn.commit()
        g1 = gen()
        assert g1 > g0
        # Unrelated column updates (scan bookkeeping) do not invalidate the cache
        conn.execute("UPDATE images SET scan_count = scan_count + 1, match_count = 3 WHERE id = ?", (img,))
        conn.commit()
        assert gen() == g1
        conn.execute("UPDATE images SET dhash = '0000000000000001' WHERE id = ?", (img,))
        conn.commit()
        assert gen() == g1 + 1
