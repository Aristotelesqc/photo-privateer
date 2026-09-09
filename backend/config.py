"""Photo Privateer configuration and constants."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# Base Paths
WORKSPACE_ROOT = Path(__file__).resolve().parent.parent

# User data storage: default to ~/.photo_privateer with legacy ~/.photoscrub fallback
CUSTOM_DATA_DIR = os.environ.get("PHOTO_PRIVATEER_DATA_DIR") or os.environ.get("PHOTOSCRUB_DATA_DIR")
if CUSTOM_DATA_DIR:
    DATA_DIR = Path(CUSTOM_DATA_DIR).resolve()
else:
    canonical_dir = Path.home() / ".photo_privateer"
    legacy_dir = Path.home() / ".photoscrub"
    if not canonical_dir.exists() and legacy_dir.exists():
        DATA_DIR = canonical_dir
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        # Migrate legacy files if present
        for item in legacy_dir.iterdir():
            dest = DATA_DIR / item.name
            if not dest.exists() and item.is_file():
                try:
                    shutil.copy2(item, dest)
                except Exception:
                    pass
    else:
        DATA_DIR = canonical_dir

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Database file: canonical photo_privateer.sqlite with transparent legacy migration
DB_PATH = DATA_DIR / "photo_privateer.sqlite"
legacy_db = DATA_DIR / "photoscrub.db"
if not DB_PATH.exists() and legacy_db.exists():
    try:
        shutil.copy2(legacy_db, DB_PATH)
    except Exception:
        pass

THUMBNAILS_DIR = DATA_DIR / "thumbnails"
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

# Frontend distribution directory
FRONTEND_DIST_DIR = WORKSPACE_ROOT / "frontend" / "dist"

# Server binding - strictly 127.0.0.1 for local privacy
HOST = os.environ.get("PHOTO_PRIVATEER_HOST") or os.environ.get("PHOTOSCRUB_HOST", "127.0.0.1")
PORT = int(os.environ.get("PHOTO_PRIVATEER_PORT") or os.environ.get("PHOTOSCRUB_PORT", "8765"))

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
