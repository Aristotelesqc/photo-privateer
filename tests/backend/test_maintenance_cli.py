"""Offline subprocess coverage of the explicit maintenance entry point."""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from backend.database import init_db


ROOT = Path(__file__).resolve().parents[2]


def run_cli(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # An accidental config import would create this directory or reject this host.
    env["PHOTO_PRIVATEER_DATA_DIR"] = str(tmp_path / "must-not-be-created")
    env["PHOTO_PRIVATEER_HOST"] = "external.invalid"
    return subprocess.run(
        [sys.executable, "-m", "backend.maintenance", *arguments],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )


def test_cli_backup_verify_restore_without_server_or_config(tmp_path):
    profile = tmp_path / "source"
    profile.mkdir()
    database = profile / "photo_privateer.sqlite"
    init_db(database)
    with sqlite3.connect(database) as conn:
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('retained-test-setting','review history')")
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('google_credentials_path','must-not-load.json')")
    bundle = tmp_path / "bundle"
    recovered = tmp_path / "recovered"
    for arguments, command in [
        (("backup", "--profile", str(profile), "--output", str(bundle)), "backup"),
        (("verify", str(bundle)), "verify"),
        (("restore", str(bundle), "--profile", str(recovered)), "restore"),
    ]:
        result = run_cli(tmp_path, *arguments)
        assert result.returncode == 0, result.stderr
        summary = json.loads(result.stdout)
        assert summary["status"] == "ok"
        assert summary["command"] == command
        assert summary["file_count"] == 1
        assert summary["payload_bytes"] > 0
        assert not (tmp_path / "must-not-be-created").exists()
    with sqlite3.connect(recovered / "photo_privateer.sqlite") as conn:
        assert conn.execute("SELECT value FROM settings WHERE key='retained-test-setting'").fetchone()[0] == "review history"
        assert conn.execute("SELECT value FROM settings WHERE key='google_credentials_path'").fetchone() is None
    result = run_cli(tmp_path, "restore", str(bundle), "--profile", str(recovered))
    assert result.returncode == 1
    assert "already exists" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("arguments", [(), ("backup",), ("restore", "some-bundle"), ("relink", "--library-id", "no")])
def test_cli_argument_errors_do_not_import_application(tmp_path, arguments):
    result = run_cli(tmp_path, *arguments)
    assert result.returncode == 2
    assert "error:" in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "must-not-be-created").exists()


def test_cli_missing_bundle_is_actionable_without_traceback(tmp_path):
    result = run_cli(tmp_path, "verify", str(tmp_path / "absent"))
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Maintenance failed:" in result.stderr
    assert "Traceback" not in result.stderr
    assert not (tmp_path / "must-not-be-created").exists()


def test_cli_relink_defaults_to_dry_run_then_explicit_apply(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    database = profile / "photo_privateer.sqlite"
    init_db(database)
    old_root = tmp_path / "old-photos"
    new_root = tmp_path / "new-photos"
    old_root.mkdir()
    new_root.mkdir()
    content = b"synthetic original source for offline CLI test"
    old_source = old_root / "photo.jpg"
    new_source = new_root / "photo.jpg"
    old_source.write_bytes(content)
    new_source.write_bytes(content)
    with sqlite3.connect(database) as conn:
        library_id = conn.execute(
            "INSERT INTO libraries(path,name,created_at) VALUES (?,?,?)",
            (str(old_root), "CLI fixture", "2026-10-04"),
        ).lastrowid
        image_id = conn.execute(
            "INSERT INTO images(library_id,sha256,file_path,filename,file_size,file_modified_at,indexed_at,last_seen_on_disk) VALUES (?,?,?,?,?,?,?,?)",
            (library_id, hashlib.sha256(content).hexdigest(), str(old_source), "photo.jpg", len(content), 0, "2026-10-04", "2026-10-04"),
        ).lastrowid
    arguments = ("relink", "--profile", str(profile), "--library-id", str(library_id), "--new-root", str(new_root))
    dry_run = run_cli(tmp_path, *arguments)
    assert dry_run.returncode == 0, dry_run.stderr
    summary = json.loads(dry_run.stdout)
    assert summary["applied"] is False
    assert summary["backup_path"] is None
    assert summary["present_count"] == 1
    assert "changes" not in summary
    assert not (profile / "backups").exists()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT path FROM libraries WHERE id=?", (library_id,)).fetchone()[0] == str(old_root)
        assert conn.execute("SELECT file_path FROM images WHERE id=?", (image_id,)).fetchone()[0] == str(old_source)
    applied = run_cli(tmp_path, *arguments, "--apply")
    assert applied.returncode == 0, applied.stderr
    summary = json.loads(applied.stdout)
    assert summary["applied"] is True
    assert Path(summary["backup_path"]).is_dir()
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT path FROM libraries WHERE id=?", (library_id,)).fetchone()[0] == str(new_root)
        assert conn.execute("SELECT file_path FROM images WHERE id=?", (image_id,)).fetchone()[0] == str(new_source)
    assert old_source.read_bytes() == new_source.read_bytes() == content
    assert not (tmp_path / "must-not-be-created").exists()
