"""Explicit offline-verifiable catalog bundles; originals/credentials are excluded."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import time

FORMAT_VERSION = 1
DATABASE_NAME = "photo_privateer.sqlite"
HASH = re.compile(r"[0-9a-f]{64}\Z")


class BackupError(ValueError):
    pass


def readonly_database(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    if not path.is_file():
        raise BackupError(f"Catalog not found: {path}")
    suffix = "?mode=ro" + ("&immutable=1" if immutable else "")
    conn = sqlite3.connect(path.resolve().as_uri() + suffix, uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def owned_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise BackupError("Unsafe bundle path")
    parts = PurePosixPath(relative).parts
    if (not parts or PurePosixPath(relative).as_posix() != relative
            or any(part in (".", "..", "") or ":" in part or "\\" in part for part in parts)
            or PurePosixPath(relative).is_absolute()):
        raise BackupError("Unsafe bundle path")
    current = root
    for part in parts:
        current = current / part
        if _linked(current):
            raise BackupError("Linked bundle/artifact paths are forbidden")
    if not current.resolve().is_relative_to(root.resolve()):
        raise BackupError("Artifact escaped its owned root")
    return current


def _versions(conn: sqlite3.Connection) -> list[int]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations' AND type='table'").fetchone():
        return []
    return [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]


def _compatible(versions: list[int]) -> None:
    from backend.migrations.runner import MIGRATIONS
    supported = {migration.version for migration in MIGRATIONS}
    if any(type(version) is not int or version not in supported for version in versions):
        raise BackupError("Unsupported catalog schema; use the matching/newer Photo Privateer release")
    if versions != sorted(set(versions)):
        raise BackupError("Invalid migration version list")


def _integrity(conn: sqlite3.Connection) -> None:
    if [row[0] for row in conn.execute("PRAGMA integrity_check")] != ["ok"]:
        raise BackupError("SQLite integrity check failed")
    if conn.execute("PRAGMA foreign_key_check").fetchall():
        raise BackupError("Catalog foreign-key check failed")
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"libraries", "images", "matches", "settings"}.issubset(tables):
        raise BackupError("This is not a supported Photo Privateer catalog")


def _artifacts(conn: sqlite3.Connection) -> list[dict]:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='catalog_artifacts'").fetchone():
        if 21 in _versions(conn):
            raise BackupError("Managed artifact registry is missing from this catalog schema")
        return []
    rows = [dict(row) for row in conn.execute(
        "SELECT relative_path, sha256, byte_size, kind FROM catalog_artifacts ORDER BY relative_path"
    )]
    for row in rows:
        if (not isinstance(row["relative_path"], str) or not row["relative_path"].startswith("artifacts/")
                or not isinstance(row["sha256"], str) or not HASH.fullmatch(row["sha256"])
                or type(row["byte_size"]) is not int or row["byte_size"] < 0
                or row["kind"] not in ("evidence", "case_attachment")):
            raise BackupError("Invalid managed artifact reference")
    return rows


def _space(parent: Path, required: int) -> None:
    if shutil.disk_usage(parent).free < required + 1024 * 1024:
        raise BackupError("Insufficient free space for a complete verified bundle")


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, target.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())


def _stage(destination: Path) -> Path:
    if os.path.lexists(destination):
        raise BackupError("Destination already exists; choose a new bundle/profile directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=".pp-staging-", dir=destination.parent)).resolve()


def _cleanup(stage: Path, destination: Path) -> None:
    # Only remove the uniquely created sibling staging directory, never the destination.
    if stage.parent != destination.parent.resolve() or not stage.name.startswith(".pp-staging-"):
        raise BackupError("Unexpected staging location")
    shutil.rmtree(stage)


def _publish(stage: Path, destination: Path) -> None:
    if os.path.lexists(destination):
        raise BackupError("Destination appeared during the operation; nothing was replaced")
    if stage.parent != destination.parent.resolve():
        raise BackupError("Publication must remain on the staging filesystem")
    if os.name == "nt":
        # Windows rename refuses an existing destination atomically.
        os.rename(stage, destination)
    else:
        # Linux renameat2 NOREPLACE avoids replacing an empty directory that
        # another process created after our existence check.
        import ctypes
        import errno
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            raise BackupError("Atomic no-replace directory publication unavailable on this platform")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1) != 0:
            error = ctypes.get_errno()
            if error == errno.EEXIST:
                raise BackupError("Destination appeared during publication; nothing was replaced")
            raise OSError(error, os.strerror(error))


def _entry(path: str, file: Path, kind: str) -> dict:
    return {"path": path, "sha256": digest(file), "byte_size": file.stat().st_size, "kind": kind}


def backup_catalog(db_path: Path, profile: Path, destination: Path, *, timeout: float = 120) -> dict:
    """Reserve catalog writers while snapshotting references and immutable owned blobs.

    Other connections can read throughout. Writers wait for the reservation; a
    large artifact backup should be taken after cancelling/waiting for long work.
    Two independent source connections avoid backing up a write transaction.
    """
    db_path, profile, destination = db_path.resolve(), profile.resolve(), destination.absolute()
    if not db_path.is_relative_to(profile):
        raise BackupError("Catalog must belong to the explicitly selected profile")
    if not db_path.is_file():
        raise BackupError(f"Catalog not found: {db_path}")
    stage = None
    try:
        with closing(sqlite3.connect(db_path.as_uri() + "?mode=rw", uri=True, timeout=10)) as guard:
            guard.execute("BEGIN IMMEDIATE")
            try:
                # Check under the writer reservation, before any mkdir: a
                # concurrently added library cannot turn staging into a write
                # inside an original source root.
                libraries = [Path(row[0]).resolve() for row in guard.execute("SELECT path FROM libraries")]
                if any(destination.resolve().is_relative_to(root) for root in libraries):
                    raise BackupError("Backup destination must be outside original library roots")
                stage = _stage(destination)
                with closing(readonly_database(db_path)) as source, closing(sqlite3.connect(stage / "catalog.sqlite")) as target:
                    _compatible(_versions(source))
                    refs = _artifacts(source)
                    page_size = source.execute("PRAGMA page_size").fetchone()[0]
                    page_count = source.execute("PRAGMA page_count").fetchone()[0]
                    _space(stage.parent, page_size * page_count + sum(ref["byte_size"] for ref in refs))
                    deadline = time.monotonic() + timeout
                    def progress(status, remaining, total):
                        if time.monotonic() > deadline:
                            raise BackupError("Catalog snapshot timed out; retry after catalog activity stops")
                    source.backup(target, pages=128, progress=progress, sleep=0.01)
                    target.execute("PRAGMA journal_mode=DELETE")
                    target.execute("DELETE FROM settings WHERE key='google_credentials_path'")
                    target.commit()
                    target.execute("VACUUM")  # Also remove the deleted path from free pages.
                entries = [_entry("catalog.sqlite", stage / "catalog.sqlite", "catalog")]
                with closing(readonly_database(stage / "catalog.sqlite", immutable=True)) as snapshot:
                    _integrity(snapshot)
                    versions = _versions(snapshot)
                    refs = _artifacts(snapshot)
                    libraries = [Path(row[0]).resolve() for row in snapshot.execute("SELECT path FROM libraries")]
                credentials = guard.execute("SELECT value FROM settings WHERE key='google_credentials_path'").fetchone()
                credential_paths = {
                    Path(value).resolve() for value in (
                        credentials[0] if credentials else None,
                        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
                        str(Path(os.environ.get("APPDATA", Path.home() / ".config")) / "gcloud" / "application_default_credentials.json"),
                    ) if value
                }
                for ref in refs:
                    if time.monotonic() > deadline:
                        raise BackupError("Artifact backup timed out; no complete bundle was published")
                    original = owned_file(profile, ref["relative_path"])
                    if original in credential_paths or any(original.resolve().is_relative_to(root) for root in libraries):
                        raise BackupError("Managed artifact points to credentials or an original library")
                    if not original.is_file() or original.stat().st_size != ref["byte_size"]:
                        raise BackupError("Referenced artifact is missing or has changed size")
                    if original.stat().st_nlink != 1:
                        raise BackupError("Managed artifacts must not be hardlinked to other files")
                    copied = owned_file(stage, ref["relative_path"])
                    _copy(original, copied)
                    entry = _entry(ref["relative_path"], copied, ref["kind"])
                    if entry["sha256"] != ref["sha256"]:
                        raise BackupError("Referenced artifact hash changed")
                    entries.append(entry)
            finally:
                guard.rollback()
        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_versions": versions,
            "files": entries,
            "exclusions": ["source originals", "thumbnail/remote preview caches", "credential files and google_credentials_path setting", "logs and unregistered files"],
        }
        with (stage / "manifest.json").open("x", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        verify_backup(stage)
        _publish(stage, destination)
        return manifest
    finally:
        if stage is not None and stage.exists():
            _cleanup(stage, destination)


def verify_backup(bundle: Path) -> dict:
    """Verify all payloads, exact references, SQL integrity and compatible versions."""
    if _linked(bundle) or not bundle.is_dir():
        raise BackupError("Bundle must be a real directory")
    bundle = bundle.resolve()
    manifest_path = owned_file(bundle, "manifest.json")
    if not manifest_path.is_file() or manifest_path.stat().st_size > 16 * 1024 * 1024:
        raise BackupError("Manifest missing or too large")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise BackupError("Unreadable backup manifest") from exc
    if (not isinstance(manifest, dict) or type(manifest.get("format_version")) is not int or manifest.get("format_version") != FORMAT_VERSION
            or not isinstance(manifest.get("schema_versions"), list) or not isinstance(manifest.get("files"), list)):
        raise BackupError("Unsupported or malformed backup format")
    _compatible(manifest["schema_versions"])
    files = {}
    names = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "byte_size", "kind"}:
            raise BackupError("Invalid manifest file entry")
        relative = entry["path"]
        if not isinstance(relative, str) or relative.casefold() in names:
            raise BackupError("Duplicate/invalid payload name")
        names.add(relative.casefold())
        if (relative != "catalog.sqlite" and not relative.startswith("artifacts/")) or entry["kind"] not in ("catalog", "evidence", "case_attachment"):
            raise BackupError("Unknown payload category")
        if not isinstance(entry["sha256"], str) or not HASH.fullmatch(entry["sha256"]) or type(entry["byte_size"]) is not int or entry["byte_size"] < 0:
            raise BackupError("Invalid payload size/hash")
        file = owned_file(bundle, relative)
        if not file.is_file() or file.stat().st_size != entry["byte_size"] or digest(file) != entry["sha256"]:
            raise BackupError("Payload missing, altered or truncated")
        files[relative] = entry
    actual = set()
    for path in bundle.rglob("*"):
        if _linked(path):
            raise BackupError("Linked bundle entries are forbidden")
        if path.is_file():
            actual.add(path.relative_to(bundle).as_posix())
    if actual != set(files) | {"manifest.json"} or files.get("catalog.sqlite", {}).get("kind") != "catalog":
        raise BackupError("Unexpected or missing bundle payloads")
    with closing(readonly_database(bundle / "catalog.sqlite", immutable=True)) as snapshot:
        _integrity(snapshot)
        if _versions(snapshot) != manifest["schema_versions"]:
            raise BackupError("Manifest/schema version mismatch")
        refs = _artifacts(snapshot)
        if set(files) != {"catalog.sqlite"} | {ref["relative_path"] for ref in refs}:
            raise BackupError("Manifest does not cover exact catalog artifact references")
        for ref in refs:
            if files[ref["relative_path"]] != {"path": ref["relative_path"], "sha256": ref["sha256"], "byte_size": ref["byte_size"], "kind": ref["kind"]}:
                raise BackupError("Artifact reference does not match its payload")
    return manifest


def restore_backup(bundle: Path, destination: Path) -> dict:
    """Publish a verified fresh profile; never replace an existing catalog."""
    manifest = verify_backup(bundle)
    bundle, destination = bundle.resolve(), destination.absolute()
    with closing(readonly_database(bundle / "catalog.sqlite", immutable=True)) as catalog:
        libraries = [Path(row[0]).resolve() for row in catalog.execute("SELECT path FROM libraries")]
    if any(destination.resolve().is_relative_to(root) for root in libraries):
        raise BackupError("Restored profile must be outside original library roots")
    stage = _stage(destination)
    try:
        _space(stage.parent, sum(entry["byte_size"] for entry in manifest["files"]))
        for entry in manifest["files"]:
            source = owned_file(bundle, entry["path"])
            name = DATABASE_NAME if entry["path"] == "catalog.sqlite" else entry["path"]
            copied = owned_file(stage, name)
            _copy(source, copied)
            if copied.stat().st_size != entry["byte_size"] or digest(copied) != entry["sha256"]:
                raise BackupError("Payload changed during restore")
        with closing(readonly_database(stage / DATABASE_NAME, immutable=True)) as restored:
            _integrity(restored)
            _compatible(_versions(restored))
        _publish(stage, destination)
        return manifest
    finally:
        if stage.exists():
            _cleanup(stage, destination)
