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
from backend.repositories.group_repo import PhotoGroupRepository, MAX_CANDIDATES_PER_PHOTO
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
    for i in range(12):  # 12 byte-identical files -> 11 exact pairs (linear, not a 66-pair clique)
        _insert_image(db_conn, lib_id, i, value, sha="same-content")
    db_conn.commit()

    resp = client.get("/api/groups/candidates", params={"limit": 5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 11
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
        # quality 84: the deterministic mock provider returns the same discoveries for both files
        img.resize((170, 170)).save(p2, format="JPEG", quality=84)
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
    assert "covered by the search of another photo in its photo group" in (session.notes or "")
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


def _reexport_edit(path: Path) -> None:
    """Simulates re-exporting a retouched version of a photo over the same file."""
    from PIL import ImageEnhance

    with Image.open(path) as img:
        edited = ImageEnhance.Brightness(img.convert("RGB")).enhance(1.08)
        edited = ImageEnhance.Contrast(edited).enhance(1.05)
    edited.save(path, format="JPEG", quality=90)


def _scan(conn, image_ids: list[int]) -> None:
    session = _scan_engine(conn).start_background_scan(image_ids=image_ids, provider_override="mock")
    _wait_for_scan(session.id)
    conn.commit()


def _group_review(client, image_id: int) -> list[dict]:
    resp = client.get("/api/matches", params={"image_id": image_id, "page_size": 200})
    assert resp.status_code == 200
    return resp.json()["matches"]


def _identity(m: dict) -> tuple:
    return (m["source_kind"], m["page_url"] or "", m["candidate_image_url"] or "")


def _assert_provider_returns_same_discoveries(path_a: str, path_b: str) -> None:
    """Precondition: searching either representation yields the same web discoveries."""
    from backend.providers.mock_provider import MockSearchProvider

    provider = MockSearchProvider()

    def ids(path: str) -> set:
        return {(i.source_kind, i.page_url or "", i.candidate_image_url or "") for i in provider.search(path).items}

    assert ids(path_a) and ids(path_a) == ids(path_b)


def test_validated_reexport_keeps_group_role_and_discovery_history(client, db_conn, temp_dir: Path):
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    _scan(db_conn, [master.id])

    before = _group_review(client, web.id)
    assert before
    triaged = before[0]
    MatchRepository(db_conn).update_classification_and_notes(
        triaged["id"], classification="UNAUTHORIZED", notes="Sent takedown"
    )
    db_conn.commit()

    time.sleep(0.01)
    _reexport_edit(p1)
    img_repo = ImageRepository(db_conn)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)

    new_master = img_repo.get_by_path(str(p1.resolve()))
    assert new_master.id != master.id  # the replaced content stays archived as its own record
    refreshed = group_repo.get_group(group.id)
    assert {img.id for img in refreshed.images} == {new_master.id, web.id}
    assert refreshed.preferred_image_id == new_master.id
    assert new_master.is_primary_representation == 1
    archived = img_repo.get_by_id(master.id)
    assert archived.photo_group_id is None and not archived.is_present_on_disk

    # Discovery history and triage follow the re-export, exactly once, from either member
    for member in (new_master.id, web.id):
        after = _group_review(client, member)
        assert sorted(_identity(m) for m in after) == sorted(_identity(m) for m in before)
        kept = next(m for m in after if m["id"] == triaged["id"])
        assert kept["classification"] == "UNAUTHORIZED"
        assert kept["notes"] == "Sent takedown"
        assert kept["first_seen_at"] == triaged["first_seen_at"]
    # Scan counts are physical per-file history: the edited content itself was never searched,
    # nor was the variant, so the group is offered for a new search (its triage is kept)
    assert new_master.scan_count == 0 and archived.scan_count == 1
    listed, _ = img_repo.list_images(filter_status="unscanned")
    assert {img.id for img in listed} == {new_master.id, web.id}


def test_unrelated_photo_reusing_a_grouped_path_is_not_grouped(db_conn, temp_dir: Path):
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    group_repo = PhotoGroupRepository(db_conn)
    group_repo.create_group([master.id, web.id], preferred_image_id=master.id)

    time.sleep(0.01)
    _create_sample_image(p1, (10, 160, 220), "A completely different photograph")
    img_repo = ImageRepository(db_conn)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)

    unrelated = img_repo.get_by_path(str(p1.resolve()))
    assert unrelated.id != master.id
    assert unrelated.photo_group_id is None
    archived = img_repo.get_by_id(master.id)
    assert archived.photo_group_id is None and not archived.is_present_on_disk
    # The remaining member is no longer in a group of one
    assert img_repo.get_by_id(web.id).photo_group_id is None
    # The unrelated photo is searched on its own
    plan = _scan_engine(db_conn).plan_scan(image_ids=[unrelated.id], provider_override="mock")
    assert [img.id for img in plan.scannable_images] == [unrelated.id]
    assert plan.grouped_variant_ids == []


def test_changing_searched_representation_does_not_duplicate_discoveries(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    _scan(db_conn, [master.id])

    first = _group_review(client, master.id)
    assert first
    triaged = first[0]
    MatchRepository(db_conn).update_classification_and_notes(triaged["id"], classification="APPROVED", notes="Licensed")
    db_conn.commit()

    # User makes the variant the primary representation, then rescans the group through it
    group_repo.set_preferred_image(group.id, web.id)
    _scan(db_conn, [master.id, web.id])

    second = _group_review(client, master.id)
    identities = [_identity(m) for m in second]
    assert len(identities) == len(set(identities))  # each discovery exactly once
    assert set(identities) >= {_identity(m) for m in first}
    kept = next(m for m in second if m["id"] == triaged["id"])
    assert kept["classification"] == "APPROVED" and kept["notes"] == "Licensed"
    listed, _ = ImageRepository(db_conn).list_images(group_id=group.id)
    assert all(img.group_match_count == len(second) for img in listed)


def test_preferred_unavailable_fallback_does_not_duplicate_discoveries(client, db_conn, temp_dir: Path):
    _lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    _scan(db_conn, [master.id])
    first = _group_review(client, web.id)
    assert first

    # Primary file temporarily unavailable: the scan falls back to the variant
    hidden = p1.with_suffix(".hidden")
    p1.rename(hidden)
    try:
        plan = _scan_engine(db_conn).plan_scan(image_ids=[web.id], provider_override="mock")
        assert [img.id for img in plan.scannable_images] == [web.id]
        _scan(db_conn, [web.id])
    finally:
        hidden.rename(p1)

    second = _group_review(client, web.id)
    identities = [_identity(m) for m in second]
    assert len(identities) == len(set(identities))
    assert set(identities) >= {_identity(m) for m in first}


def test_grouping_with_an_already_scanned_photo_covers_the_group(db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    img_repo = ImageRepository(db_conn)
    group_repo = PhotoGroupRepository(db_conn)

    # Scanned while ungrouped (e.g. in v1.2.x), then grouped with a never-scanned variant
    _scan(db_conn, [master.id])
    assert img_repo.get_by_id(web.id).scan_count == 0
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)

    unscanned, _ = img_repo.list_images(filter_status="unscanned")
    assert unscanned == []
    scanned, _ = img_repo.list_images(filter_status="scanned")
    assert {img.id for img in scanned} == {master.id, web.id}
    by_id = {img.id: img for img in img_repo.list_images()[0]}
    assert by_id[web.id].group_scan_count == 1
    assert by_id[web.id].group_last_scanned_at == img_repo.get_by_id(master.id).last_scanned_at

    # A variant added later to the covered group does not re-enter Unscanned either
    extra_path = Path(master.file_path).with_name("multi_extra.jpg")
    with Image.open(master.file_path) as img:
        img.resize((150, 150)).save(extra_path, format="JPEG", quality=80)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(
        master.library_id
    )
    extra = img_repo.get_by_path(str(extra_path.resolve()))
    unscanned, _ = img_repo.list_images(filter_status="unscanned")
    assert {img.id for img in unscanned} == {extra.id}
    group_repo.add_image_to_group(group.id, extra.id)
    unscanned, _ = img_repo.list_images(filter_status="unscanned")
    assert unscanned == []


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


# --- Follow-up review on 3c04c3f: identity transitions -------------------------------------------


def _matches_of(conn, image_ids: list[int]) -> list:
    """All physical observations (logical discoveries and folded observations) of the photos."""
    placeholders = ",".join("?" for _ in image_ids)
    return conn.execute(
        f"SELECT * FROM matches WHERE image_id IN ({placeholders}) ORDER BY id", tuple(image_ids)
    ).fetchall()


def _logical_of(conn, image_ids: list[int]) -> list:
    """Logical discoveries only (what review lists and counts)."""
    return [r for r in _matches_of(conn, image_ids) if r["canonical_match_id"] is None]


def _row_identity(r) -> tuple:
    return (r["source_kind"], r["page_url"] or "", r["candidate_image_url"] or "")


def _scan_both_ungrouped(conn, master, web):
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    _scan(conn, [master.id])
    _scan(conn, [web.id])
    rows = _matches_of(conn, [master.id, web.id])
    identities = [_row_identity(r) for r in rows]
    assert len(identities) == 2 * len(set(identities))  # each discovery stored once per photo
    return rows


@pytest.mark.parametrize("via", ["create_group", "add_image_to_group"])
def test_grouping_already_scanned_photos_coalesces_discoveries(db_conn, temp_dir: Path, via: str):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    rows = _scan_both_ungrouped(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    x_master = next(r for r in rows if r["image_id"] == master.id)
    x_web = next(r for r in rows if r["image_id"] == web.id and _row_identity(r) == _row_identity(x_master))
    # Older first sighting on the master, newer last sighting and a note on the web export
    db_conn.execute("UPDATE matches SET first_seen_at = '2026-01-01T00:00:00+00:00' WHERE id = ?", (x_master["id"],))
    db_conn.execute("UPDATE matches SET last_seen_at = '2026-12-31T00:00:00+00:00' WHERE id = ?", (x_web["id"],))
    db_conn.commit()
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED", notes="Reported", acknowledged=True)
    db_conn.commit()

    group_repo = PhotoGroupRepository(db_conn)
    if via == "create_group":
        group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    else:
        extra = _insert_image(db_conn, master.library_id, 99, 0x0F0F_F0F0_3C3C_A5A5)
        db_conn.commit()
        group = group_repo.create_group([master.id, extra], preferred_image_id=master.id)
        group_repo.add_image_to_group(group.id, web.id)

    after = _logical_of(db_conn, [master.id, web.id])
    identities = [_row_identity(r) for r in after]
    assert len(identities) == len(set(identities)) == len(rows) // 2  # exactly one logical discovery each
    # ...while every physical observation is kept (folded, not deleted)
    assert len(_matches_of(db_conn, [master.id, web.id])) == len(rows)
    merged = next(r for r in after if _row_identity(r) == _row_identity(x_master))
    assert merged["first_seen_at"] == "2026-01-01T00:00:00+00:00"
    assert merged["last_seen_at"] == "2026-12-31T00:00:00+00:00"
    assert merged["classification"] == "UNAUTHORIZED"
    assert merged["notes"] == "Reported"
    assert merged["acknowledged_at"] is not None and merged["is_new"] == 0
    img_repo = ImageRepository(db_conn)
    total = img_repo.get_by_id(master.id).match_count + img_repo.get_by_id(web.id).match_count
    assert total == len(after)


def test_grouping_with_conflicting_decisions_requires_explicit_rereview(db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    rows = _scan_both_ungrouped(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    x_master = next(r for r in rows if r["image_id"] == master.id)
    x_web = next(r for r in rows if r["image_id"] == web.id and _row_identity(r) == _row_identity(x_master))
    match_repo.update_classification_and_notes(x_master["id"], classification="APPROVED", notes="Licensed to client")
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED")
    db_conn.commit()

    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)

    merged = [r for r in _logical_of(db_conn, [master.id, web.id]) if _row_identity(r) == _row_identity(x_master)]
    assert len(merged) == 1
    merged = merged[0]
    # Both observations still exist, each keeping its own prior decision as inspectable provenance
    observations = {r["id"]: r for r in _matches_of(db_conn, [master.id, web.id]) if _row_identity(r) == _row_identity(x_master)}
    assert set(observations) == {x_master["id"], x_web["id"]}
    folded = next(r for r in observations.values() if r["canonical_match_id"] is not None)
    assert folded["canonical_match_id"] == merged["id"]
    assert folded["classification"] in ("APPROVED", "UNAUTHORIZED")
    # Never a silent pick between incompatible human decisions
    assert merged["classification"] == "UNREVIEWED"
    assert merged["is_new"] == 1 and merged["auto_classified_by_rule_id"] is None
    assert "conflicting decisions" in merged["notes"]
    assert f"APPROVED (photo #{master.id})" in merged["notes"]
    assert f"UNAUTHORIZED (photo #{web.id})" in merged["notes"]
    assert "Licensed to client" in merged["notes"]


def test_fallback_rediscovery_previews_an_available_group_member(client, db_conn, temp_dir: Path):
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    _scan(db_conn, [master.id])

    # Master goes missing; the group is scanned through the variant
    p1.unlink()
    img_repo = ImageRepository(db_conn)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)
    assert not img_repo.get_by_id(master.id).is_present_on_disk
    _scan(db_conn, [web.id])

    review = _group_review(client, web.id)
    assert review
    for m in review:
        assert m["image_id"] == master.id  # provenance unchanged
        assert m["display_image_id"] == web.id  # preview resolves to a present member
        assert m["image_thumbnail_url"] == f"/api/photos/{web.id}/thumbnail"
    single = client.get(f"/api/matches/{review[0]['id']}")
    assert single.status_code == 200
    assert single.json()["display_image_id"] == web.id


def test_selecting_a_missing_group_member_scans_through_an_available_one(db_conn, temp_dir: Path):
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    p1.unlink()
    LibraryIndexer(LibraryRepository(db_conn), ImageRepository(db_conn), ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)

    plan = _scan_engine(db_conn).plan_scan(image_ids=[master.id], provider_override="mock")
    assert [img.id for img in plan.scannable_images] == [web.id]
    assert plan.missing_ids == []
    assert plan.grouped_variant_ids == [master.id]

    # A singleton that is missing is still reported missing
    db_conn.execute("UPDATE images SET photo_group_id = NULL, is_primary_representation = 1")
    db_conn.commit()
    with pytest.raises(ValueError):
        _scan_engine(db_conn).plan_scan(image_ids=[master.id], provider_override="mock")


def test_project_filter_on_discoveries_is_group_aware(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    db_conn.execute("UPDATE images SET project = 'Masters' WHERE id = ?", (master.id,))
    db_conn.execute("UPDATE images SET project = 'Client exports' WHERE id = ?", (web.id,))
    db_conn.commit()
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    _scan(db_conn, [master.id])
    owned = _group_review(client, master.id)
    assert owned

    for project in ("Client exports", "Masters"):
        resp = client.get("/api/matches", params={"project": project, "page_size": 200})
        assert resp.status_code == 200
        body = resp.json()
        ids = [m["id"] for m in body["matches"]]
        assert sorted(ids) == sorted(m["id"] for m in owned), project
        assert body["total"] == len(owned)


def test_exact_duplicate_clusters_produce_linear_candidates(temp_dir: Path):
    db_file = temp_dir / "sha_cluster.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib_id = _make_library(conn, temp_dir)
        ids = [_insert_image(conn, lib_id, i, 0xA5A5_5A5A_0FF0_F00F, sha="same") for i in range(600)]
        conn.commit()
        repo = PhotoGroupRepository(conn)
        pairs, total = repo.find_candidates_page(limit=1000)
        assert total == 599  # N - 1, not N * (N - 1) / 2 = 179,700
        assert all(p.is_exact_duplicate for p in pairs)
        assert {p.image_a.id for p in pairs} | {p.image_b.id for p in pairs} == set(ids)

        # Dismissing a copy's anchor pair falls back to the next anchor
        first = pairs[0]
        repo.dismiss_candidate_pair(first.image_a.id, first.image_b.id)
        pairs, total = repo.find_candidates_page(limit=1000)
        assert total == 599
        assert (first.image_a.id, first.image_b.id) not in {(p.image_a.id, p.image_b.id) for p in pairs}


def test_startup_repairs_group_left_invalid_by_an_interrupted_index(db_path, db_conn, temp_dir: Path):
    from fastapi.testclient import TestClient
    from backend.main import app

    lib_id = _make_library(db_conn, temp_dir)
    a = _insert_image(db_conn, lib_id, 1, 0x1111_2222_3333_4444)
    b = _insert_image(db_conn, lib_id, 2, 0x1111_2222_3333_4445)
    group = PhotoGroupRepository(db_conn).create_group([a, b], preferred_image_id=a)
    # Interrupted pass: the replaced primary was detached and committed, the final repair never ran
    ImageRepository(db_conn).detach_archived_image(a, "/virtual/1.jpg#archived-1")
    db_conn.commit()
    assert db_conn.execute("SELECT preferred_image_id FROM photo_groups WHERE id = ?", (group.id,)).fetchone()[0] == a

    with TestClient(app):
        pass

    assert db_conn.execute("SELECT COUNT(*) FROM photo_groups").fetchone()[0] == 0
    row = db_conn.execute("SELECT photo_group_id, is_primary_representation FROM images WHERE id = ?", (b,)).fetchone()
    assert row["photo_group_id"] is None and row["is_primary_representation"] == 1


def test_reexport_adopting_a_known_missing_record_keeps_lineage(client, db_conn, temp_dir: Path):
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    _scan(db_conn, [master.id])
    before = _group_review(client, master.id)
    assert before
    MatchRepository(db_conn).update_classification_and_notes(before[0]["id"], classification="UNAUTHORIZED", notes="DMCA sent")
    db_conn.commit()

    # A retouched export C of the master was indexed elsewhere earlier, then went missing
    c_path = p1.with_name("multi_retouch.jpg")
    c_path.write_bytes(p1.read_bytes())
    _reexport_edit(c_path)
    img_repo = ImageRepository(db_conn)
    indexer = LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs"))
    indexer.index_library(lib.id)
    c_record = img_repo.get_by_path(str(c_path.resolve()))
    c_bytes = c_path.read_bytes()
    c_path.unlink()
    indexer.index_library(lib.id)

    # The photographer copies C's bytes over the master's file
    time.sleep(0.01)
    p1.write_bytes(c_bytes)
    indexer.index_library(lib.id)

    adopted = img_repo.get_by_path(str(p1.resolve()))
    assert adopted.id == c_record.id  # the known record was reconciled to the path
    refreshed = group_repo.get_group(group.id)
    assert {img.id for img in refreshed.images} == {c_record.id, web.id}
    assert refreshed.preferred_image_id == c_record.id

    after = _group_review(client, web.id)
    assert sorted(_identity(m) for m in after) == sorted(_identity(m) for m in before)
    kept = next(m for m in after if _identity(m) == _identity(before[0]))
    assert kept["classification"] == "UNAUTHORIZED" and kept["notes"] == "DMCA sent"


# --- Follow-up review on 19b39cd: non-destructive folding -----------------------------------------


def _x_rows(conn, master, web):
    rows = _scan_both_ungrouped(conn, master, web)
    x_master = next(r for r in rows if r["image_id"] == master.id)
    x_web = next(r for r in rows if r["image_id"] == web.id and _row_identity(r) == _row_identity(x_master))
    return rows, x_master, x_web


@pytest.mark.parametrize("ungroup", ["remove_from_group", "dissolve_group"])
def test_group_then_ungroup_preserves_each_photos_observations(client, db_conn, temp_dir: Path, ungroup: str):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    rows, x_master, x_web = _x_rows(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED", notes="B's own finding")
    db_conn.commit()
    per_photo_before = {
        img: sorted(_row_identity(r) for r in rows if r["image_id"] == img) for img in (master.id, web.id)
    }

    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    grouped_review = _group_review(client, master.id)
    identities = [_identity(m) for m in grouped_review]
    assert len(identities) == len(set(identities)) == len(per_photo_before[master.id])  # one logical X
    logical_x = next(m for m in grouped_review if _identity(m) == _row_identity(x_master))
    assert logical_x["observation_count"] == 2
    obs = client.get(f"/api/matches/{logical_x['id']}/observations").json()
    assert {o["image_id"] for o in obs} == {master.id, web.id}

    if ungroup == "remove_from_group":
        group_repo.remove_image_from_group(group.id, web.id)
    else:
        group_repo.delete_group(group.id)

    # Each photo again lists every web use its own scans observed, nothing invented or lost
    for img in (master.id, web.id):
        review = _group_review(client, img)
        assert sorted(_identity(m) for m in review) == per_photo_before[img]
        assert all(m["image_id"] == img for m in review)
    restored = next(m for m in _group_review(client, web.id) if _identity(m) == _row_identity(x_web))
    assert restored["id"] == x_web["id"]
    assert restored["classification"] == "UNAUTHORIZED" and restored["notes"] == "B's own finding"
    assert len(_matches_of(db_conn, [master.id, web.id])) == len(rows)
    img_repo = ImageRepository(db_conn)
    assert img_repo.get_by_id(web.id).match_count == len(per_photo_before[web.id])


def test_purging_one_grouped_library_keeps_the_other_members_discoveries(client, db_conn, temp_dir: Path):
    lib_repo = LibraryRepository(db_conn)
    img_repo = ImageRepository(db_conn)
    thumbs = ThumbnailCache(temp_dir / "thumbs")
    dirs = [temp_dir / "lib_one", temp_dir / "lib_two"]
    for d in dirs:
        d.mkdir()
    p1, p2 = dirs[0] / "multi_master.jpg", dirs[1] / "multi_web.jpg"
    _create_sample_image(p1, (120, 90, 60), "Master")
    with Image.open(p1) as img:
        img.resize((170, 170)).save(p2, format="JPEG", quality=84)
    lib_one = lib_repo.create(str(dirs[0]), name="One")
    lib_two = lib_repo.create(str(dirs[1]), name="Two")
    LibraryIndexer(lib_repo, img_repo, thumbs).index_library(lib_one.id)
    LibraryIndexer(lib_repo, img_repo, thumbs).index_library(lib_two.id)
    master = img_repo.get_by_path(str(p1.resolve()))
    web = img_repo.get_by_path(str(p2.resolve()))

    rows, x_master, x_web = _x_rows(db_conn, master, web)
    group = PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    logical_x = next(m for m in _group_review(client, web.id) if _identity(m) == _row_identity(x_master))
    MatchRepository(db_conn).update_classification_and_notes(logical_x["id"], classification="UNAUTHORIZED", notes="Group decision")
    db_conn.commit()
    assert logical_x["image_id"] == master.id  # the logical discovery is held by the purged photo

    lib_repo.purge(lib_one.id)

    assert img_repo.get_by_id(master.id) is None
    remaining = img_repo.get_by_id(web.id)
    assert remaining is not None and remaining.photo_group_id is None
    review = _group_review(client, web.id)
    assert sorted(_identity(m) for m in review) == sorted(_row_identity(r) for r in rows if r["image_id"] == web.id)
    x = next(m for m in review if _identity(m) == _row_identity(x_web))
    assert x["id"] == x_web["id"] and x["image_id"] == web.id  # B's own physical observation survives
    assert x["classification"] == "UNAUTHORIZED" and x["notes"] == "Group decision"  # logical triage handed over
    assert remaining.match_count == len(review)
    assert group.id not in {g.id for g in PhotoGroupRepository(db_conn).list_groups()}


def test_folded_observations_are_read_only_provenance(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    folded_id = next(
        r["id"] for r in _matches_of(db_conn, [master.id, web.id]) if r["canonical_match_id"] is not None
    )
    resp = client.patch(f"/api/matches/{folded_id}", json={"classification": "APPROVED"})
    assert resp.status_code == 409
    # Domain rules and rule cascades touch logical discoveries only
    rule = DomainRuleRepository(db_conn).upsert_rule(x_master["domain"], "IRRELEVANT")
    MatchRepository(db_conn).apply_rule_to_unreviewed_matches(rule.domain, "IRRELEVANT", rule_id=rule.id)
    folded = db_conn.execute("SELECT classification FROM matches WHERE id = ?", (folded_id,)).fetchone()
    assert folded["classification"] == "UNREVIEWED"


def test_rescan_through_a_member_with_a_folded_observation_updates_the_logical_discovery(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    rows, x_master, x_web = _x_rows(db_conn, master, web)
    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    group_repo.set_preferred_image(group.id, web.id)
    _scan(db_conn, [web.id])
    assert len(_matches_of(db_conn, [master.id, web.id])) == len(rows)  # no new rows
    review = _group_review(client, web.id)
    identities = [_identity(m) for m in review]
    assert len(identities) == len(set(identities)) == len(rows) // 2


# --- Follow-up review on c84891f: physical observation on first group rediscovery, original triage ---


def _two_library_pair(conn, temp_dir: Path):
    lib_repo = LibraryRepository(conn)
    img_repo = ImageRepository(conn)
    thumbs = ThumbnailCache(temp_dir / "thumbs")
    dirs = [temp_dir / "lib_a", temp_dir / "lib_b"]
    for d in dirs:
        d.mkdir()
    p1, p2 = dirs[0] / "multi_master.jpg", dirs[1] / "multi_web.jpg"
    _create_sample_image(p1, (120, 90, 60), "Master")
    with Image.open(p1) as img:
        img.resize((170, 170)).save(p2, format="JPEG", quality=84)
    lib_a = lib_repo.create(str(dirs[0]), name="A")
    lib_b = lib_repo.create(str(dirs[1]), name="B")
    LibraryIndexer(lib_repo, img_repo, thumbs).index_library(lib_a.id)
    LibraryIndexer(lib_repo, img_repo, thumbs).index_library(lib_b.id)
    return lib_a, lib_b, img_repo.get_by_path(str(p1.resolve())), img_repo.get_by_path(str(p2.resolve()))


def test_first_rediscovery_through_a_group_member_records_its_own_observation(client, db_conn, temp_dir: Path):
    lib_a, _lib_b, master, web = _two_library_pair(db_conn, temp_dir)
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    _scan(db_conn, [master.id])
    a_rows = _matches_of(db_conn, [master.id])
    assert a_rows and _matches_of(db_conn, [web.id]) == []  # B has never observed anything

    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    group_repo.set_preferred_image(group.id, web.id)
    _scan(db_conn, [web.id])

    review = _group_review(client, web.id)
    identities = [_identity(m) for m in review]
    assert len(identities) == len(set(identities)) == len(a_rows)  # one logical discovery each
    b_rows = _matches_of(db_conn, [web.id])
    assert sorted(_row_identity(r) for r in b_rows) == sorted(_row_identity(r) for r in a_rows)
    logical_ids = {m["id"] for m in review}
    assert all(r["canonical_match_id"] in logical_ids for r in b_rows)  # folded under logical X
    assert all(r["fold_kind"] == "GROUP" for r in b_rows)
    assert all(m["observation_count"] == 2 for m in review)
    assert ImageRepository(db_conn).get_by_id(web.id).match_count == 0  # folded rows are not counted twice

    # Purging A's library keeps X through B's own observation
    LibraryRepository(db_conn).purge(lib_a.id)
    review = _group_review(client, web.id)
    assert sorted(_identity(m) for m in review) == sorted(_row_identity(r) for r in a_rows)
    assert {m["id"] for m in review} == {r["id"] for r in b_rows}  # B's observations became the discoveries
    assert ImageRepository(db_conn).get_by_id(web.id).match_count == len(review)


def test_canonical_observation_keeps_its_own_original_triage(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(x_master["id"], classification="APPROVED", notes="Licensed")
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED", notes="Stolen")
    db_conn.commit()

    group = PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    logical = next(m for m in _group_review(client, master.id) if _identity(m) == _row_identity(x_master))
    assert logical["classification"] == "UNREVIEWED"  # conflict -> explicit re-review

    observations = {o["image_id"]: o for o in client.get(f"/api/matches/{logical['id']}/observations").json()}
    assert observations[master.id]["observed_classification"] == "APPROVED"
    assert observations[master.id]["observed_notes"] == "Licensed"
    assert observations[web.id]["observed_classification"] == "UNAUTHORIZED"
    assert observations[web.id]["observed_notes"] == "Stolen"

    # Dissolving the group: the folded observation returns to its own decision; the canonical row
    # keeps exposing its own original decision as provenance
    PhotoGroupRepository(db_conn).delete_group(group.id)
    b_x = next(m for m in _group_review(client, web.id) if _identity(m) == _row_identity(x_web))
    assert b_x["classification"] == "UNAUTHORIZED" and b_x["observed_classification"] == "UNAUTHORIZED"
    a_x = next(m for m in _group_review(client, master.id) if _identity(m) == _row_identity(x_master))
    assert a_x["observed_classification"] == "APPROVED" and a_x["observed_notes"] == "Licensed"


# --- Audit of c84891f: group-first scans, persistent conflicts, active preview, perceptual work ---


def test_grouped_scan_of_new_representative_retains_physical_observation(client, db_conn, temp_dir: Path):
    lib_a, _lib_b, master, web = _two_library_pair(db_conn, temp_dir)
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)  # grouped before any scan
    _scan(db_conn, [master.id])
    group_repo.set_preferred_image(group.id, web.id)
    _scan(db_conn, [web.id])

    a_rows, b_rows = _matches_of(db_conn, [master.id]), _matches_of(db_conn, [web.id])
    assert a_rows and sorted(_row_identity(r) for r in b_rows) == sorted(_row_identity(r) for r in a_rows)
    total_before = len(_group_review(client, web.id))
    LibraryRepository(db_conn).purge(lib_a.id)
    assert len(_group_review(client, web.id)) == total_before == len(a_rows)


def test_joining_third_photo_cannot_silently_resolve_existing_conflict(client, db_conn, temp_dir: Path):
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    p3 = p1.with_name("multi_third.jpg")
    with Image.open(p1) as img:
        img.resize((160, 160)).save(p3, format="JPEG", quality=84)
    img_repo = ImageRepository(db_conn)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)
    third = img_repo.get_by_path(str(p3.resolve()))
    _assert_provider_returns_same_discoveries(master.file_path, third.file_path)
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    _scan(db_conn, [third.id])
    x_third = next(r for r in _matches_of(db_conn, [third.id]) if _row_identity(r) == _row_identity(x_master))

    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(x_master["id"], classification="APPROVED")
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED")
    match_repo.update_classification_and_notes(x_third["id"], classification="APPROVED")
    db_conn.commit()

    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)

    def logical_x():
        return next(m for m in _group_review(client, master.id) if _identity(m) == _row_identity(x_master))

    assert logical_x()["classification"] == "UNREVIEWED" and logical_x()["triage_conflict"] is True
    group_repo.add_image_to_group(group.id, third.id)
    assert logical_x()["classification"] == "UNREVIEWED"  # not silently resolved by C's APPROVED
    assert logical_x()["triage_conflict"] is True
    assert logical_x()["observation_count"] == 3

    # Domain rules never auto-resolve an open conflict
    rule = DomainRuleRepository(db_conn).upsert_rule(x_master["domain"], "IRRELEVANT")
    match_repo.apply_rule_to_unreviewed_matches(rule.domain, "IRRELEVANT", rule_id=rule.id)
    assert logical_x()["classification"] == "UNREVIEWED"

    # Only an explicit decision resolves it; later merges then use that decision
    resp = client.patch(f"/api/matches/{logical_x()['id']}", json={"classification": "UNAUTHORIZED"})
    assert resp.status_code == 200
    assert logical_x()["classification"] == "UNAUTHORIZED" and logical_x()["triage_conflict"] is False


def test_canonical_original_decision_remains_inspectable_after_conflict(client, db_conn, temp_dir: Path):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    approved = match_repo.update_classification_and_notes(x_master["id"], classification="APPROVED")
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED")
    db_conn.commit()
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    logical = next(m for m in _group_review(client, master.id) if _identity(m) == _row_identity(x_master))
    assert logical["classified_at"] is None  # logical state requires review
    obs = {o["image_id"]: o for o in client.get(f"/api/matches/{logical['id']}/observations").json()}
    assert obs[master.id]["observed_classification"] == "APPROVED"
    assert obs[master.id]["observed_classified_at"] == approved.classified_at
    assert obs[master.id]["observed_rule_id"] is None
    assert obs[web.id]["observed_classification"] == "UNAUTHORIZED"


def test_preview_of_active_member_avoids_archived_group_owner(client, db_conn, temp_dir: Path):
    lib_a, _lib_b, master, web = _two_library_pair(db_conn, temp_dir)
    _assert_provider_returns_same_discoveries(master.file_path, web.file_path)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    _scan(db_conn, [master.id])
    LibraryRepository(db_conn).archive(lib_a.id)
    _scan(db_conn, [web.id])

    review = _group_review(client, web.id)
    assert review
    for m in review:
        assert m["display_image_id"] == web.id
    assert client.get(f"/api/photos/{review[0]['display_image_id']}/file").status_code == 200


def test_perceptual_pass_work_is_linear_in_duplicate_and_grouped_clusters(temp_dir: Path):
    db_file = temp_dir / "work.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib_id = _make_library(conn, temp_dir)
        value = 0xA5A5_5A5A_0FF0_F00F
        for i in range(1000):  # byte-identical copies with an identical informative dHash
            _insert_image(conn, lib_id, i, value, sha="same")
        conn.commit()
        repo = PhotoGroupRepository(conn)
        _pairs, total = repo.find_candidates_page(limit=10)
        assert total == 999
        assert repo.last_candidate_comparisons == 0  # 11 * n * (n - 1) / 2 = 5,494,500 before

        # 300 near-identical photos already in one group plus one loose variant
        db2 = temp_dir / "work2.sqlite"
        init_db(db2)
    with get_db(db2) as conn:
        lib_id = _make_library(conn, temp_dir, name="lib2")
        ids = [_insert_image(conn, lib_id, i, value ^ (i % 3)) for i in range(300)]
        conn.commit()
        repo = PhotoGroupRepository(conn)
        repo.create_group(ids)
        loose = _insert_image(conn, lib_id, 999, value ^ 0b1000)
        conn.commit()
        pairs, total = repo.find_candidates_page(limit=1000)
        # The loose photo gets at most MAX_CANDIDATES_PER_PHOTO candidates (one suffices to join)
        assert 1 <= total <= MAX_CANDIDATES_PER_PHOTO
        assert all(loose in (p.image_a.id, p.image_b.id) for p in pairs)
        assert repo.last_candidates_truncated is True
        assert repo.last_candidate_comparisons <= 11 * 300  # grouped x grouped pairs are never compared


# --- Triage restoration on group dissolution (owner's decision on 6a59c22) ---


def _triaged_pair(client, db_conn, temp_dir, a_class, a_notes, b_class, b_notes):
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(x_master["id"], classification=a_class, notes=a_notes)
    match_repo.update_classification_and_notes(x_web["id"], classification=b_class, notes=b_notes)
    db_conn.commit()
    group = PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)

    def x_of(image_id, x_row):
        return next(m for m in _group_review(client, image_id) if _identity(m) == _row_identity(x_row))

    return master, web, x_master, x_web, group, x_of


def test_dissolving_without_explicit_review_restores_original_triage(client, db_conn, temp_dir: Path):
    master, web, x_master, x_web, group, x_of = _triaged_pair(
        client, db_conn, temp_dir, "APPROVED", "A note", "UNAUTHORIZED", "B note"
    )
    logical = x_of(master.id, x_master)
    assert logical["classification"] == "UNREVIEWED" and logical["triage_conflict"] is True
    assert logical["explicit_review_at"] is None  # automatic coalescence is not a review

    PhotoGroupRepository(db_conn).delete_group(group.id)
    a_x, b_x = x_of(master.id, x_master), x_of(web.id, x_web)
    assert (a_x["classification"], a_x["notes"]) == ("APPROVED", "A note")
    assert (b_x["classification"], b_x["notes"]) == ("UNAUTHORIZED", "B note")
    assert a_x["triage_conflict"] is False
    assert ImageRepository(db_conn).get_by_id(master.id).unreviewed_count == len(_group_review(client, master.id)) - 1


def test_dissolving_after_explicit_review_keeps_the_groups_decision(client, db_conn, temp_dir: Path):
    master, web, x_master, x_web, group, x_of = _triaged_pair(
        client, db_conn, temp_dir, "APPROVED", "A note", "UNAUTHORIZED", "B note"
    )
    logical = x_of(master.id, x_master)
    resp = client.patch(f"/api/matches/{logical['id']}", json={"classification": "IRRELEVANT"})
    assert resp.status_code == 200 and resp.json()["explicit_review_at"]

    PhotoGroupRepository(db_conn).delete_group(group.id)
    a_x, b_x = x_of(master.id, x_master), x_of(web.id, x_web)
    assert a_x["classification"] == "IRRELEVANT"  # the explicit group decision stays
    assert a_x["observed_classification"] == "APPROVED" and a_x["observed_notes"] == "A note"  # provenance kept
    assert (b_x["classification"], b_x["notes"]) == ("UNAUTHORIZED", "B note")


@pytest.mark.parametrize("explicit", [False, True])
def test_explicit_review_selecting_the_unchanged_classification_counts(client, db_conn, temp_dir: Path, explicit: bool):
    master, web, x_master, x_web, group, x_of = _triaged_pair(
        client, db_conn, temp_dir, "APPROVED", "A note", "APPROVED", "B note"
    )
    logical = x_of(master.id, x_master)
    assert logical["classification"] == "APPROVED" and "B note" in logical["notes"]  # merged automatically
    if explicit:
        resp = client.patch(f"/api/matches/{logical['id']}", json={"classification": "APPROVED"})
        assert resp.status_code == 200

    PhotoGroupRepository(db_conn).delete_group(group.id)
    a_x = x_of(master.id, x_master)
    assert a_x["classification"] == "APPROVED"
    assert a_x["observed_notes"] == "A note"
    if explicit:
        # Same value, but an explicit review: the group's discovery (merged notes) stays as decided
        assert "B note" in a_x["notes"]
    else:
        # No review since the merge: back to the photo's own original state
        assert a_x["notes"] == "A note"


def test_automatic_merges_never_advance_the_explicit_review_marker(client, db_conn, temp_dir: Path):
    master, web, x_master, _x_web, group, x_of = _triaged_pair(
        client, db_conn, temp_dir, "APPROVED", None, "APPROVED", None
    )
    logical = x_of(master.id, x_master)
    before = logical["explicit_review_at"]
    # Pre-group reviews happened before the merge: they do not count as a review of the group
    row = db_conn.execute(
        "SELECT explicit_review_at, merged_at FROM matches WHERE id = ?", (logical["id"],)
    ).fetchone()
    assert row["explicit_review_at"] < row["merged_at"]
    PhotoGroupRepository(db_conn).remove_image_from_group(group.id, web.id)
    assert x_of(master.id, x_master)["explicit_review_at"] in (None, before)


# --- Multi-agent audit of 1b5a627 ---


def test_dense_burst_cluster_work_and_memory_are_bounded(temp_dir: Path):
    """10,000 distinct burst frames, all within the threshold of each other (PERF-01)."""
    db_file = temp_dir / "burst.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib_id = _make_library(conn, temp_dir)
        base = 0xA5A5_5A5A_0FF0_F00F
        rng = random.Random(3)
        n = 10_000
        for i in range(n):
            value = base
            for bit in rng.sample(range(64), 3):
                value ^= 1 << bit
            _insert_image(conn, lib_id, i, value)  # unique SHA per frame
        conn.commit()
        repo = PhotoGroupRepository(conn)
        started = time.time()
        _pairs, total = repo.find_candidates_page(limit=50)
        elapsed = time.time() - started
        assert total <= n * MAX_CANDIDATES_PER_PHOTO // 2 + n  # linear, not n^2 / 2 ~ 50M pairs
        assert repo.last_candidate_comparisons <= 11 * n * MAX_CANDIDATES_PER_PHOTO * 4
        assert repo.last_candidates_truncated is True
        assert elapsed < 30


def test_candidate_pagination_offset(client, db_conn, temp_dir: Path):
    lib_id = _make_library(db_conn, temp_dir)
    for i in range(6):
        _insert_image(db_conn, lib_id, i, 0xA5A5_5A5A_0FF0_F00F, sha="same")
    db_conn.commit()
    first = client.get("/api/groups/candidates", params={"limit": 3}).json()
    second = client.get("/api/groups/candidates", params={"limit": 3, "offset": 3}).json()
    assert first["total"] == second["total"] == 5
    ids_first = {(p["image_a"]["id"], p["image_b"]["id"]) for p in first["pairs"]}
    ids_second = {(p["image_a"]["id"], p["image_b"]["id"]) for p in second["pairs"]}
    assert len(ids_first) == 3 and len(ids_second) == 2 and not ids_first & ids_second
    assert first["truncated"] is False


def test_purging_canonical_keeps_pre_group_human_triage(client, db_conn, temp_dir: Path):
    """DATA-01: A/X explicitly APPROVED before grouping, B observed X; purging A must not let a
    later dissolution restore B's own UNREVIEWED state over the inherited decision."""
    lib_a, _lib_b, master, web = _two_library_pair(db_conn, temp_dir)
    rows, x_master, x_web = _x_rows(db_conn, master, web)
    MatchRepository(db_conn).update_classification_and_notes(
        x_master["id"], classification="APPROVED", notes="Client sous licence"
    )
    db_conn.commit()
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)

    LibraryRepository(db_conn).purge(lib_a.id)  # group dissolves: B is alone

    x = next(m for m in _group_review(client, web.id) if _identity(m) == _row_identity(x_master))
    assert x["image_id"] == web.id
    assert x["classification"] == "APPROVED" and x["notes"] == "Client sous licence"
    assert x["inherited_from"] and f"photo #{master.id}" in x["inherited_from"]
    assert x["observed_classification"] == "UNREVIEWED"  # B's own observation remains provenance


def test_purging_the_only_searched_member_keeps_the_groups_discoveries(client, db_conn, temp_dir: Path):
    """DATA-02: the group was searched only through A; purging A's library keeps the group's
    discoveries with the surviving member, with inheritance provenance."""
    lib_a, _lib_b, master, web = _two_library_pair(db_conn, temp_dir)
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    _scan(db_conn, [master.id])
    a_rows = _matches_of(db_conn, [master.id])
    assert a_rows and _matches_of(db_conn, [web.id]) == []
    MatchRepository(db_conn).update_classification_and_notes(a_rows[0]["id"], classification="UNAUTHORIZED")
    db_conn.commit()

    LibraryRepository(db_conn).purge(lib_a.id)

    review = _group_review(client, web.id)
    assert sorted(_identity(m) for m in review) == sorted(_row_identity(r) for r in a_rows)
    assert all(m["image_id"] == web.id and f"photo #{master.id}" in (m["inherited_from"] or "") for m in review)
    kept = next(m for m in review if m["id"] == a_rows[0]["id"])
    assert kept["classification"] == "UNAUTHORIZED"
    assert ImageRepository(db_conn).get_by_id(web.id).match_count == len(review)


def test_repeated_conflicts_keep_a_single_banner(client, db_conn, temp_dir: Path):
    """DATA-03: adding further reviewed photos updates one conflict banner instead of stacking."""
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    p3 = p1.with_name("multi_third.jpg")
    with Image.open(p1) as img:
        img.resize((160, 160)).save(p3, format="JPEG", quality=84)
    img_repo = ImageRepository(db_conn)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)
    third = img_repo.get_by_path(str(p3.resolve()))
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    _scan(db_conn, [third.id])
    x_third = next(r for r in _matches_of(db_conn, [third.id]) if _row_identity(r) == _row_identity(x_master))
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(x_master["id"], classification="APPROVED")
    match_repo.update_classification_and_notes(x_web["id"], classification="UNAUTHORIZED")
    match_repo.update_classification_and_notes(x_third["id"], classification="IRRELEVANT")
    db_conn.commit()
    group_repo = PhotoGroupRepository(db_conn)
    group = group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    group_repo.add_image_to_group(group.id, third.id)

    logical = next(m for m in _group_review(client, master.id) if _identity(m) == _row_identity(x_master))
    assert logical["notes"].count("[Merged discovery: conflicting decisions]") == 1
    for decision in (f"APPROVED (photo #{master.id})", f"UNAUTHORIZED (photo #{web.id})", f"IRRELEVANT (photo #{third.id})"):
        assert decision in logical["notes"]


def test_photo_grouped_during_an_active_scan_is_not_searched_twice(db_conn, temp_dir: Path):
    """COST-01: a photo whose group was already searched in the running session is skipped."""
    _lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    engine = _scan_engine(db_conn)
    calls: list[str] = []
    from backend.providers.mock_provider import MockSearchProvider

    original_search = MockSearchProvider.search

    def counting_search(self, image_path, **kwargs):
        calls.append(Path(image_path).name)
        if len(calls) == 1:
            # The user groups both photos while the first one is being searched
            side = get_connection_for(db_conn)
            PhotoGroupRepository(side).create_group([master.id, web.id], preferred_image_id=master.id)
            side.close()
        return original_search(self, image_path, **kwargs)

    import backend.providers.mock_provider as mock_module
    mock_module.MockSearchProvider.search = counting_search
    try:
        session = engine.start_background_scan(image_ids=[master.id, web.id], provider_override="mock")
        _wait_for_scan(session.id)
    finally:
        mock_module.MockSearchProvider.search = original_search
    db_conn.commit()
    assert calls == [Path(master.file_path).name]
    items = db_conn.execute(
        "SELECT image_id, status FROM scan_items WHERE scan_session_id = ? ORDER BY id", (session.id,)
    ).fetchall()
    assert [(r["image_id"], r["status"]) for r in items] == [(master.id, "SUCCESS"), (web.id, "SKIPPED")]
    assert UsageRepository(db_conn).get_scan_session(session.id).failed_images == 0


def get_connection_for(conn):
    from backend.database import get_connection

    path = conn.execute("PRAGMA database_list").fetchall()[0][2]
    return get_connection(path)


def test_grouping_keeps_a_scan_under_the_free_tier_guard(db_conn, temp_dir: Path):
    """COST-02: the free-tier guard counts one search per group."""
    lib, master, web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    settings_repo = SettingsRepository(db_conn)
    usage_repo = UsageRepository(db_conn)
    from backend.repositories.usage_repo import get_current_billing_period

    allowance = settings_repo.get_app_settings().free_tier_monthly_units
    usage_repo.record_call(
        provider="google_vision", billing_period=get_current_billing_period(), scan_session_id=None,
        image_id=None, attempted_units=allowance - 1, successful_units=allowance - 1, failed_units=0,
        request_status="SUCCESS", estimated_cost=0.0,
    )
    db_conn.commit()
    engine = _scan_engine(db_conn)
    with pytest.raises(ValueError, match="free tier"):
        engine.plan_scan(image_ids=[master.id, web.id], provider_override="google_vision")
    PhotoGroupRepository(db_conn).create_group([master.id, web.id], preferred_image_id=master.id)
    plan = engine.plan_scan(image_ids=[master.id, web.id], provider_override="google_vision")
    assert [img.id for img in plan.scannable_images] == [master.id]


def test_transparent_cutouts_hash_identically_whatever_hidden_rgb(temp_dir: Path):
    """ALGO-01: two exports of one cut-out whose fully transparent pixels store different RGB."""
    from PIL import ImageDraw

    def cutout(path: Path, hidden: tuple[int, int, int]) -> None:
        img = Image.new("RGBA", (240, 200), hidden + (0,))
        draw = ImageDraw.Draw(img)
        rng = random.Random(11)
        for _ in range(25):
            x0, y0 = rng.randrange(40, 160), rng.randrange(30, 130)
            draw.ellipse((x0, y0, x0 + rng.randrange(20, 60), y0 + rng.randrange(20, 60)),
                         fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256), 255))
        img.save(path, format="PNG")

    black, white = temp_dir / "cut_black.png", temp_dir / "cut_white.png"
    cutout(black, (0, 0, 0))
    cutout(white, (255, 255, 255))
    h_black, h_white = compute_dhash(black), compute_dhash(white)
    assert h_black == h_white
    assert is_candidate_representation(h_black, h_white)


def test_cold_thumbnail_generation_requires_an_active_library(client, db_conn, temp_dir: Path):
    """SEC-01: a missing thumbnail is only generated for photos inside an active library."""
    lib, master, _web, _p1, _p2 = _indexed_pair(db_conn, temp_dir)
    thumbs = ThumbnailCache(temp_dir / "thumbs")
    LibraryRepository(db_conn).archive(lib.id)
    for path in (temp_dir / "thumbs").rglob("*.webp"):
        path.unlink()
    assert not thumbs.get_thumbnail_path(master.sha256).is_file()
    resp = client.get(f"/api/photos/{master.id}/thumbnail")
    assert resp.status_code == 403
    assert not thumbs.get_thumbnail_path(master.sha256).is_file()


def test_creating_a_library_invalidates_the_candidate_cache(temp_dir: Path):
    """CACHE-01: migration 015 adds the library insert trigger."""
    db_file = temp_dir / "lib_trigger.sqlite"
    assert 15 in init_db(db_file)
    with get_db(db_file) as conn:
        before = conn.execute("SELECT generation FROM group_candidate_state").fetchone()[0]
        _make_library(conn, temp_dir, name="fresh")
        assert conn.execute("SELECT generation FROM group_candidate_state").fetchone()[0] == before + 1


@pytest.mark.parametrize("n_entries", [200, 3_000])  # small-bucket fast path and scan path
def test_comparison_budget_is_a_hard_ceiling_in_false_positive_buckets(temp_dir: Path, monkeypatch, n_entries: int):
    """Hashes sharing one pigeonhole band but mostly beyond the threshold never saturate the
    per-photo cap: the comparison budget alone must stop the bucket walk."""
    import backend.repositories.group_repo as group_repo_module

    budget = 1_000
    monkeypatch.setattr(group_repo_module, "CANDIDATE_COMPARISON_BUDGET", budget)
    db_file = temp_dir / "false_positive.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        lib_id = _make_library(conn, temp_dir)
        rng = random.Random(5)
        for i in range(n_entries):
            # Same low 16 bits (the first bands), random high bits: ~24 bits apart on average
            _insert_image(conn, lib_id, i, (rng.getrandbits(48) << 16) | 0x5A3C)
        conn.commit()
        repo = PhotoGroupRepository(conn)
        repo.find_candidates_page(limit=50)
        assert repo.last_candidates_truncated is True
        assert repo.last_candidate_comparisons <= budget
        assert repo.last_candidate_comparisons < n_entries * (n_entries - 1) // 2


def test_inherited_triage_survives_regroup_then_ungroup_as_a_folded_observation(client, db_conn, temp_dir: Path):
    """A/X APPROVED, B/X UNREVIEWED; group A+B, purge A: B inherits APPROVED. Grouping B with C
    (earlier X, so C's discovery becomes canonical and B's is folded) then dissolving must not
    restore B's own pre-inheritance observation over the inherited decision."""
    lib_a, lib_b, master, web = _two_library_pair(db_conn, temp_dir)
    _rows, x_master, x_web = _x_rows(db_conn, master, web)
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(x_master["id"], classification="APPROVED")
    db_conn.commit()
    group_repo = PhotoGroupRepository(db_conn)
    group_repo.create_group([master.id, web.id], preferred_image_id=master.id)
    LibraryRepository(db_conn).purge(lib_a.id)

    b_x = db_conn.execute("SELECT * FROM matches WHERE id = ?", (x_web["id"],)).fetchone()
    assert b_x["classification"] == "APPROVED" and b_x["inherited_at"] is not None

    # C observed X earlier than B
    c_id = _insert_image(db_conn, lib_b.id, 9_001, int(web.dhash, 16))
    columns = [k for k in b_x.keys() if k != "id"]
    c_row = dict(b_x)
    c_row.update(
        image_id=c_id, first_seen_at="2000-01-01T00:00:00+00:00", classification="UNREVIEWED",
        classified_at=None, notes=None, canonical_match_id=None, fold_kind=None, folded_at=None,
        inherited_at=None, inherited_from=None, merged_at=None, explicit_review_at=None,
        obs_classification=None, obs_classified_at=None, obs_rule_id=None, obs_notes=None,
        obs_is_new=None, obs_acknowledged_at=None, obs_captured_at=None, triage_conflict=0,
    )
    db_conn.execute(
        f"INSERT INTO matches ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(c_row[k] for k in columns),
    )
    db_conn.commit()
    group = group_repo.create_group([web.id, c_id], preferred_image_id=web.id)
    b_x = db_conn.execute("SELECT * FROM matches WHERE id = ?", (x_web["id"],)).fetchone()
    assert b_x["canonical_match_id"] is not None  # B's discovery is now a folded observation

    group_repo.delete_group(group.id)

    x = next(m for m in _group_review(client, web.id) if _identity(m) == _row_identity(x_web))
    assert x["id"] == x_web["id"]
    assert x["classification"] == "APPROVED"
    assert x["inherited_from"] and f"photo #{master.id}" in x["inherited_from"]
    assert x["observed_classification"] == "UNREVIEWED"


def test_photo_grouped_after_an_earlier_search_in_the_same_scan_is_not_searched_again(db_conn, temp_dir: Path):
    """A completes while ungrouped, the user then groups A+B before the worker reaches B."""
    lib, master, web, p1, _p2 = _indexed_pair(db_conn, temp_dir)
    filler_path = p1.with_name("filler.jpg")
    _create_sample_image(filler_path, (30, 140, 200), "Filler")
    img_repo = ImageRepository(db_conn)
    LibraryIndexer(LibraryRepository(db_conn), img_repo, ThumbnailCache(temp_dir / "thumbs")).index_library(lib.id)
    filler = img_repo.get_by_path(str(filler_path.resolve()))
    engine = _scan_engine(db_conn)
    calls: list[str] = []
    from backend.providers.mock_provider import MockSearchProvider

    original_search = MockSearchProvider.search

    def counting_search(self, image_path, **kwargs):
        calls.append(Path(image_path).name)
        if Path(image_path).name == filler_path.name:
            # A was searched (and recorded) while ungrouped; the user groups A+B now
            side = get_connection_for(db_conn)
            PhotoGroupRepository(side).create_group([master.id, web.id], preferred_image_id=master.id)
            side.close()
        return original_search(self, image_path, **kwargs)

    import backend.providers.mock_provider as mock_module
    mock_module.MockSearchProvider.search = counting_search
    try:
        session = engine.start_background_scan(image_ids=[master.id, filler.id, web.id], provider_override="mock")
        _wait_for_scan(session.id)
    finally:
        mock_module.MockSearchProvider.search = original_search
    db_conn.commit()
    assert Path(web.file_path).name not in calls
    items = {
        r["image_id"]: r["status"]
        for r in db_conn.execute("SELECT image_id, status FROM scan_items WHERE scan_session_id = ?", (session.id,))
    }
    assert items == {master.id: "SUCCESS", filler.id: "SUCCESS", web.id: "SKIPPED"}


def _shared_observation(conn, image_id: int) -> int:
    row, _ = MatchRepository(conn).upsert_match(
        image_id=image_id, scan_session_id=None, domain="audit.example",
        match_type="FULL", provider="mock", source_kind="PAGE",
        page_url="https://audit.example/shared", candidate_image_url="https://audit.example/shared.jpg",
    )
    conn.commit()
    return row.id


def _match_row(conn, match_id: int):
    return conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()


def test_latest_explicit_decision_survives_a_second_group_cycle(db_conn, temp_dir: Path):
    """Each grouping cycle rolls back to the state right before that cycle, never to the first
    cycle's snapshot; the original observation stays available as provenance."""
    lib = _make_library(db_conn, temp_dir)
    a = _insert_image(db_conn, lib, 1, 0xA5A55A5A0FF0F00F)
    b = _insert_image(db_conn, lib, 2, 0xA5A55A5A0FF0F00F)
    ma, mb = _shared_observation(db_conn, a), _shared_observation(db_conn, b)
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(ma, classification="APPROVED", notes="original")
    match_repo.update_classification_and_notes(mb, classification="UNAUTHORIZED")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    first = repo.create_group([a, b], preferred_image_id=a)
    match_repo.update_classification_and_notes(ma, classification="IRRELEVANT", notes="latest human review")
    db_conn.commit()
    repo.delete_group(first.id)
    assert _match_row(db_conn, ma)["classification"] == "IRRELEVANT"

    second = repo.create_group([a, b], preferred_image_id=a)
    assert _match_row(db_conn, ma)["classification"] == "UNREVIEWED"  # new conflict
    repo.delete_group(second.id)  # no human review during the second cycle

    row = _match_row(db_conn, ma)
    assert row["classification"] == "IRRELEVANT" and row["notes"] == "latest human review"
    assert row["obs_classification"] == "APPROVED" and row["obs_notes"] == "original"  # provenance
    assert _match_row(db_conn, mb)["classification"] == "UNAUTHORIZED"


def test_inherited_decision_travels_through_a_later_ordinary_handover(db_conn, temp_dir: Path):
    libs = [_make_library(db_conn, temp_dir, name=f"lib{i}") for i in range(4)]
    ids = [_insert_image(db_conn, lib, i, 0xA5A55A5A0FF0F00F) for i, lib in enumerate(libs)]
    matches = [_shared_observation(db_conn, i) for i in ids]
    MatchRepository(db_conn).update_classification_and_notes(
        matches[0], classification="APPROVED", notes="licensed client"
    )
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group(ids, preferred_image_id=ids[0])
    LibraryRepository(db_conn).purge(libs[0])
    inherited = _match_row(db_conn, matches[1])
    assert inherited["classification"] == "APPROVED" and inherited["inherited_at"]

    repo.remove_image_from_group(group.id, ids[1])  # ordinary handover from B to C
    promoted = _match_row(db_conn, matches[2])
    assert promoted["classification"] == "APPROVED"
    assert promoted["inherited_at"] and f"photo #{ids[0]}" in promoted["inherited_from"]

    LibraryRepository(db_conn).purge(libs[1])
    repo.delete_group(group.id)
    kept = _match_row(db_conn, matches[2])
    assert kept["classification"] == "APPROVED" and "licensed client" in (kept["notes"] or "")
    assert f"photo #{ids[0]}" in kept["inherited_from"]


@pytest.mark.parametrize("n,budget", [(400, 1_000), (10_000, 20_000_000)])
def test_candidate_budget_applies_inside_a_bucket(db_conn, temp_dir: Path, monkeypatch, n: int, budget: int):
    """Codex reproduction: the first six-bit band collides, the rest is unrelated."""
    import backend.repositories.group_repo as group_repo_module

    lib = _make_library(db_conn, temp_dir)
    rng = random.Random(721)
    for i in range(n):
        _insert_image(db_conn, lib, i, rng.getrandbits(58) << 6)
    db_conn.commit()
    monkeypatch.setattr(group_repo_module, "CANDIDATE_COMPARISON_BUDGET", budget)
    repo = PhotoGroupRepository(db_conn)
    repo.find_candidates_page(threshold=10, limit=50)
    assert repo.last_candidates_truncated
    assert repo.last_candidate_comparisons <= budget


def test_successive_purges_keep_every_original_purged_source(db_conn, temp_dir: Path):
    libs = [_make_library(db_conn, temp_dir, name=f"lib{i}") for i in range(3)]
    ids = [_insert_image(db_conn, lib, i, 0xA5A55A5A0FF0F00F) for i, lib in enumerate(libs)]
    matches = [_shared_observation(db_conn, i) for i in ids]
    MatchRepository(db_conn).update_classification_and_notes(matches[0], classification="APPROVED")
    db_conn.commit()
    group = PhotoGroupRepository(db_conn).create_group(ids, preferred_image_id=ids[0])
    LibraryRepository(db_conn).purge(libs[0])  # A -> B
    LibraryRepository(db_conn).purge(libs[1])  # B (carrying A's decision) -> C
    kept = _match_row(db_conn, matches[2])
    assert kept["classification"] == "APPROVED" and kept["canonical_match_id"] is None
    assert f"photo #{ids[0]}" in kept["inherited_from"] and f"photo #{ids[1]}" in kept["inherited_from"]
    repo = PhotoGroupRepository(db_conn)
    if repo.get_group(group.id):  # a single surviving member may already have dissolved it
        repo.delete_group(group.id)
    assert _match_row(db_conn, matches[2])["classification"] == "APPROVED"


def _inherited_carrier(db_conn, temp_dir: Path):
    """A/X APPROVED "licensed client", B/X UNREVIEWED; group A+B, purge A: B carries A's decision."""
    lib_a = _make_library(db_conn, temp_dir, name="purged")
    lib_b = _make_library(db_conn, temp_dir, name="kept")
    a = _insert_image(db_conn, lib_a, 1, 0xA5A55A5A0FF0F00F)
    b = _insert_image(db_conn, lib_b, 2, 0xA5A55A5A0FF0F00F)
    ma, mb = _shared_observation(db_conn, a), _shared_observation(db_conn, b)
    MatchRepository(db_conn).update_classification_and_notes(ma, classification="APPROVED", notes="licensed client")
    db_conn.commit()
    PhotoGroupRepository(db_conn).create_group([a, b], preferred_image_id=a)
    LibraryRepository(db_conn).purge(lib_a)
    row = _match_row(db_conn, mb)
    assert row["classification"] == "APPROVED" and f"photo #{a}" in row["inherited_from"]
    return lib_b, a, b, mb


def test_pre_cycle_inheritance_rolls_back_with_a_later_reversible_group(db_conn, temp_dir: Path):
    """The inherited carrier stays canonical in a later conflicting group; dissolving it without
    review restores the inherited decision it had before that cycle."""
    lib_b, a, b, mb = _inherited_carrier(db_conn, temp_dir)
    c = _insert_image(db_conn, lib_b, 3, 0xA5A55A5A0FF0F00F)
    mc = _shared_observation(db_conn, c)  # observed after B
    MatchRepository(db_conn).update_classification_and_notes(mc, classification="UNAUTHORIZED")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group([b, c], preferred_image_id=b)
    row = _match_row(db_conn, mb)
    assert row["canonical_match_id"] is None and row["classification"] == "UNREVIEWED" and row["triage_conflict"]

    repo.delete_group(group.id)  # no explicit review during this cycle

    row = _match_row(db_conn, mb)
    assert row["classification"] == "APPROVED" and row["notes"] == "licensed client"
    assert row["triage_conflict"] == 0 and f"photo #{a}" in row["inherited_from"]
    assert row["obs_classification"] == "UNREVIEWED"  # original observation stays provenance
    assert _match_row(db_conn, mc)["classification"] == "UNAUTHORIZED"


def test_inheritance_merged_from_a_temporary_sibling_does_not_leak_after_ungroup(db_conn, temp_dir: Path):
    lib_b, a, b, mb = _inherited_carrier(db_conn, temp_dir)
    c = _insert_image(db_conn, lib_b, 3, 0xA5A55A5A0FF0F00F)
    mc = _shared_observation(db_conn, c)
    # C observed X first, so C's row becomes canonical and carries the merged (inherited) state
    db_conn.execute("UPDATE matches SET first_seen_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (mc,))
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group([c, b], preferred_image_id=c)
    row = _match_row(db_conn, mc)
    assert row["canonical_match_id"] is None and f"photo #{a}" in row["inherited_from"]
    repo.delete_group(group.id)
    c_row = _match_row(db_conn, mc)
    assert c_row["classification"] == "UNREVIEWED" and c_row["inherited_from"] is None
    assert _match_row(db_conn, mb)["classification"] == "APPROVED"


def test_purge_during_the_current_cycle_keeps_the_newly_inherited_decision(db_conn, temp_dir: Path):
    libs = [_make_library(db_conn, temp_dir, name=f"cyc{i}") for i in range(3)]
    ids = [_insert_image(db_conn, lib, i, 0xA5A55A5A0FF0F00F) for i, lib in enumerate(libs)]
    matches = [_shared_observation(db_conn, i) for i in ids]
    MatchRepository(db_conn).update_classification_and_notes(matches[0], classification="APPROVED", notes="licensed client")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group(ids, preferred_image_id=ids[0])
    LibraryRepository(db_conn).purge(libs[0])  # inheritance acquired during this cycle
    repo.delete_group(group.id)
    row = _match_row(db_conn, matches[1])
    assert row["classification"] == "APPROVED" and row["notes"] == "licensed client"
    assert f"photo #{ids[0]}" in row["inherited_from"]


def test_in_cycle_inheritance_survives_when_the_carrier_is_later_folded_in_the_same_cycle(db_conn, temp_dir: Path):
    """B inherits A's decision during the cycle, then a photo with an earlier observation joins and
    folds B's discovery under its own; dissolving must not roll B back to its pre-cycle state."""
    libs = [_make_library(db_conn, temp_dir, name=f"fold{i}") for i in range(4)]
    a, b, d = (_insert_image(db_conn, libs[i], i, 0xA5A55A5A0FF0F00F) for i in range(3))
    ma, mb, _md = (_shared_observation(db_conn, i) for i in (a, b, d))
    MatchRepository(db_conn).update_classification_and_notes(ma, classification="APPROVED", notes="licensed client")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group([a, b, d], preferred_image_id=a)
    LibraryRepository(db_conn).purge(libs[0])
    assert _match_row(db_conn, mb)["inherited_at"]

    c = _insert_image(db_conn, libs[3], 3, 0xA5A55A5A0FF0F00F)
    mc = _shared_observation(db_conn, c)
    db_conn.execute("UPDATE matches SET first_seen_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (mc,))
    db_conn.commit()
    repo.add_image_to_group(group.id, c)
    assert _match_row(db_conn, mb)["canonical_match_id"] == mc  # B is now a folded observation

    repo.delete_group(group.id)
    row = _match_row(db_conn, mb)
    assert row["classification"] == "APPROVED" and row["notes"] == "licensed client"
    assert f"photo #{a}" in row["inherited_from"]


def _conflicting_pair(conn, temp_dir: Path, a_class: str = "APPROVED", b_class: str = "UNAUTHORIZED"):
    lib = _make_library(conn, temp_dir)
    a = _insert_image(conn, lib, 1, 0xA5A55A5A0FF0F00F)
    b = _insert_image(conn, lib, 2, 0xA5A55A5A0FF0F00F)
    ma, mb = _shared_observation(conn, a), _shared_observation(conn, b)
    match_repo = MatchRepository(conn)
    match_repo.update_classification_and_notes(ma, classification=a_class, notes="A note")
    match_repo.update_classification_and_notes(mb, classification=b_class, notes="B note")
    conn.commit()
    return a, b, ma, mb


def test_rollback_preserves_an_unresolved_pre_cycle_conflict(db_conn, temp_dir: Path):
    """A conflict kept open by an acknowledgement (no classification) is part of the next
    cycle's rollback state: a reversible grouping never lets a domain rule resolve it."""
    a, b, ma, _mb = _conflicting_pair(db_conn, temp_dir)
    repo = PhotoGroupRepository(db_conn)
    first = repo.create_group([a, b], preferred_image_id=a)
    MatchRepository(db_conn).update_classification_and_notes(ma, acknowledged=True)
    db_conn.commit()
    repo.delete_group(first.id)
    assert _match_row(db_conn, ma)["triage_conflict"] == 1

    second = repo.create_group([a, b], preferred_image_id=a)
    repo.delete_group(second.id)  # no explicit classification in either cycle
    rule = DomainRuleRepository(db_conn).upsert_rule("audit.example", "IRRELEVANT")
    MatchRepository(db_conn).apply_rule_to_unreviewed_matches("audit.example", "IRRELEVANT", rule.id)
    db_conn.commit()
    row = _match_row(db_conn, ma)
    assert (row["classification"], row["triage_conflict"]) == ("UNREVIEWED", 1)


def test_lineage_observation_does_not_prevent_group_rollback(db_conn, temp_dir: Path):
    """Codex reproduction: re-export provenance (LINEAGE) is permanent, not an active group."""
    lib, master, web, master_path, _ = _indexed_pair(db_conn, temp_dir)
    known_path = master_path.with_name("known_export.jpg")
    with Image.open(master_path) as im:
        im.resize((160, 160)).save(known_path, format="JPEG", quality=84)
    images = ImageRepository(db_conn)
    indexer = LibraryIndexer(LibraryRepository(db_conn), images, ThumbnailCache(temp_dir / "thumbs"))
    indexer.index_library(lib.id)
    known = images.get_by_path(str(known_path.resolve()))
    ma, mb, mk = [_shared_observation(db_conn, i) for i in (master.id, web.id, known.id)]
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(ma, classification="APPROVED")
    match_repo.update_classification_and_notes(mb, classification="UNAUTHORIZED")
    match_repo.update_classification_and_notes(mk, classification="APPROVED")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    first = repo.create_group([master.id, web.id], preferred_image_id=master.id)
    master_path.write_bytes(known_path.read_bytes())  # re-export of a test fixture in place
    known_path.unlink()
    indexer.index_library(lib.id)
    current = images.get_by_path(str(master_path.resolve()))
    assert current.id == known.id
    assert _match_row(db_conn, ma)["fold_kind"] == "LINEAGE" and _match_row(db_conn, ma)["canonical_match_id"] == mk
    match_repo.update_classification_and_notes(mk, classification="APPROVED", notes="latest decision")
    db_conn.commit()
    repo.delete_group(first.id)
    assert _match_row(db_conn, mk)["classification"] == "APPROVED"

    second = repo.create_group([current.id, web.id], preferred_image_id=current.id)
    assert _match_row(db_conn, mk)["classification"] == "UNREVIEWED"
    repo.delete_group(second.id)
    row = _match_row(db_conn, mk)
    assert (row["classification"], row["notes"]) == ("APPROVED", "latest decision")
    assert _match_row(db_conn, ma)["fold_kind"] == "LINEAGE"  # provenance kept
    assert _match_row(db_conn, mb)["classification"] == "UNAUTHORIZED"


def test_migration_closes_completed_legacy_cycles(temp_dir: Path):
    """A group dissolved before migration 016 leaves an independent row with that finished cycle's
    merged_at / explicit_review_at and no rb_*. Migration 018 closes such cycles, so a new
    unreviewed cycle rolls back to the current state instead of counting the old review."""
    import backend.migrations.runner as runner

    db_file = temp_dir / "legacy.sqlite"
    init_db(db_file)
    with get_db(db_file) as conn:
        a, b, ma, _mb = _conflicting_pair(conn, temp_dir, "APPROVED", "APPROVED")
        conn.execute(
            "UPDATE matches SET notes = 'latest decision', merged_at = '2026-01-01T00:00:00+00:00', "
            "explicit_review_at = '2026-01-02T00:00:00+00:00', obs_captured_at = '2026-01-01T00:00:00+00:00', "
            "obs_classification = 'APPROVED', obs_notes = 'A note' WHERE id = ?",
            (ma,),
        )
        runner.migration_018_close_completed_cycles(conn)
        conn.commit()
        row = _match_row(conn, ma)
        assert row["merged_at"] is None and row["explicit_review_at"] is None
        assert row["notes"] == "latest decision" and row["obs_notes"] == "A note"  # triage and provenance kept

        repo = PhotoGroupRepository(conn)
        group = repo.create_group([a, b], preferred_image_id=a)
        repo.delete_group(group.id)  # no review after upgrading
        assert _match_row(conn, ma)["notes"] == "latest decision"


def test_dissolving_after_a_reexport_keeps_the_lineage_merged_decision(db_conn, temp_dir: Path):
    """A validated re-export is a permanent identity transition: dissolving the group without a
    review must not roll the replacement back to its own pre-re-export state."""
    lib, master, web, master_path, _ = _indexed_pair(db_conn, temp_dir)
    known_path = master_path.with_name("known_export.jpg")
    with Image.open(master_path) as im:
        im.resize((160, 160)).save(known_path, format="JPEG", quality=84)
    images = ImageRepository(db_conn)
    indexer = LibraryIndexer(LibraryRepository(db_conn), images, ThumbnailCache(temp_dir / "thumbs"))
    indexer.index_library(lib.id)
    known = images.get_by_path(str(known_path.resolve()))
    ma, _mb, mk = [_shared_observation(db_conn, i) for i in (master.id, web.id, known.id)]
    MatchRepository(db_conn).update_classification_and_notes(ma, classification="APPROVED", notes="licensed")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group([master.id, web.id], preferred_image_id=master.id)
    master_path.write_bytes(known_path.read_bytes())
    known_path.unlink()
    indexer.index_library(lib.id)
    assert _match_row(db_conn, ma)["fold_kind"] == "LINEAGE"
    assert _match_row(db_conn, mk)["classification"] == "APPROVED"

    repo.delete_group(group.id)  # no review
    row = _match_row(db_conn, mk)
    assert row["classification"] == "APPROVED" and "licensed" in (row["notes"] or "")


def test_upgrade_preserves_conflict_in_an_open_cycle(db_conn, temp_dir: Path):
    """A cycle opened before migration 018 has a rollback state without rb_triage_conflict.
    Migration 019 backfills it, so an unresolved pre-cycle conflict is never cleared by the
    rollback, then resolved by a domain rule."""
    import backend.migrations.runner as runner

    a, b, ma, _mb = _conflicting_pair(db_conn, temp_dir)
    repo = PhotoGroupRepository(db_conn)
    first = repo.create_group([a, b], preferred_image_id=a)
    MatchRepository(db_conn).update_classification_and_notes(ma, acknowledged=True)
    db_conn.commit()
    repo.delete_group(first.id)
    assert _match_row(db_conn, ma)["triage_conflict"] == 1
    second = repo.create_group([a, b], preferred_image_id=a)
    # The snapshot as a pre-018 build captured it: no conflict flag
    db_conn.execute("UPDATE matches SET rb_triage_conflict = NULL WHERE id = ?", (ma,))
    db_conn.commit()
    saved = _match_row(db_conn, ma)
    assert saved["rb_classification"] == "UNREVIEWED" and saved["rb_captured_at"]
    runner.migration_019_open_cycle_conflict_backfill(db_conn)
    db_conn.commit()
    assert _match_row(db_conn, ma)["rb_triage_conflict"] == 1

    repo.repair_groups()
    repo.delete_group(second.id)  # no classification selected before or after upgrading
    rule = DomainRuleRepository(db_conn).upsert_rule("audit.example", "IRRELEVANT")
    MatchRepository(db_conn).apply_rule_to_unreviewed_matches("audit.example", "IRRELEVANT", rule.id)
    db_conn.commit()
    row = _match_row(db_conn, ma)
    assert (row["classification"], row["triage_conflict"]) == ("UNREVIEWED", 1)


def test_reexport_does_not_make_a_temporary_group_conflict_permanent(db_conn, temp_dir: Path):
    """Codex reproduction: re-exporting a conflicting group head keeps the permanent lineage
    decisions merged, while dissolving the group still undoes the temporary sibling merge."""
    lib, master, web, master_path, _ = _indexed_pair(db_conn, temp_dir)
    known_path = master_path.with_name("known_export.jpg")
    with Image.open(master_path) as im:
        im.resize((160, 160)).save(known_path, format="JPEG", quality=84)
    images = ImageRepository(db_conn)
    indexer = LibraryIndexer(LibraryRepository(db_conn), images, ThumbnailCache(temp_dir / "thumbs"))
    indexer.index_library(lib.id)
    known = images.get_by_path(str(known_path.resolve()))
    ma, mb, mk = [_shared_observation(db_conn, i) for i in (master.id, web.id, known.id)]
    match_repo = MatchRepository(db_conn)
    match_repo.update_classification_and_notes(ma, classification="APPROVED", notes="master licensed")
    match_repo.update_classification_and_notes(mb, classification="UNAUTHORIZED", notes="B note")
    match_repo.update_classification_and_notes(mk, classification="APPROVED", notes="export licensed")
    db_conn.commit()
    repo = PhotoGroupRepository(db_conn)
    group = repo.create_group([master.id, web.id], preferred_image_id=master.id)
    assert _match_row(db_conn, ma)["triage_conflict"] == 1
    master_path.write_bytes(known_path.read_bytes())  # re-export of a test fixture in place
    known_path.unlink()
    indexer.index_library(lib.id)
    assert images.get_by_path(str(master_path.resolve())).id == known.id
    assert _match_row(db_conn, ma)["fold_kind"] == "LINEAGE"
    assert _match_row(db_conn, mk)["triage_conflict"] == 1  # the group is still open

    repo.delete_group(group.id)  # no explicit review
    assert _match_row(db_conn, mb)["classification"] == "UNAUTHORIZED"
    row = _match_row(db_conn, mk)
    assert (row["classification"], row["triage_conflict"]) == ("APPROVED", 0)
    assert "master licensed" in row["notes"] and "export licensed" in row["notes"]
    assert "B note" not in row["notes"] and "conflicting decisions" not in row["notes"]
    assert _match_row(db_conn, ma)["fold_kind"] == "LINEAGE"  # provenance kept
