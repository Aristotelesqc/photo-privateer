"""Photo Privateer configuration and constants."""
from __future__ import annotations

import ipaddress
import os
import shutil
from pathlib import Path

# Application Version
APP_VERSION = "1.2.0"

# Base Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

def validate_loopback_host(host_str: str) -> str:
    """Validates that a host address is strictly loopback (127.0.0.1, ::1, or localhost).
    Raises ValueError on non-loopback addresses such as 0.0.0.0 or LAN IPs.
    """
    cleaned = host_str.strip().strip("'\"")
    if cleaned.lower() == "localhost":
        return cleaned
    try:
        ip = ipaddress.ip_address(cleaned)
        if not ip.is_loopback:
            raise ValueError(
                f"Binding to non-loopback address '{cleaned}' is forbidden for security. "
                f"Photo Privateer is strictly local-first and only permits loopback (127.0.0.1, ::1)."
            )
        return cleaned
    except ValueError as e:
        if "forbidden for security" in str(e):
            raise
        raise ValueError(
            f"Invalid host address '{cleaned}': must be a valid loopback address (127.0.0.1 or ::1)."
        )

# Server binding - strictly loopback for local privacy
_RAW_HOST = os.environ.get("PHOTO_PRIVATEER_HOST", "127.0.0.1")
HOST = validate_loopback_host(_RAW_HOST)
PORT = int(os.environ.get("PHOTO_PRIVATEER_PORT", "8765"))

def get_data_dir() -> Path:
    """Returns canonical data directory, respecting PHOTO_PRIVATEER_DATA_DIR environment override."""
    custom = os.environ.get("PHOTO_PRIVATEER_DATA_DIR")
    if custom:
        p = Path(custom).resolve()
    else:
        p = (Path.home() / ".photo_privateer").resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_db_path() -> Path:
    """Returns canonical database file path."""
    return get_data_dir() / "photo_privateer.sqlite"

def get_thumbnails_dir() -> Path:
    """Returns thumbnail cache directory."""
    p = get_data_dir() / "thumbnails"
    p.mkdir(parents=True, exist_ok=True)
    return p

# Canonical locations (dynamically evaluated)
DATA_DIR = get_data_dir()
DB_PATH = get_db_path()
THUMBNAILS_DIR = get_thumbnails_dir()

# Frontend distribution directory
FRONTEND_DIST_DIR = WORKSPACE_ROOT / "frontend" / "dist"

# Supported image formats
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}

# Thumbnail resolution
THUMBNAIL_SIZE = (380, 380)

# Google Cloud Vision Web Detection Pricing Constants (as of official GCP docs, August 2026)
# https://cloud.google.com/vision/pricing
# First 1,000 units/month free. Beyond 1,000: $3.50 per 1,000 units ($0.0035 / unit).
DEFAULT_FREE_TIER_MONTHLY_UNITS = 1000
DEFAULT_UNIT_PRICE_USD = 0.0035
DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED = True

# Match Classifications
CLASS_UNREVIEWED = "UNREVIEWED"
CLASS_APPROVED = "APPROVED"
CLASS_UNAUTHORIZED = "UNAUTHORIZED"
CLASS_IRRELEVANT = "IRRELEVANT"

VALID_CLASSIFICATIONS = {
    CLASS_UNREVIEWED,
    CLASS_APPROVED,
    CLASS_UNAUTHORIZED,
    CLASS_IRRELEVANT,
}
