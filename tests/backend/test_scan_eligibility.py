"""Browse/scan policy, historical retention and pre-provider rejection."""
from pathlib import Path
import pytest
from PIL import Image
from backend.repositories.group_repo import PhotoGroupRepository


@pytest.fixture
def sources(repos, temp_dir):
    result = {}
    for name in ("active", "archived", "disabled", "offline"):
        root = temp_dir / name
        root.mkdir()
        Image.new("RGB", (32, 32), color="red").save(root / f"{name}.png")
        lib = repos["lib_repo"].create(str(root), name=name)
        repos["indexer"].index_library(lib.id)
        images, _ = repos["img_repo"].list_images(library_id=lib.id)
        result[name] = (lib, images[0])
    repos["lib_repo"].archive(result["archived"][0].id)
    repos["lib_repo"].update(result["disabled"][0].id, enabled=False)
    Path(result["offline"][1].file_path).unlink()
    return result


def test_default_sources_explicit_history_and_restore(client, repos, sources):
    default = client.get("/api/photos").json()
    assert {image["filename"] for image in default["images"]} == {"active.png", "offline.png"}
    assert default["total"] == 2
    history = client.get("/api/photos?include_inactive=true").json()
    images = {image["filename"]: image for image in history["images"]}
    assert history["total"] == 4
    assert images["active.png"]["scan_eligible"] is True
    assert images["archived.png"]["library_archived"] is True
    assert images["disabled.png"]["library_enabled"] is False
    assert images["offline.png"]["source_available"] is False
    # The disk changed after indexing: the live Missing filter still finds the source.
    missing = client.get("/api/photos?filter_status=missing&page_size=1").json()
    assert missing["total"] == 1
    assert missing["images"][0]["filename"] == "offline.png"
    assert all(not images[f"{name}.png"]["scan_eligible"] for name in ("archived", "disabled", "offline"))
    archived = sources["archived"][0]
    assert client.get(f"/api/photos?library_id={archived.id}").json()["total"] == 0
    repos["lib_repo"].unarchive(archived.id)
    assert client.get("/api/photos").json()["total"] == 3
    assert repos["img_repo"].list_images()[1] == 4  # No catalog deletion.


def test_group_fallback_and_inactive_primary_do_not_hide_active_members(client, repos, sources):
    active = sources["active"][1]
    offline = sources["offline"][1]
    archived = sources["archived"][1]
    PhotoGroupRepository(repos["img_repo"].conn).create_group(
        [active.id, offline.id, archived.id], preferred_image_id=archived.id
    )
    images = {image["id"]: image for image in client.get("/api/photos?include_inactive=true").json()["images"]}
    assert images[active.id]["scan_eligible"] is True
    assert images[offline.id]["scan_eligible"] is True
    assert images[archived.id]["scan_eligible"] is False
    plan = repos["scan_engine"].plan_scan([offline.id, active.id], provider_override="mock")
    assert [image.id for image in plan.scannable_images] == [active.id]
    projection = client.post("/api/scans/prepare", json={"image_ids": [offline.id, active.id], "provider": "mock"}).json()
    assert projection["usable_count"] == 1
    assert projection["grouped_variant_count"] == 1
    assert client.get("/api/photos").json()["total"] == 2


@pytest.mark.parametrize("change", ["archive", "disable"])
def test_change_after_projection_rejected_before_provider(client, repos, sources, monkeypatch, change):
    lib, image = sources["active"]
    payload = {"image_ids": [image.id], "provider": "mock"}
    assert client.post("/api/scans/prepare", json=payload).status_code == 200
    if change == "archive":
        repos["lib_repo"].archive(lib.id)
    else:
        repos["lib_repo"].update(lib.id, enabled=False)
    provider = []
    monkeypatch.setattr("backend.services.scan_engine.get_provider", lambda *args, **kwargs: provider.append(args))
    for route in ("prepare", "start"):
        response = client.post(f"/api/scans/{route}", json=payload)
        assert response.status_code == 400
        assert "Settings" in response.json()["detail"]
    assert provider == []
    assert repos["usage_repo"].conn.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0] == 0
    assert repos["usage_repo"].conn.execute("SELECT COUNT(*) FROM scan_sessions").fetchone()[0] == 0


def test_batch_selection_rejects_ineligible_without_partial_update(client, repos, sources):
    active = sources["active"][1]
    disabled = sources["disabled"][1]
    response = client.post("/api/photos/batch-project", json={"photo_ids": [active.id, disabled.id], "project": "Changed"})
    assert response.status_code == 400
    assert repos["img_repo"].get_by_id(active.id).project is None
    assert repos["img_repo"].get_by_id(disabled.id).project is None
    assert client.post("/api/photos/batch-project", json={"photo_ids": [active.id], "project": "Active"}).status_code == 200
    repos["img_repo"].update_project(disabled.id, "Historical")
    repos["img_repo"].conn.commit()
    assert client.get("/api/photos/projects").json() == ["Active"]
    assert client.get("/api/photos/projects?include_inactive=true").json() == ["Active", "Historical"]


def test_source_containment_shared_by_browse_and_preparation(client, repos, sources, temp_dir):
    image = sources["active"][1]
    outside = temp_dir / "outside.png"
    Image.new("RGB", (16, 16)).save(outside)
    repos["img_repo"].conn.execute("UPDATE images SET file_path = ? WHERE id = ?", (str(outside), image.id))
    repos["img_repo"].conn.commit()
    assert client.get(f"/api/photos/{image.id}").json()["scan_eligible"] is False
    response = client.post("/api/scans/prepare", json={"image_ids": [image.id], "provider": "mock"})
    assert response.status_code == 400


def test_archival_keeps_historical_discoveries_and_notes(client, repos, sample_images_dir):
    lib = repos["lib_repo"].create(str(sample_images_dir))
    repos["indexer"].index_library(lib.id)
    images, _ = repos["img_repo"].list_images(library_id=lib.id)
    photo = next(image for image in images if image.filename == "mountain_landscape.jpg")
    repos["scan_engine"].execute_scan([photo.id], provider_override="mock")
    matches, total = repos["match_repo"].list_matches(image_id=photo.id)
    assert total > 0
    match = matches[0]
    assert client.patch(f"/api/matches/{match.id}", json={"classification": "APPROVED", "notes": "Preserve historical authorization"}).status_code == 200
    repos["lib_repo"].archive(lib.id)
    assert client.get("/api/photos").json()["total"] == 0
    history = client.get("/api/photos?include_inactive=true").json()["images"]
    assert next(image for image in history if image["id"] == photo.id)["match_count"] == total
    record = client.get(f"/api/matches/{match.id}").json()
    assert record["classification"] == "APPROVED"
    assert record["notes"] == "Preserve historical authorization"
    repos["lib_repo"].unarchive(lib.id)
    assert client.get(f"/api/photos/{photo.id}").json()["scan_eligible"] is True
