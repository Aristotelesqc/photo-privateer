"""Verified bundle recovery on synthetic profiles; no provider or user data."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from backend.database import get_connection, init_db
from backend.repositories.group_repo import PhotoGroupRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.usage_repo import UsageRepository
from backend.services import catalog_backup as backup
from backend.services.profile_lock import ProfileBusyError, profile_lease


def register(conn, profile, relative, content, kind="evidence", *, write=True):
    file = profile / relative
    if write:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content)
    conn.execute(
        "INSERT INTO catalog_artifacts (id, relative_path, sha256, byte_size, kind, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (relative, relative, hashlib.sha256(content).hexdigest(), len(content), kind, "2026-01-01T00:00:00Z"),
    )
    conn.commit()
    return file


@pytest.fixture
def catalog(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    db = profile / backup.DATABASE_NAME
    init_db(db)
    conn = get_connection(db)
    libraries = LibraryRepository(conn)
    images = ImageRepository(conn)
    matches = MatchRepository(conn)
    image_ids = []
    originals = {}
    match_ids = []
    for position, classification in enumerate(("APPROVED", "UNAUTHORIZED")):
        root = profile / "originals" / str(position)
        root.mkdir(parents=True)
        source = root / f"source-{position}.png"
        content = b"synthetic source photograph " + bytes([position])
        source.write_bytes(content)
        originals[source] = content
        library = libraries.create(str(root), name=f"Source {position}")
        image = images.upsert_image(
            library.id, hashlib.sha256(content).hexdigest(), str(source), source.name,
            len(content), source.stat().st_mtime, 16, 16, "PNG", project="Client", dhash="a5a55a5a0ff0f00f",
        )
        image_ids.append(image.id)
        match, _ = matches.upsert_match(
            image.id, None, "backup.example", "FULL", "mock", source_kind="PAGE",
            page_url="https://backup.example/use", candidate_image_url="https://backup.example/photo.jpg",
        )
        matches.update_classification_and_notes(match.id, classification=classification, notes=f"Review {position}")
        conn.execute("UPDATE matches SET first_seen_at = ? WHERE id = ?", (f"2000-01-01T00:00:0{position}Z", match.id))
        conn.commit()
        match_ids.append(match.id)
    group = PhotoGroupRepository(conn).create_group(image_ids, preferred_image_id=image_ids[1])
    matches.update_classification_and_notes(match_ids[0], classification="IRRELEVANT", notes="Preserve scoped group review", acknowledged=True)
    usage = UsageRepository(conn)
    session = usage.create_scan_session("mock", 1)
    usage.record_scan_item(session.id, image_ids[0], "SUCCESS", matches_found=1)
    usage.record_call("mock", "2026-01", session.id, image_ids[0], 1, 1, 0, "SUCCESS", 0)
    usage.update_scan_session_progress(session.id, 1, 1, 0, status="COMPLETED")
    secret = profile / "credentials.json"
    secret.write_bytes(b"synthetic private key must never leave profile")
    conn.execute("INSERT INTO settings (key, value) VALUES ('google_credentials_path', ?)", (str(secret),))
    conn.execute("INSERT INTO settings (key, value) VALUES ('unit_price_usd', '0.0035')")
    conn.commit()
    (profile / "thumbnails").mkdir()
    (profile / "thumbnails" / "cached.webp").write_bytes(b"cached photo")
    (profile / "runtime.log").write_bytes(b"private log")
    (profile / "unregistered.txt").write_bytes(b"unregistered private file")
    yield SimpleNamespace(profile=profile, db=db, conn=conn, originals=originals, secret=secret, group=group.id, image_ids=image_ids, match_ids=match_ids)
    conn.close()


def bundle(catalog, tmp_path):
    destination = tmp_path / "bundle"
    backup.backup_catalog(catalog.db, catalog.profile, destination)
    return destination


def manifest_update(directory, mutate):
    path = directory / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    mutate(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def refresh_catalog_entry(directory):
    payload = directory / "catalog.sqlite"
    manifest_update(directory, lambda value: value["files"].__setitem__(0, {
        "path": "catalog.sqlite", "sha256": backup.digest(payload), "byte_size": payload.stat().st_size, "kind": "catalog",
    }))


def table_rows(conn):
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {table: [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
            for table in tables if table != "settings"}


def assert_no_stage(parent):
    assert list(parent.glob(".pp-staging-*")) == []


def test_roundtrip_keeps_exact_history_and_registered_artifacts_excludes_private_files(catalog, tmp_path, monkeypatch):
    evidence = register(catalog.conn, catalog.profile, "artifacts/evidence/capture.bin", b"synthetic immutable page evidence")
    attachment = register(catalog.conn, catalog.profile, "artifacts/cases/letter.txt", b"synthetic case attachment", "case_attachment")
    expected = table_rows(catalog.conn)
    # Recovery must not inspect local keys, refresh auth or instantiate providers.
    monkeypatch.setattr("backend.repositories.settings_repo.SettingsRepository.get_app_settings", lambda self: pytest.fail("Authentication/settings inspection during backup"))
    monkeypatch.setattr("backend.providers.get_provider", lambda *a, **kw: pytest.fail("Provider instantiated during recovery"))
    directory = bundle(catalog, tmp_path)
    manifest = backup.verify_backup(directory)
    assert str(catalog.secret).encode("utf-8") not in (directory / "catalog.sqlite").read_bytes()
    assert {entry["path"] for entry in manifest["files"]} == {
        "catalog.sqlite", "artifacts/evidence/capture.bin", "artifacts/cases/letter.txt",
    }
    assert {path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file()} == {
        "manifest.json", "catalog.sqlite", "artifacts/evidence/capture.bin", "artifacts/cases/letter.txt",
    }
    recovered = tmp_path / "recovered-profile"
    backup.restore_backup(directory, recovered)
    with closing(backup.readonly_database(recovered / backup.DATABASE_NAME, immutable=True)) as restored:
        assert table_rows(restored) == expected
        assert restored.execute("SELECT value FROM settings WHERE key='unit_price_usd'").fetchone()[0] == "0.0035"
        assert restored.execute("SELECT 1 FROM settings WHERE key='google_credentials_path'").fetchone() is None
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
    assert catalog.conn.execute("SELECT value FROM settings WHERE key='google_credentials_path'").fetchone()[0] == str(catalog.secret)
    assert (recovered / "artifacts/evidence/capture.bin").read_bytes() == evidence.read_bytes()
    assert (recovered / "artifacts/cases/letter.txt").read_bytes() == attachment.read_bytes()
    assert all(path.read_bytes() == content for path, content in catalog.originals.items())
    assert catalog.secret.read_bytes() == b"synthetic private key must never leave profile"
    assert_no_stage(tmp_path)


def test_snapshot_includes_committed_wal_pages_without_checkpoint(catalog, tmp_path):
    catalog.conn.execute("PRAGMA wal_autocheckpoint=0")
    catalog.conn.execute("INSERT INTO settings (key, value) VALUES ('wal_sentinel', 'committed-wal-only')")
    catalog.conn.commit()
    wal = Path(str(catalog.db) + "-wal")
    assert wal.is_file() and wal.stat().st_size > 0
    directory = bundle(catalog, tmp_path)
    with closing(backup.readonly_database(directory / "catalog.sqlite", immutable=True)) as snapshot:
        assert snapshot.execute("SELECT value FROM settings WHERE key='wal_sentinel'").fetchone()[0] == "committed-wal-only"
        assert snapshot.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    assert not (directory / "catalog.sqlite-wal").exists()


def test_live_readers_continue_while_snapshot_reserves_writers_then_releases_them(catalog, tmp_path, monkeypatch):
    register(catalog.conn, catalog.profile, "artifacts/page.bin", b"owned immutable evidence")
    expected = table_rows(catalog.conn)
    copying = threading.Event()
    release = threading.Event()
    failures = []
    copy = backup._copy
    def paused_copy(source, target):
        copying.set()
        if not release.wait(10):
            raise RuntimeError("Test did not release artifact copying")
        copy(source, target)
    monkeypatch.setattr(backup, "_copy", paused_copy)
    directory = tmp_path / "live-bundle"
    def run_backup():
        try:
            backup.backup_catalog(catalog.db, catalog.profile, directory)
        except BaseException as exc:
            failures.append(exc)
    worker = threading.Thread(target=run_backup, name="synthetic-backup")
    worker.start()
    try:
        assert copying.wait(10), failures
        with closing(backup.readonly_database(catalog.db)) as reader:
            assert table_rows(reader) == expected
        with closing(sqlite3.connect(catalog.db, timeout=0)) as writer:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                writer.execute("UPDATE matches SET notes='concurrent edit' WHERE id=?", (catalog.match_ids[0],))
            writer.rollback()
            release.set()
            worker.join(10)
            assert not worker.is_alive()
            assert failures == []
            writer.execute("UPDATE matches SET notes='edit after backup' WHERE id=?", (catalog.match_ids[0],))
            writer.commit()
        with closing(backup.readonly_database(directory / "catalog.sqlite", immutable=True)) as snapshot:
            assert table_rows(snapshot) == expected
        assert catalog.conn.execute("SELECT notes FROM matches WHERE id=?", (catalog.match_ids[0],)).fetchone()[0] == "edit after backup"
    finally:
        release.set()
        worker.join(10)
    assert not worker.is_alive()
    assert_no_stage(tmp_path)


def test_legacy_catalog_without_artifact_registry_remains_backupable(catalog, tmp_path):
    catalog.conn.execute("DROP TABLE catalog_artifacts")
    catalog.conn.execute("DELETE FROM schema_migrations WHERE version=21")
    catalog.conn.commit()
    assert [entry["path"] for entry in backup.verify_backup(bundle(catalog, tmp_path))["files"]] == ["catalog.sqlite"]


def test_catalog_claiming_artifact_migration_cannot_silently_omit_lost_registry(catalog, tmp_path):
    assert catalog.conn.execute("SELECT 1 FROM schema_migrations WHERE version=21").fetchone()
    register(catalog.conn, catalog.profile, "artifacts/page.bin", b"registered history")
    catalog.conn.execute("DROP TABLE catalog_artifacts")
    catalog.conn.commit()
    destination = tmp_path / "refused-missing-registry"
    with pytest.raises(backup.BackupError):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert not destination.exists()
    assert_no_stage(tmp_path)


@pytest.mark.parametrize("damage", ["missing", "truncated", "modified"])
def test_registered_missing_or_changed_artifact_prevents_publication(catalog, tmp_path, damage):
    artifact = register(catalog.conn, catalog.profile, "artifacts/page.bin", b"original evidence")
    if damage == "missing":
        artifact.unlink()
    else:
        artifact.write_bytes(b"short" if damage == "truncated" else b"different content")
    destination = tmp_path / "failed-bundle"
    with pytest.raises(backup.BackupError, match="missing|size|hash"):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert not destination.exists()
    assert_no_stage(tmp_path)


@pytest.mark.parametrize("damage", ["missing", "truncated", "modified", "unexpected"])
def test_verify_rejects_damaged_or_unregistered_bundle(catalog, tmp_path, damage):
    register(catalog.conn, catalog.profile, "artifacts/page.bin", b"original evidence")
    directory = bundle(catalog, tmp_path)
    artifact = directory / "artifacts/page.bin"
    if damage == "missing":
        artifact.unlink()
    elif damage == "unexpected":
        (directory / "unlisted-secret.json").write_bytes(b"unexpected")
    else:
        artifact.write_bytes(b"short" if damage == "truncated" else b"different content")
    with pytest.raises(backup.BackupError, match="Payload|Unexpected"):
        backup.verify_backup(directory)
    destination = tmp_path / "failed-restore"
    with pytest.raises(backup.BackupError):
        backup.restore_backup(directory, destination)
    assert not destination.exists()
    assert_no_stage(tmp_path)


@pytest.mark.parametrize("change", ["future_format", "future_schema", "duplicate", "traversal", "absolute", "wrong_kind"])
def test_verify_rejects_invalid_manifest_before_restoration(catalog, tmp_path, change):
    directory = bundle(catalog, tmp_path)
    def mutate(value):
        if change == "future_format":
            value["format_version"] += 100
        elif change == "future_schema":
            value["schema_versions"].append(999999)
        elif change == "duplicate":
            value["files"].append(dict(value["files"][0]))
        elif change == "wrong_kind":
            value["files"][0]["kind"] = "evidence"
        else:
            value["files"][0]["path"] = "artifacts/../../outside" if change == "traversal" else "/catalog.sqlite"
    manifest_update(directory, mutate)
    with pytest.raises(backup.BackupError):
        backup.verify_backup(directory)
    destination = tmp_path / "refused-profile"
    with pytest.raises(backup.BackupError):
        backup.restore_backup(directory, destination)
    assert not destination.exists()


def test_future_sql_schema_and_manifest_mismatch_are_rejected(catalog, tmp_path):
    directory = bundle(catalog, tmp_path)
    with closing(sqlite3.connect(directory / "catalog.sqlite")) as conn:
        conn.execute("INSERT INTO schema_migrations VALUES (999999, 'future_unknown', '2026-01-01')")
        conn.commit()
    refresh_catalog_entry(directory)
    with pytest.raises(backup.BackupError, match="version mismatch|Unsupported"):
        backup.verify_backup(directory)
    manifest_update(directory, lambda value: value["schema_versions"].append(999999))
    with pytest.raises(backup.BackupError, match="Unsupported catalog schema"):
        backup.verify_backup(directory)


def test_foreign_key_corruption_even_with_matching_file_hash_is_rejected(catalog, tmp_path):
    directory = bundle(catalog, tmp_path)
    with closing(sqlite3.connect(directory / "catalog.sqlite")) as conn:
        conn.execute("UPDATE matches SET image_id=999999 WHERE id=?", (catalog.match_ids[0],))
        conn.commit()
    refresh_catalog_entry(directory)
    with pytest.raises(backup.BackupError, match="foreign-key"):
        backup.verify_backup(directory)


@pytest.mark.parametrize("operation", ["backup", "restore"])
@pytest.mark.parametrize("failure", ["space", "copy", "interruption", "publish_race"])
def test_failures_never_publish_partial_profile_or_replace_racing_destination(catalog, tmp_path, monkeypatch, operation, failure):
    register(catalog.conn, catalog.profile, "artifacts/page.bin", b"owned evidence")
    directory = bundle(catalog, tmp_path) if operation == "restore" else None
    destination = tmp_path / "destination"
    sentinel = b"unrelated destination must remain intact"
    if failure == "space":
        monkeypatch.setattr(backup.shutil, "disk_usage", lambda path: SimpleNamespace(free=0))
    elif failure in ("copy", "interruption"):
        def fail_copy(source, target):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"partial bytes")
            if failure == "interruption":
                raise KeyboardInterrupt("synthetic interruption")
            raise OSError("synthetic disk write failed")
        monkeypatch.setattr(backup, "_copy", fail_copy)
    else:
        publish = backup._publish
        def raced_publish(stage, target):
            target.mkdir()
            (target / "existing.txt").write_bytes(sentinel)
            publish(stage, target)
        monkeypatch.setattr(backup, "_publish", raced_publish)
    expected = KeyboardInterrupt if failure == "interruption" else (backup.BackupError, OSError)
    with pytest.raises(expected):
        if operation == "backup":
            backup.backup_catalog(catalog.db, catalog.profile, destination)
        else:
            backup.restore_backup(directory, destination)
    if failure == "publish_race":
        assert (destination / "existing.txt").read_bytes() == sentinel
        assert list(destination.iterdir()) == [destination / "existing.txt"]
    else:
        assert not destination.exists()
    assert_no_stage(tmp_path)
    assert all(path.read_bytes() == content for path, content in catalog.originals.items())


@pytest.mark.parametrize("destination_kind", ["file", "directory"])
def test_existing_backup_and_restore_destinations_are_untouched(catalog, tmp_path, destination_kind):
    directory = bundle(catalog, tmp_path)
    destination = tmp_path / "existing"
    sentinel = destination if destination_kind == "file" else destination / "history.txt"
    if destination_kind == "directory":
        destination.mkdir()
    sentinel.write_bytes(b"existing user history")
    for run in (lambda: backup.backup_catalog(catalog.db, catalog.profile, destination),
                lambda: backup.restore_backup(directory, destination)):
        with pytest.raises(backup.BackupError, match="Destination already exists"):
            run()
        assert sentinel.read_bytes() == b"existing user history"
    assert_no_stage(tmp_path)


def test_timeout_prevents_complete_publication(catalog, tmp_path):
    destination = tmp_path / "timed-out"
    with pytest.raises(backup.BackupError, match="timed out"):
        backup.backup_catalog(catalog.db, catalog.profile, destination, timeout=-1)
    assert not destination.exists()
    assert_no_stage(tmp_path)


def test_registered_credentials_setting_is_never_copied(catalog, tmp_path):
    credential = register(catalog.conn, catalog.profile, "artifacts/credentials.json", b"synthetic credential")
    catalog.conn.execute("UPDATE settings SET value=? WHERE key='google_credentials_path'", (str(credential),))
    catalog.conn.commit()
    destination = tmp_path / "refused"
    with pytest.raises(backup.BackupError, match="credentials"):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert not destination.exists()
    assert credential.read_bytes() == b"synthetic credential"
    assert_no_stage(tmp_path)


def test_environment_credentials_reference_is_never_copied(catalog, tmp_path, monkeypatch):
    credential = register(catalog.conn, catalog.profile, "artifacts/environment-key.json", b"synthetic environment credential")
    catalog.conn.execute("DELETE FROM settings WHERE key='google_credentials_path'")
    catalog.conn.commit()
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", str(credential))
    destination = tmp_path / "refused-env-key"
    with pytest.raises(backup.BackupError, match="credential"):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert not destination.exists()
    assert_no_stage(tmp_path)


def test_hardlinked_credentials_cannot_hide_as_managed_evidence(catalog, tmp_path):
    alias = catalog.profile / "artifacts/innocent-evidence.bin"
    alias.parent.mkdir()
    try:
        os.link(catalog.secret, alias)
    except OSError as exc:
        pytest.skip(f"Hard links unavailable: {exc}")
    register(catalog.conn, catalog.profile, "artifacts/innocent-evidence.bin", catalog.secret.read_bytes(), write=False)
    destination = tmp_path / "refused-hardlink"
    with pytest.raises(backup.BackupError, match="credential|link|owned"):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert not destination.exists()
    assert_no_stage(tmp_path)


def test_managed_original_library_content_is_rejected(catalog, tmp_path):
    artifact = register(catalog.conn, catalog.profile, "artifacts/photographs/photo.bin", b"original photograph")
    LibraryRepository(catalog.conn).create(str(artifact.parent), name="Originals inside artifacts")
    destination = tmp_path / "refused-original"
    with pytest.raises(backup.BackupError, match="original library"):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert not destination.exists()
    assert artifact.read_bytes() == b"original photograph"


def test_backup_destination_inside_original_library_is_rejected_before_staging(catalog):
    original = next(iter(catalog.originals))
    root = original.parent
    before = {path.name for path in root.iterdir()}
    destination = root / "new-backup-parent" / "bundle"
    with pytest.raises(backup.BackupError, match="original|library"):
        backup.backup_catalog(catalog.db, catalog.profile, destination)
    assert {path.name for path in root.iterdir()} == before
    assert not destination.parent.exists()
    assert original.read_bytes() == catalog.originals[original]


def test_restore_destination_inside_original_library_is_rejected_before_staging(catalog, tmp_path):
    directory = bundle(catalog, tmp_path)
    original = next(iter(catalog.originals))
    root = original.parent
    before = {path.name for path in root.iterdir()}
    destination = root / "new-restore-parent" / "profile"
    with pytest.raises(backup.BackupError, match="original|library"):
        backup.restore_backup(directory, destination)
    assert {path.name for path in root.iterdir()} == before
    assert not destination.parent.exists()
    assert original.read_bytes() == catalog.originals[original]


def test_atomic_publication_does_not_replace_empty_destination_created_after_final_check(tmp_path, monkeypatch):
    stage = tmp_path / ".pp-staging-race"
    stage.mkdir()
    (stage / "catalog.sqlite").write_bytes(b"complete synthetic staged catalog")
    destination = tmp_path / "racing-empty-directory"
    lexists = backup.os.path.lexists
    def race_after_check(path):
        exists = lexists(path)
        if Path(path) == destination and not exists:
            destination.mkdir()
        return exists
    monkeypatch.setattr(backup.os.path, "lexists", race_after_check)
    with pytest.raises((backup.BackupError, OSError)):
        backup._publish(stage, destination)
    assert destination.is_dir() and list(destination.iterdir()) == []
    assert (stage / "catalog.sqlite").read_bytes() == b"complete synthetic staged catalog"


@pytest.mark.parametrize("operation", ["backup", "verify"])
def test_symlink_payload_cannot_escape_owned_profile_or_bundle(catalog, tmp_path, operation):
    content = b"synthetic evidence"
    artifact = register(catalog.conn, catalog.profile, "artifacts/page.bin", content)
    directory = bundle(catalog, tmp_path) if operation == "verify" else None
    alias = directory / "artifacts/page.bin" if directory else artifact
    target = tmp_path / "outside.bin"
    target.write_bytes(content)
    alias.unlink()
    try:
        alias.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable: {exc}")
    with pytest.raises(backup.BackupError, match="Linked"):
        if directory:
            backup.verify_backup(directory)
        else:
            backup.backup_catalog(catalog.db, catalog.profile, tmp_path / "refused-symlink")
    assert target.read_bytes() == content
    assert_no_stage(tmp_path)


def test_profile_lock_refuses_second_owner_releases_after_exception_and_persistent_file(catalog):
    with pytest.raises(RuntimeError, match="synthetic"):
        with profile_lease(catalog.profile):
            with pytest.raises(ProfileBusyError, match="in use"):
                with profile_lease(catalog.profile):
                    pytest.fail("Second owner acquired the same profile")
            raise RuntimeError("synthetic owner crash")
    assert (catalog.profile / ".profile.lock").is_file()
    with profile_lease(catalog.profile):
        pass  # An existing lock file is not itself ownership.


def test_profile_lock_is_cross_process_and_recovers_when_owner_exits(catalog):
    code = """import sys
from pathlib import Path
from backend.services.profile_lock import profile_lease, ProfileBusyError
try:
    with profile_lease(Path(sys.argv[1])):
        print('acquired', flush=True)
except ProfileBusyError:
    print('busy', flush=True)
    raise SystemExit(23)
"""
    root = Path(__file__).resolve().parents[2]
    with profile_lease(catalog.profile):
        denied = subprocess.run([sys.executable, "-c", code, str(catalog.profile)], cwd=root, capture_output=True, text=True, timeout=15)
    assert denied.returncode == 23, denied.stderr
    assert denied.stdout.strip() == "busy"
    acquired = subprocess.run([sys.executable, "-c", code, str(catalog.profile)], cwd=root, capture_output=True, text=True, timeout=15)
    assert acquired.returncode == 0, acquired.stderr
    assert acquired.stdout.strip() == "acquired"


def test_profile_lock_is_released_by_os_after_abrupt_process_exit(catalog):
    code = """import os, sys
from pathlib import Path
from backend.services.profile_lock import profile_lease
with profile_lease(Path(sys.argv[1])):
    print('owned', flush=True)
    os._exit(42)
"""
    crashed = subprocess.run([sys.executable, "-c", code, str(catalog.profile)],
                             cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=15)
    assert crashed.returncode == 42, crashed.stderr
    assert crashed.stdout.strip() == "owned"
    with profile_lease(catalog.profile):
        pass
