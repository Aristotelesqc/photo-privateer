"""Photo Privateer Semantic Version Bump Utility.

Updates application version across all canonical project files:
- backend/config.py (APP_VERSION)
- frontend/src/version.ts (APP_VERSION)
- frontend/package.json (version)
- frontend/package-lock.json (version)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def get_current_version() -> str:
    pkg_path = WORKSPACE_ROOT / "frontend" / "package.json"
    if not pkg_path.exists():
        raise FileNotFoundError(f"Missing {pkg_path}")
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    return data.get("version", "0.0.0")


def compute_next_version(current: str, part: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(.*)$", current)
    if not match:
        raise ValueError(f"Current version '{current}' is not a valid semver.")
    major, minor, patch, suffix = match.groups()
    major, minor, patch = int(major), int(minor), int(patch)
    if part == "major":
        return f"{major + 1}.0.0"
    elif part == "minor":
        return f"{major}.{minor + 1}.0"
    elif part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"Unknown part: {part}")


def update_backend_config(new_version: str) -> None:
    config_path = WORKSPACE_ROOT / "backend" / "config.py"
    content = config_path.read_text(encoding="utf-8")
    new_content = re.sub(
        r'APP_VERSION\s*=\s*["\'][^"\']+["\']',
        f'APP_VERSION = "{new_version}"',
        content,
    )
    config_path.write_text(new_content, encoding="utf-8")


def update_frontend_version_ts(new_version: str) -> None:
    ts_path = WORKSPACE_ROOT / "frontend" / "src" / "version.ts"
    ts_path.write_text(
        f"export const APP_VERSION = '{new_version}';\n",
        encoding="utf-8",
    )


def update_package_json(new_version: str) -> None:
    pkg_path = WORKSPACE_ROOT / "frontend" / "package.json"
    data = json.loads(pkg_path.read_text(encoding="utf-8"))
    data["version"] = new_version
    pkg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def update_package_lock_json(new_version: str) -> None:
    lock_path = WORKSPACE_ROOT / "frontend" / "package-lock.json"
    if not lock_path.exists():
        return
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    if "version" in data:
        data["version"] = new_version
    if "packages" in data and "" in data["packages"]:
        data["packages"][""]["version"] = new_version
    lock_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump version across Photo Privateer backend and frontend."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("version", nargs="?", help="Target semantic version (e.g. 1.0.1)")
    group.add_argument("--patch", action="store_true", help="Bump patch version (e.g. 1.0.0 -> 1.0.1)")
    group.add_argument("--minor", action="store_true", help="Bump minor version (e.g. 1.0.0 -> 1.1.0)")
    group.add_argument("--major", action="store_true", help="Bump major version (e.g. 1.0.0 -> 2.0.0)")

    args = parser.parse_args()
    current = get_current_version()

    if args.patch:
        target = compute_next_version(current, "patch")
    elif args.minor:
        target = compute_next_version(current, "minor")
    elif args.major:
        target = compute_next_version(current, "major")
    else:
        target = args.version.lstrip("v")
        if not re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", target):
            print(f"Error: '{target}' is not a valid semantic version.", file=sys.stderr)
            return 1

    print(f"Bumping Photo Privateer version: {current} -> {target}")

    update_backend_config(target)
    update_frontend_version_ts(target)
    update_package_json(target)
    update_package_lock_json(target)

    print(f"Successfully updated version to {target} across all project files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
