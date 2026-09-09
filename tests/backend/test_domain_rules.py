"""Tests for domain classification rules engine and override behavior."""
from __future__ import annotations

from pathlib import Path
from backend.config import CLASS_APPROVED, CLASS_IRRELEVANT, CLASS_UNAUTHORIZED

def test_domain_rules_and_manual_override(repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    rule_repo = repos["rule_repo"]
    match_repo = repos["match_repo"]
    scan_engine = repos["scan_engine"]

    # 1. Setup library & index
    lib = lib_repo.create(path=str(sample_images_dir), name="Photos")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    multi_img = next(img for img in images if img.filename == "multi_domain_photo.jpg")

    # 2. Add rule: always mark curated-exhibits.art as APPROVED
    rule = rule_repo.upsert_rule("curated-exhibits.art", CLASS_APPROVED, notes="Whitelisted gallery partner")
    assert rule.id is not None
    assert rule.domain == "curated-exhibits.art"

    # 3. Add rule: always mark spam-scraper-repost.biz as IRRELEVANT
    rule_repo.upsert_rule("spam-scraper-repost.biz", CLASS_IRRELEVANT, notes="Known scraping bot")

    # 4. Execute scan
    scan_engine.execute_scan(image_ids=[multi_img.id], provider_override="mock")

    matches, total = match_repo.list_matches(image_id=multi_img.id)
    assert total >= 3

    # Check that rules were applied deterministically to newly discovered matches
    exhibit_matches = [m for m in matches if "curated-exhibits.art" in m.domain]
    assert len(exhibit_matches) >= 2
    for m in exhibit_matches:
        assert m.classification == CLASS_APPROVED
        assert m.auto_classified_by_rule_id == rule.id

    spam_matches = [m for m in matches if "spam-scraper-repost.biz" in m.domain]
    assert len(spam_matches) >= 1
    for m in spam_matches:
        assert m.classification == CLASS_IRRELEVANT

    # 5. User manually overrides one of the approved matches to UNAUTHORIZED
    target_match = exhibit_matches[0]
    overridden = match_repo.update_classification_and_notes(
        match_id=target_match.id,
        classification=CLASS_UNAUTHORIZED,
        notes="Actually an unauthorized usage on sub-page",
    )
    assert overridden.classification == CLASS_UNAUTHORIZED
    assert overridden.auto_classified_by_rule_id is None  # Manual override clears rule provenance

    # 6. Rescan: verify manual override is PRESERVED and not reverted back by the domain rule
    scan_engine.execute_scan(image_ids=[multi_img.id], provider_override="mock")
    refetched = match_repo.get_by_id(target_match.id)
    assert refetched.classification == CLASS_UNAUTHORIZED, "Manual override was reverted by domain rule on rescan!"
    assert refetched.notes == "Actually an unauthorized usage on sub-page"

def test_retroactive_domain_rule_application(repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    rule_repo = repos["rule_repo"]
    match_repo = repos["match_repo"]
    scan_engine = repos["scan_engine"]

    # Index and scan without rules
    lib = lib_repo.create(path=str(sample_images_dir), name="Photos")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    multi_img = next(img for img in images if img.filename == "multi_domain_photo.jpg")

    scan_engine.execute_scan(image_ids=[multi_img.id], provider_override="mock")
    matches_before, _ = match_repo.list_matches(domain="curated-exhibits.art")
    assert all(m.classification == "UNREVIEWED" for m in matches_before)

    # Now create rule: should retroactively update unreviewed matches
    rule = rule_repo.upsert_rule("curated-exhibits.art", CLASS_APPROVED)
    updated_count = match_repo.apply_rule_to_unreviewed_matches("curated-exhibits.art", CLASS_APPROVED, rule.id)
    assert updated_count == len(matches_before)

    matches_after, _ = match_repo.list_matches(domain="curated-exhibits.art")
    assert all(m.classification == CLASS_APPROVED for m in matches_after)
