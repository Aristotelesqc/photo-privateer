"""Executable PR4 compatibility examples for the future identity ADR.

These exercise real migrated SQLite repositories. They do not simulate or claim
to validate the proposed UUID schema, authorizations, evidence or case modules.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image

from backend.repositories.group_repo import PhotoGroupRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.match_repo import MatchRepository
from backend.services.perceptual import is_candidate_representation


FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "identity_contract.json").read_text(encoding="utf-8")
)


def test_identity_contract_fixture_has_distinct_uuid4_examples():
    examples = list(FIXTURE["target_example_ids"].values())
    assert len(set(examples)) == len(examples)
    assert all(UUID(value).version == 4 for value in examples)
    names = [scenario["name"] for scenario in FIXTURE["scenarios"]]
    assert len(set(names)) == len(names)
    assert any("known_limitation" in scenario for scenario in FIXTURE["scenarios"])


@pytest.mark.parametrize("scenario", FIXTURE["scenarios"], ids=lambda value: value["name"])
def test_identity_contract_pr4_examples(db_conn, temp_dir: Path, scenario):
    libraries = LibraryRepository(db_conn)
    images = ImageRepository(db_conn)
    matches = MatchRepository(db_conn)
    groups = PhotoGroupRepository(db_conn)
    image_ids: dict[str, int] = {}
    match_ids: dict[str, int] = {}
    library_ids: dict[str, int] = {}
    sources: dict[Path, bytes] = {}
    group_id: int | None = None

    # Independent libraries make purging one source exercise the actual handover.
    # File content is temporary; no indexing, provider search or user DB is used.
    for position, spec in enumerate(scenario["initial"]):
        name = spec["name"]
        root = temp_dir / name
        root.mkdir()
        path = root / f"{name}.png"
        Image.new("RGB", (16, 16), (position * 30, 80, 120)).save(path)
        sources[path] = path.read_bytes()
        library = libraries.create(str(root), name=name)
        image = images.upsert_image(
            library.id, hashlib.sha256(sources[path]).hexdigest(), str(path.resolve()),
            path.name, path.stat().st_size, path.stat().st_mtime, 16, 16, "PNG",
            dhash="a5a55a5a0ff0f00f",
        )
        image_ids[name], library_ids[name] = image.id, library.id
        if spec.get("observe", True):
            match, _ = matches.upsert_match(
                image.id, None, "contract.example", "FULL", "mock", source_kind="PAGE",
                page_url="https://contract.example/use",
                candidate_image_url="https://contract.example/use.jpg",
            )
            match_ids[name] = match.id
            matches.update_classification_and_notes(
                match.id, classification=spec.get("classification", "UNREVIEWED"),
                notes=spec.get("notes"),
            )
            # Canonical owner election is deterministic even on coarse clocks.
            db_conn.execute(
                "UPDATE matches SET first_seen_at = ? WHERE id = ?",
                (f"2000-01-01T00:00:{position:02d}+00:00", match.id),
            )
        db_conn.commit()

    def check(expected):
        for name, fields in expected.items():
            row = db_conn.execute(
                "SELECT * FROM matches WHERE id = ?", (match_ids[name],)
            ).fetchone()
            if fields.get("absent"):
                assert row is None
                continue
            assert row is not None
            for field, value in fields.items():
                if field == "canonical":
                    assert row["canonical_match_id"] == (match_ids[value] if value else None)
                elif field == "image":
                    assert row["image_id"] == image_ids[value]
                elif field == "explicit":
                    assert bool(row["explicit_review_at"]) is value
                elif field == "inherited_from_images":
                    assert row["inherited_at"]
                    for origin in value:
                        assert f"photo #{image_ids[origin]} (" in row["inherited_from"]
                elif field == "notes_contains":
                    assert all(part in (row["notes"] or "") for part in value)
                elif field == "notes_excludes":
                    assert all(part not in (row["notes"] or "") for part in value)
                elif field == "original_image_column_absent":
                    assert value is True and "original_image_id" not in row.keys()
                else:
                    assert row[field] == value, (scenario["name"], name, field, dict(row))

    for step in scenario["steps"]:
        operation = step["op"]
        if operation == "group":
            members = [image_ids[name] for name in step["members"]]
            primary = image_ids[step.get("primary", step["members"][0])]
            group_id = groups.create_group(members, preferred_image_id=primary).id
        elif operation == "dissolve":
            assert group_id is not None
            assert groups.delete_group(group_id)
            group_id = None
        elif operation == "review":
            payload = {key: step[key] for key in ("classification", "notes", "acknowledged") if key in step}
            matches.update_classification_and_notes(match_ids[step["image"]], **payload)
        elif operation == "primary":
            assert group_id is not None
            groups.set_preferred_image(group_id, image_ids[step["image"]])
            assert groups.get_group(group_id).preferred_image_id == image_ids[step["image"]]
        elif operation == "purge":
            assert libraries.purge(library_ids[step["image"]])
        elif operation == "leave":
            assert group_id is not None
            groups.remove_image_from_group(group_id, image_ids[step["image"]])
        elif operation == "validated_lineage":
            old = images.get_by_id(image_ids[step["old"]])
            target = images.get_by_id(image_ids[step["target"]])
            assert old.photo_group_id is not None
            assert is_candidate_representation(old.dhash, target.dhash)
            # Public repository boundary used by the indexer AFTER it validates
            # replacement. Existing indexer tests cover file/hash detection.
            images.detach_archived_image(old.id, f"{old.file_path}#archived-{old.id}")
            images.transfer_representation_history(old.id, target.id)
            images.inherit_group_membership(target.id, old.photo_group_id, bool(old.is_primary_representation))
            groups.repair_groups()
            db_conn.commit()
        else:
            pytest.fail(f"Unsupported fixture operation: {operation}")
        check(step.get("expect", {}))
        assert db_conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert all(path.read_bytes() == original for path, original in sources.items())
