"""Explicit local catalog maintenance, independent of application startup."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Sequence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Back up, verify, restore or relink a local Photo Privateer catalog."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="Create a verified bundle in a new directory")
    backup.add_argument("--profile", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="Verify a bundle without restoring or migrating it")
    verify.add_argument("bundle", type=Path)
    restore = commands.add_parser("restore", help="Restore a bundle into a new profile directory")
    restore.add_argument("bundle", type=Path)
    restore.add_argument("--profile", type=Path, required=True)
    relink = commands.add_parser("relink", help="Validate a relocated library; use --apply to save")
    relink.add_argument("--profile", type=Path, required=True)
    relink.add_argument("--library-id", type=int, required=True)
    relink.add_argument("--new-root", type=Path, required=True)
    relink.add_argument("--apply", action="store_true")
    return parser


def _bundle_summary(command: str, location: Path, manifest: dict) -> dict:
    return {
        "command": command,
        "status": "ok",
        "path": str(location.absolute()),
        "format_version": manifest["format_version"],
        "schema_versions": manifest["schema_versions"],
        "file_count": len(manifest["files"]),
        "payload_bytes": sum(entry["byte_size"] for entry in manifest["files"]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "relink":
            from backend.services.library_relink import relink_library

            result = relink_library(
                args.profile, args.library_id, args.new_root, apply=args.apply
            )
            summary = {"command": "relink", "status": "ok"}
            summary.update({key: value for key, value in result.items() if key in {
                "library_id", "applied", "image_count", "present_count", "missing_count",
                "archived_alias_count", "backup_path", "old_root", "new_root",
            }})
        else:
            from backend.services.catalog_backup import (
                DATABASE_NAME, backup_catalog, restore_backup, verify_backup,
            )

            if args.command == "backup":
                manifest = backup_catalog(args.profile / DATABASE_NAME, args.profile, args.output)
                location = args.output
            elif args.command == "verify":
                manifest = verify_backup(args.bundle)
                location = args.bundle
            else:
                manifest = restore_backup(args.bundle, args.profile)
                location = args.profile
            summary = _bundle_summary(args.command, location, manifest)
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(f"Maintenance failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
