"""Tests for match persistence, classification preservation, and rescan history."""
from __future__ import annotations

from pathlib import Path
from backend.config import CLASS_APPROVED, CLASS_UNAUTHORIZED, CLASS_UNREVIEWED

def test_matches_persistence_and_rescan_preservation(repos, sample_images_dir: Path):
    indexer = repos["indexer"]
    lib_repo = repos["lib_repo"]
    img_repo = repos["img_repo"]
    match_repo = repos["match_repo"]
    scan_engine = repos["scan_engine"]

    # 1. Index library
    lib = lib_repo.create(path=str(sample_images_dir), name="Photos")
    indexer.index_library(lib.id)
    images, _ = img_repo.list_images(library_id=lib.id)
    target_img = next(img for img in images if img.filename == "mountain_landscape.jpg")

    # 2. First scan
    session1 = scan_engine.execute_scan(image_ids=[target_img.id], provider_override="mock")
    assert session1.status == "COMPLETED"
    assert session1.successful_images == 1

    matches1, count1 = match_repo.list_matches(image_id=target_img.id)
    assert count1 > 0
    for m in matches1:
        assert m.is_new is True
        assert m.classification == CLASS_UNREVIEWED

    # 3. User reviews and classifies one match as APPROVED with notes
    first_match = matches1[0]
    updated = match_repo.update_classification_and_notes(
        match_id=first_match.id,
        classification=CLASS_APPROVED,
        notes="Official authorized publication",
    )
    assert updated.classification == CLASS_APPROVED
    assert updated.notes == "Official authorized publication"

    # User classifies second match as UNAUTHORIZED
    if len(matches1) > 1:
        match_repo.update_classification_and_notes(
            match_id=matches1[1].id,
            classification=CLASS_UNAUTHORIZED,
            notes="Infringing commercial wallpaper site",
        )

    # 4. Rescan the same image
    session2 = scan_engine.execute_scan(image_ids=[target_img.id], provider_override="mock")
    assert session2.status == "COMPLETED"

    matches2, count2 = match_repo.list_matches(image_id=target_img.id)
    # Total count should NOT duplicate rows
    assert count2 == count1

    # Check preserved classifications and notes
    remet = match_repo.get_by_id(first_match.id)
    assert remet.classification == CLASS_APPROVED, "Rescan wiped user's classification!"
    assert remet.notes == "Official authorized publication", "Rescan wiped user's notes!"
    assert remet.is_new is False, "Rediscovered match should not be flagged as new!"
    assert remet.last_seen_at >= first_match.first_seen_at
