"""Thumbnail generation and disk cache management."""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps
from backend.config import THUMBNAILS_DIR, THUMBNAIL_SIZE

class ThumbnailCache:
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or THUMBNAILS_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_thumbnail_path(self, sha256: str) -> Path:
        return self.cache_dir / f"{sha256}.webp"

    def has_thumbnail(self, sha256: str) -> bool:
        return self.get_thumbnail_path(sha256).is_file()

    def get_or_create_thumbnail(self, original_path: str | Path, sha256: str) -> Path:
        thumb_path = self.get_thumbnail_path(sha256)
        if thumb_path.is_file():
            return thumb_path

        orig = Path(original_path)
        if not orig.is_file():
            raise FileNotFoundError(f"Original image file not found: {orig}")

        # Open in read-only mode and transpose EXIF
        with Image.open(orig) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            
            # Save as optimized WebP
            temp_path = self.cache_dir / f"{sha256}.tmp.webp"
            img.save(temp_path, format="WEBP", quality=85)
            temp_path.replace(thumb_path)

        return thumb_path
