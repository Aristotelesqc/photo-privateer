"""Regression tests covering specific audit requirements:
- Server-side rejection of archived/disabled library scans
- Transactional library purge without touching source files
- Domain rule cascade update preserving manual user overrides
- Credentials clearing and reverting to ADC
- Empty notes clearing to NULL
- Chunking helper for SQLite batches
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from PIL import Image

from backend.utils import chunked
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.services.library_indexer import LibraryIndexer
from backend.models import MatchUpdate, SettingsUpdate

def test_chunked_helper():
    items = list(range(1050))
    chunks = list(chunked(items, size=500))
    assert len(chunks) == 3
    assert len(chunks[0]) == 500
    assert len(chunks[1]) == 500
    assert len(chunks[2]) == 50
    assert [x for c in chunks for x in c] == items

def test_archived_and_disabled_library_scan_rejection(client, repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="Photos")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) > 0
    img_id = images[0].id

    # Archive the library
    lib_repo.archive(lib.id)

    # Rejection in /api/scans/prepare
    prep_res = client.post("/api/scans/prepare", json={"image_ids": [img_id]})
    assert prep_res.status_code == 400
    assert "archived or disabled" in prep_res.json()["detail"].lower()

    # Rejection in /api/scans/start
    start_res = client.post("/api/scans/start", json={"image_ids": [img_id]})
    assert start_res.status_code == 400
    assert "archived or disabled" in start_res.json()["detail"].lower()

    # Unarchive but disable
    lib_repo.unarchive(lib.id)
    lib_repo.update(lib.id, enabled=False)

    prep_res2 = client.post("/api/scans/prepare", json={"image_ids": [img_id]})
    assert prep_res2.status_code == 400
    assert "archived or disabled" in prep_res2.json()["detail"].lower()

def test_library_purge_transactional_without_touching_source_files(client, repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    match_repo = repos["match_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="PurgeTest")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    assert len(images) > 0

    # Add a dummy match for one of the images
    match_repo.upsert_match(
        image_id=images[0].id,
        scan_session_id=None,
        domain="example.com",
        match_type="FULL",
        provider="mock",
    )

    # Purge via repository
    purged = lib_repo.purge(lib.id)
    assert purged is True

    # Library and images should be gone from SQLite
    assert lib_repo.get_by_id(lib.id) is None
    rem_images, _ = img_repo.list_images(library_id=lib.id)
    assert len(rem_images) == 0

    # Source files on disk MUST NOT be deleted
    for img in images:
        assert Path(img.file_path).exists(), f"Source file was deleted! {img.file_path}"

def test_domain_rule_cascade_preserves_manual_override(client, repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    match_repo = repos["match_repo"]
    rule_repo = repos["rule_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="RuleTest")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    img = images[0]

    # 1. Create rule domain "myportfolio.com" with APPROVED
    r1 = client.post("/api/rules", json={
        "domain": "myportfolio.com",
        "classification": "APPROVED",
        "notes": "Portfolio site",
    }).json()
    rule_id = r1["id"]

    # 2. Add two matches matching this domain
    m1, _ = match_repo.upsert_match(
        image_id=img.id,
        scan_session_id=None,
        domain="myportfolio.com",
        match_type="FULL",
        provider="mock",
        page_url="https://myportfolio.com/page1",
        default_classification="APPROVED",
        rule_id=rule_id,
    )
    m2, _ = match_repo.upsert_match(
        image_id=img.id,
        scan_session_id=None,
        domain="myportfolio.com",
        match_type="FULL",
        provider="mock",
        page_url="https://myportfolio.com/page2",
        default_classification="APPROVED",
        rule_id=rule_id,
    )

    assert m1.classification == "APPROVED"
    assert m1.auto_classified_by_rule_id == rule_id
    assert m2.classification == "APPROVED"
    assert m2.auto_classified_by_rule_id == rule_id

    # 3. User manually overrides m2 to UNAUTHORIZED
    patch_res = client.patch(f"/api/matches/{m2.id}", json={"classification": "UNAUTHORIZED"})
    assert patch_res.status_code == 200
    m2_updated = match_repo.get_by_id(m2.id)
    assert m2_updated.classification == "UNAUTHORIZED"
    assert m2_updated.auto_classified_by_rule_id is None  # provenance cleared

    # 4. Update the rule classification to IRRELEVANT
    r2 = client.post("/api/rules", json={
        "domain": "myportfolio.com",
        "classification": "IRRELEVANT",
    })
    assert r2.status_code == 200

    # 5. Check cascade: m1 should be IRRELEVANT, m2 must STILL be UNAUTHORIZED
    m1_refreshed = match_repo.get_by_id(m1.id)
    m2_refreshed = match_repo.get_by_id(m2.id)

    assert m1_refreshed.classification == "IRRELEVANT"
    assert m1_refreshed.auto_classified_by_rule_id == rule_id
    assert m2_refreshed.classification == "UNAUTHORIZED"
    assert m2_refreshed.auto_classified_by_rule_id is None

def test_credentials_clearing_reverts_to_adc(client, repos, temp_dir: Path):
    settings_repo = repos["settings_repo"]

    dummy_sa = temp_dir / "service_account.json"
    dummy_sa.write_text(json.dumps({
        "type": "service_account",
        "project_id": "test-proj",
        "private_key_id": "k1",
        "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----\n",
        "client_email": "test@test-proj.iam.gserviceaccount.com",
        "client_id": "123",
    }), encoding="utf-8")

    # Set credentials path
    res1 = client.patch("/api/settings", json={"google_credentials_path": str(dummy_sa)})
    assert res1.status_code == 200
    assert res1.json()["google_credentials_path"] == str(dummy_sa)
    assert res1.json()["auth_mode"] == "service_account"

    # Clear credentials path with null
    res2 = client.patch("/api/settings", json={"google_credentials_path": None})
    assert res2.status_code == 200
    assert res2.json()["google_credentials_path"] is None
    # Now that credentials path is cleared, it falls back to ADC or none
    assert res2.json()["auth_mode"] in ("adc", "none")

    # Re-set and clear with empty string
    client.patch("/api/settings", json={"google_credentials_path": str(dummy_sa)})
    res3 = client.patch("/api/settings", json={"google_credentials_path": ""})
    assert res3.status_code == 200
    assert res3.json()["google_credentials_path"] is None

def test_clearing_notes_sets_null(client, repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    match_repo = repos["match_repo"]

    lib = lib_repo.create(path=str(sample_images_dir), name="NotesTest")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    img = images[0]

    m, _ = match_repo.upsert_match(
        image_id=img.id,
        scan_session_id=None,
        domain="example.org",
        match_type="FULL",
        provider="mock",
    )

    # Set notes
    patch1 = client.patch(f"/api/matches/{m.id}", json={"notes": "Contacted infringement team"})
    assert patch1.status_code == 200
    assert patch1.json()["notes"] == "Contacted infringement team"

    # Clear notes with empty string
    patch2 = client.patch(f"/api/matches/{m.id}", json={"notes": ""})
    assert patch2.status_code == 200
    assert patch2.json()["notes"] is None

    m_db = match_repo.get_by_id(m.id)
    assert m_db.notes is None

    # Set notes again and clear with whitespace
    client.patch(f"/api/matches/{m.id}", json={"notes": "Some note"})
    patch3 = client.patch(f"/api/matches/{m.id}", json={"notes": "   "})
    assert patch3.status_code == 200
    assert patch3.json()["notes"] is None
