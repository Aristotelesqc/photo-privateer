"""Offline root relinking against real migrated SQLite catalogs and source files."""
from __future__ import annotations

from contextlib import closing
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from backend.migrations.runner import run_migrations
from backend.repositories.group_repo import PhotoGroupRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.match_repo import MatchRepository
from backend.services import library_relink
from backend.services.catalog_backup import DATABASE_NAME, BackupError, verify_backup
from backend.services.library_relink import RelinkError, relink_library
from backend.services.profile_lock import ProfileBusyError


@pytest.fixture
def relink_catalog(tmp_path: Path):
    profile, old, new = (tmp_path / name for name in ("profile", "old", "new"))
    for root in (profile, old, new):
        root.mkdir()
    db_path = profile / DATABASE_NAME
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    libraries = LibraryRepository(conn)
    images = ImageRepository(conn)
    matches = MatchRepository(conn)
    library = libraries.create(str(old), name="Moved originals")
    ids = {}
    expected_sources = {}
    for name, relative, content in (
        ("A", "a.jpg", b"matching duplicated source"),
        ("B", "nested/b.jpg", b"matching duplicated source"),
        ("missing", "missing.png", b"temporarily offline"),
        ("alias", "historic.jpg", b"old export content"),
    ):
        path = old / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        expected_sources[path] = content
        row = images.upsert_image(
            library.id, hashlib.sha256(content).hexdigest(), str(path.resolve()),
            path.name, len(content), path.stat().st_mtime, 100, 80, "JPEG",
            project="manual project", project_source="manual", dhash="a5a55a5a0ff0f00f",
        )
        ids[name] = row.id
        if name in ("A", "B"):
            target = new / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            expected_sources[target] = content
            match, _ = matches.upsert_match(
                row.id, None, "fixture.example", "FULL", "mock",
                page_url="https://fixture.example/use", candidate_image_url="https://fixture.example/asset.jpg",
            )
            matches.update_classification_and_notes(
                match.id, classification="APPROVED" if name == "A" else "UNAUTHORIZED",
                notes=f"{name} prior decision",
            )
    images.detach_archived_image(ids["alias"], str(old / "historic.jpg") + f"#archived-{ids['alias']}")
    fake_alias = new / f"historic.jpg#archived-{ids['alias']}"
    fake_alias.write_bytes(b"not the source: never open this sentinel")
    expected_sources[fake_alias] = fake_alias.read_bytes()
    groups = PhotoGroupRepository(conn)
    groups.create_group([ids["A"], ids["B"]], preferred_image_id=ids["B"])
    conn.execute("UPDATE images SET scan_count=2,last_scanned_at='2026-01-01' WHERE id=?", (ids["A"],))
    session = conn.execute(
        "INSERT INTO scan_sessions(started_at,provider,total_images,status,notes) VALUES('2026-01-01','mock',1,'COMPLETED','history')"
    ).lastrowid
    conn.execute(
        "INSERT INTO scan_items(scan_session_id,image_id,status,created_at) VALUES(?,?,'SUCCESS','2026-01-01')",
        (session, ids["A"]),
    )
    conn.execute(
        "INSERT INTO provider_calls(provider,timestamp,billing_period,scan_session_id,image_id,request_status) VALUES('mock','2026-01-01','2026-01',?,?,'SUCCESS')",
        (session, ids["A"]),
    )
    conn.commit()
    try:
        yield {
            "profile": profile, "old": old, "new": new, "db_path": db_path,
            "conn": conn, "library_id": library.id, "ids": ids, "sources": expected_sources,
        }
    finally:
        conn.close()


def catalog_state(conn, *, omit_relinked_fields=False):
    state = {}
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        # Cache generation is intentionally invalidated by catalog triggers.
        if table == "group_candidate_state":
            continue
        rows = [dict(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
        if omit_relinked_fields:
            for row in rows:
                if table == "libraries":
                    row.pop("path")
                elif table == "images":
                    row.pop("file_path")
                    row.pop("is_present_on_disk")
        state[table] = rows
    return state


def test_dry_run_keeps_catalog_and_originals_unchanged(relink_catalog):
    data = relink_catalog
    before = catalog_state(data["conn"])
    raw_db = data["db_path"].read_bytes()
    result = relink_library(data["profile"], data["library_id"], data["new"])
    assert result["applied"] is False and result["backup_path"] is None
    assert (result["image_count"], result["present_count"], result["missing_count"], result["archived_alias_count"]) == (4, 2, 1, 1)
    assert catalog_state(data["conn"]) == before
    assert data["db_path"].read_bytes() == raw_db
    assert not (data["profile"] / "backups").exists()
    assert all(path.read_bytes() == content for path, content in data["sources"].items())


def test_apply_backs_up_old_catalog_and_preserves_ids_triage_and_history(relink_catalog):
    data = relink_catalog
    before = catalog_state(data["conn"], omit_relinked_fields=True)
    # Former root may be absent. Original fixture bytes remain elsewhere.
    moved = data["old"].with_name("former-root-now-offline")
    data["old"].rename(moved)
    old_sources = {moved / path.relative_to(data["old"]): content for path, content in data["sources"].items() if path.is_relative_to(data["old"])}
    result = relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert result["applied"] is True
    bundle = Path(result["backup_path"])
    assert bundle.parent == data["profile"] / "backups" and bundle.name.startswith("relink-")
    verify_backup(bundle)
    with closing(sqlite3.connect(bundle / "catalog.sqlite")) as backup:
        assert backup.execute("SELECT path FROM libraries WHERE id=?", (data["library_id"],)).fetchone()[0] == str(data["old"])
    assert catalog_state(data["conn"], omit_relinked_fields=True) == before
    assert data["conn"].execute("PRAGMA foreign_key_check").fetchall() == []
    rows = {row["id"]: dict(row) for row in data["conn"].execute("SELECT * FROM images")}
    assert rows[data["ids"]["A"]]["file_path"] == str(data["new"] / "a.jpg")
    assert rows[data["ids"]["B"]]["file_path"] == str(data["new"] / "nested/b.jpg")
    assert rows[data["ids"]["A"]]["sha256"] == rows[data["ids"]["B"]]["sha256"]
    assert rows[data["ids"]["missing"]]["is_present_on_disk"] == 0
    assert rows[data["ids"]["alias"]]["is_present_on_disk"] == 0
    assert rows[data["ids"]["alias"]]["file_path"].endswith(f"historic.jpg#archived-{data['ids']['alias']}")
    assert all(path.read_bytes() == content for path, content in old_sources.items())
    assert all(path.read_bytes() == content for path, content in data["sources"].items() if path.is_relative_to(data["new"]))


@pytest.mark.parametrize("apply", [False, True])
def test_changed_content_is_refused_before_catalog_or_backup_mutation(relink_catalog, apply):
    data = relink_catalog
    (data["new"] / "a.jpg").write_bytes(b"unrelated content at same relative path")
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError, match="SHA-256 mismatch"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=apply)
    assert catalog_state(data["conn"]) == before
    assert not (data["profile"] / "backups").exists()


def test_alias_is_never_hashed_even_when_a_real_file_has_its_name(relink_catalog, monkeypatch):
    data = relink_catalog
    called = []
    original = library_relink._presence
    def record(path, *args):
        called.append(path)
        return original(path, *args)
    monkeypatch.setattr(library_relink, "_presence", record)
    result = relink_library(data["profile"], data["library_id"], data["new"])
    assert result["archived_alias_count"] == 1
    assert all("#archived-" not in str(path) for path in called)


def test_archived_root_overlap_is_refused(relink_catalog):
    data = relink_catalog
    other = data["old"].with_name("other")
    other.mkdir()
    library = LibraryRepository(data["conn"]).create(str(other))
    data["conn"].execute("UPDATE libraries SET path=?,enabled=0,is_archived=1 WHERE id=?", (str(data["new"].parent), library.id))
    data["conn"].commit()
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError, match="overlaps"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert catalog_state(data["conn"]) == before


def test_other_catalog_image_collision_is_refused(relink_catalog):
    data = relink_catalog
    other = data["old"].with_name("other")
    other.mkdir()
    library = LibraryRepository(data["conn"]).create(str(other))
    ImageRepository(data["conn"]).upsert_image(
        library.id, "a" * 64, str(data["new"] / "a.jpg"), "a.jpg", 1, 1, None, None, None,
    )
    data["conn"].commit()
    with pytest.raises(RelinkError, match="collides"):
        relink_library(data["profile"], data["library_id"], data["new"])


@pytest.mark.parametrize("bad_kind", ["parent_traversal", "directory", "missing_root", "unknown_library"])
def test_invalid_projection_is_refused(relink_catalog, bad_kind):
    data = relink_catalog
    new = data["new"]
    library_id = data["library_id"]
    if bad_kind == "parent_traversal":
        data["conn"].execute("UPDATE images SET file_path=? WHERE id=?", (str(data["old"] / "../escape.jpg"), data["ids"]["A"]))
        data["conn"].commit()
    elif bad_kind == "directory":
        (new / "a.jpg").unlink()
        (new / "a.jpg").mkdir()
    elif bad_kind == "missing_root":
        new = new / "not-a-directory"
    else:
        library_id = 999999
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError):
        relink_library(data["profile"], library_id, new, apply=True)
    assert catalog_state(data["conn"]) == before


def test_profile_server_lock_blocks_relink(relink_catalog):
    data = relink_catalog
    # A real second process owns precisely the lease used by the server.
    code = (
        "import sys; from pathlib import Path; "
        "from backend.services.profile_lock import profile_lease; "
        "lease=profile_lease(Path(sys.argv[1])); lease.__enter__(); "
        "print('locked',flush=True); sys.stdin.readline(); lease.__exit__(None,None,None)"
    )
    with subprocess.Popen([sys.executable, "-c", code, str(data["profile"])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as process:
        try:
            assert process.stdout.readline().strip() == "locked"
            before = catalog_state(data["conn"])
            with pytest.raises(ProfileBusyError):
                relink_library(data["profile"], data["library_id"], data["new"], apply=True)
            assert catalog_state(data["conn"]) == before
            assert not (data["profile"] / "backups").exists()
        finally:
            process.communicate("release\n", timeout=10)
    # A persistent lock file is not considered ownership after its owner exits.
    assert relink_library(data["profile"], data["library_id"], data["new"])["applied"] is False


def test_source_change_during_backup_is_refused_on_transaction_revalidation(relink_catalog, monkeypatch):
    data = relink_catalog
    real_backup = library_relink.backup_catalog
    def backup_then_change(*args, **kwargs):
        result = real_backup(*args, **kwargs)
        (data["new"] / "a.jpg").write_bytes(b"changed while verifying snapshot")
        return result
    monkeypatch.setattr(library_relink, "backup_catalog", backup_then_change)
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError, match="SHA-256 mismatch"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert catalog_state(data["conn"]) == before
    bundles = list((data["profile"] / "backups").glob("relink-*"))
    assert len(bundles) == 1
    verify_backup(bundles[0])


def test_backup_failure_refuses_all_catalog_writes(relink_catalog, monkeypatch):
    data = relink_catalog
    def fail_backup(*args, **kwargs):
        raise BackupError("injected verification failure")
    monkeypatch.setattr(library_relink, "backup_catalog", fail_backup)
    before = catalog_state(data["conn"])
    with pytest.raises(BackupError, match="verification failure"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert catalog_state(data["conn"]) == before


def test_sql_failure_rolls_back_all_paths_and_preserves_verified_backup(relink_catalog):
    data = relink_catalog
    data["conn"].execute(f"""
        CREATE TRIGGER fail_relink BEFORE UPDATE OF file_path ON images
        WHEN NEW.id={data['ids']['B']} AND NEW.file_path LIKE '%new%'
        BEGIN SELECT RAISE(ABORT,'injected relink failure'); END
    """)
    data["conn"].commit()
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError, match="not partially remapped"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert catalog_state(data["conn"]) == before
    for bundle in (data["profile"] / "backups").glob("relink-*"):
        verify_backup(bundle)


def test_symlink_escape_is_refused_before_hashing_outside(relink_catalog):
    data = relink_catalog
    target = data["new"] / "a.jpg"
    outside = data["new"].with_name("outside.jpg")
    outside.write_bytes(b"matching duplicated source")
    target.unlink()
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("File symlink creation is not available on this host")
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError, match="escapes"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert catalog_state(data["conn"]) == before
    assert outside.read_bytes() == b"matching duplicated source"


@pytest.mark.skipif(os.name != "nt", reason="Windows directory-junction fallback")
def test_windows_junction_escape_is_refused_without_symlink_privileges(relink_catalog):
    data = relink_catalog
    linked_directory = data["new"] / "nested"
    (linked_directory / "b.jpg").unlink()
    linked_directory.rmdir()
    outside = data["new"].with_name("outside-directory")
    outside.mkdir()
    original = outside / "b.jpg"
    original.write_bytes(b"matching duplicated source")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(linked_directory), str(outside)],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        pytest.skip("Directory junction creation is unavailable: " + result.stderr.strip())
    assert linked_directory.is_junction()
    try:
        before = catalog_state(data["conn"])
        with pytest.raises(RelinkError, match="escapes"):
            relink_library(data["profile"], data["library_id"], data["new"], apply=True)
        assert catalog_state(data["conn"]) == before
        assert original.read_bytes() == b"matching duplicated source"
    finally:
        # Remove the junction itself, never traverse/delete its external target.
        if linked_directory.is_junction():
            linked_directory.rmdir()


def test_case_only_collision_between_mapped_images_is_refused(relink_catalog):
    data = relink_catalog
    data["conn"].execute("UPDATE images SET file_path=? WHERE id=?", (str(data["old"] / "A.jpg"), data["ids"]["B"]))
    data["conn"].commit()
    before = catalog_state(data["conn"])
    with pytest.raises(RelinkError, match="collides"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert catalog_state(data["conn"]) == before


def test_catalog_change_during_backup_requires_a_new_projection(relink_catalog, monkeypatch):
    data = relink_catalog
    original = library_relink.backup_catalog
    def backup_then_edit(*args, **kwargs):
        result = original(*args, **kwargs)
        data["conn"].execute("UPDATE libraries SET name='changed concurrently' WHERE id=?", (data["library_id"],))
        data["conn"].commit()
        return result
    monkeypatch.setattr(library_relink, "backup_catalog", backup_then_edit)
    before_paths = [row[0] for row in data["conn"].execute("SELECT file_path FROM images ORDER BY id")]
    with pytest.raises(RelinkError, match="projection changed"):
        relink_library(data["profile"], data["library_id"], data["new"], apply=True)
    assert [row[0] for row in data["conn"].execute("SELECT file_path FROM images ORDER BY id")] == before_paths


def test_nested_root_remap_avoids_transient_unique_collision(relink_catalog):
    data = relink_catalog
    old, new = data["old"], data["old"] / "nested-root"
    new.mkdir()
    source = b"matching duplicated source"
    (new / "a.jpg").write_bytes(source)
    (new / "nested/b.jpg").parent.mkdir(parents=True)
    (new / "nested/b.jpg").write_bytes(source)
    # An old row's path is another row's final path; both have equal bytes.
    data["conn"].execute("UPDATE images SET file_path=? WHERE id=?", (str(new / "a.jpg"), data["ids"]["B"]))
    data["conn"].commit()
    (new / "nested-root/a.jpg").parent.mkdir()
    (new / "nested-root/a.jpg").write_bytes(source)
    result = relink_library(data["profile"], data["library_id"], new, apply=True)
    assert result["applied"] is True
    paths = {row["id"]: row["file_path"] for row in data["conn"].execute("SELECT id,file_path FROM images")}
    assert paths[data["ids"]["A"]] == str(new / "a.jpg")
    assert paths[data["ids"]["B"]] == str(new / "nested-root/a.jpg")


def test_service_import_does_not_initialize_config_or_application():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import backend.services.library_relink; assert 'backend.config' not in sys.modules; assert 'backend.main' not in sys.modules; print('standalone')"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "standalone"
