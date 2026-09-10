"""Tests for FastAPI HTTP routes and full end-to-end API workflows."""
from __future__ import annotations

from pathlib import Path

def test_full_api_workflow(client, sample_images_dir: Path):
    # 1. Add Library
    res_lib = client.post("/api/libraries", json={
        "path": str(sample_images_dir),
        "name": "E2E Test Library",
        "recursive": True,
    })
    assert res_lib.status_code == 200
    lib_data = res_lib.json()
    lib_id = lib_data["id"]

    # 2. Index Library
    res_idx = client.post(f"/api/libraries/{lib_id}/index")
    assert res_idx.status_code == 200
    idx_data = res_idx.json()
    assert idx_data["results"]["scanned"] == 5

    # 3. List Photos
    res_photos = client.get("/api/photos")
    assert res_photos.status_code == 200
    photos_data = res_photos.json()
    assert photos_data["total"] == 5
    first_photo = photos_data["images"][0]

    # 4. Fetch Thumbnail
    res_thumb = client.get(f"/api/photos/{first_photo['id']}/thumbnail")
    assert res_thumb.status_code == 200
    assert "image/webp" in res_thumb.headers.get("content-type", "")

    # 5. Prepare Scan
    res_prep = client.post("/api/scans/prepare", json={
        "image_ids": [first_photo["id"]],
        "provider": "mock",
    })
    assert res_prep.status_code == 200
    prep_data = res_prep.json()
    assert prep_data["selected_count"] == 1
    assert prep_data["estimated_incremental_cost_usd"] == 0.0

    # 6. Start Scan (asynchronous background execution)
    res_scan = client.post("/api/scans/start", json={
        "image_ids": [first_photo["id"]],
        "provider": "mock",
    })
    assert res_scan.status_code == 200
    scan_data = res_scan.json()
    assert scan_data["status"] in ("RUNNING", "COMPLETED")
    assert scan_data["total_images"] == 1
    session_id = scan_data["id"]

    import time
    for _ in range(50):
        res_poll = client.get(f"/api/scans/{session_id}")
        assert res_poll.status_code == 200
        poll_data = res_poll.json()
        if poll_data["status"] in ("COMPLETED", "FAILED"):
            scan_data = poll_data
            break
        time.sleep(0.05)

    assert scan_data["status"] == "COMPLETED"

    # 7. List Matches
    res_matches = client.get(f"/api/matches?image_id={first_photo['id']}")
    assert res_matches.status_code == 200
    matches_data = res_matches.json()
    if matches_data["total"] > 0:
        match_item = matches_data["matches"][0]
        # 8. Update Classification
        res_class = client.patch(f"/api/matches/{match_item['id']}", json={
            "classification": "APPROVED",
            "notes": "Reviewed via test",
        })
        assert res_class.status_code == 200
        assert res_class.json()["classification"] == "APPROVED"

    # 9. Create Domain Rule
    res_rule = client.post("/api/rules", json={
        "domain": "test-portfolio.com",
        "classification": "APPROVED",
        "notes": "E2E Rule",
    })
    assert res_rule.status_code == 200
    assert res_rule.json()["domain"] == "test-portfolio.com"

    # 10. Check Usage Summary
    res_usage = client.get("/api/usage/summary")
    assert res_usage.status_code == 200
    usage_data = res_usage.json()
    assert "units_used_this_month" in usage_data
    assert "NOTICE: All usage counts and costs" in usage_data["disclaimer"]

    # 11. Check Settings
    res_settings = client.get("/api/settings")
    assert res_settings.status_code == 200
    assert res_settings.json()["active_provider"] == "mock"
