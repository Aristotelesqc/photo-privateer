"""Detect server-only drift without changing generated files or user data."""
import copy
from pathlib import Path

import pytest

from scripts.api_contract import artifacts, generate_types, load_schema, stale_artifacts, ts_type


def test_checked_in_contracts_match_current_server():
    assert stale_artifacts(artifacts(load_schema())) == []


def test_server_only_field_change_is_detected_without_rewriting(tmp_path):
    schema = load_schema()
    generated = tmp_path / "generated.ts"
    generated.write_text(generate_types(schema), encoding="utf-8")
    before = generated.read_bytes()
    changed = copy.deepcopy(schema)
    changed["components"]["schemas"]["LibraryOut"]["properties"]["server_only_test_field"] = {"type": "string"}
    assert stale_artifacts({generated: generate_types(changed)}) == [generated]
    assert generated.read_bytes() == before


def test_generator_preserves_null_optional_arrays_enums_and_rejects_unknown_forms():
    schema = {"type": "object", "required": ["value"], "properties": {
        "value": {"anyOf": [{"type": "string", "enum": ["a", "b"]}, {"type": "null"}]},
        "items": {"type": "array", "items": {"type": "integer"}},
    }}
    generated = ts_type(schema)
    assert '"value": "a" | "b" | null' in generated
    assert '"items"?: Array<number>' in generated
    with pytest.raises(ValueError, match="Unsupported"):
        ts_type({"oneOf": [{"type": "string"}, {"type": "integer"}]})


def test_missing_filter_is_exposed_and_acknowledgement_preserves_review(client, repos, sample_images_dir):
    library = repos["lib_repo"].create(str(sample_images_dir))
    repos["indexer"].index_library(library.id)
    photos, _ = repos["img_repo"].list_images(library_id=library.id)
    missing = photos[0]
    Path(missing.file_path).unlink()  # Synthetic fixture only.
    repos["indexer"].index_library(library.id)
    response = client.get("/api/photos", params={"filter_status": "missing"})
    assert response.status_code == 200
    assert [image["id"] for image in response.json()["images"]] == [missing.id]
    session = repos["scan_engine"].execute_scan([photos[1].id], "mock")
    matches = client.get("/api/matches").json()["matches"]
    assert session.status == "COMPLETED" and matches
    match_id = matches[0]["id"]
    response = client.patch(f"/api/matches/{match_id}", json={"classification": "APPROVED", "notes": "keep review"})
    assert response.status_code == 200
    response = client.patch(f"/api/matches/{match_id}", json={"acknowledged": True})
    assert response.status_code == 200
    assert response.json()["classification"] == "APPROVED"
    assert response.json()["notes"] == "keep review"
    assert response.json()["is_new"] is False
