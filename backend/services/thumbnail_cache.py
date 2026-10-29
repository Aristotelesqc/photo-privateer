"""Thumbnail generation and disk cache management."""
from __future__ import annotations

from pathlib import Path
import os
import re
import tempfile
import threading
import time
from typing import Optional
from PIL import Image, ImageOps
from backend.config import THUMBNAILS_DIR, THUMBNAIL_SIZE

# One bounded coordination primitive for the single-process desktop app. No
# per-SHA lock registry can grow with the catalog. Reentrant for read/generation.
_thumbnail_lock = threading.RLock()
_TEMP_NAME = re.compile(r"\.pp-thumb-[0-9a-f]{64}-[\w-]+\.tmp", re.ASCII)

class ThumbnailCache:
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or THUMBNAILS_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_thumbnail_path(self, sha256: str) -> Path:
        if re.fullmatch(r"[0-9a-f]{64}", sha256, re.ASCII) is None:
            raise ValueError("Invalid thumbnail content hash")
        path = self.cache_dir / f"{sha256}.webp"
        if path.resolve().parent != self.cache_dir.resolve():
            raise ValueError("Thumbnail path escapes the cache directory")
        return path

    def has_thumbnail(self, sha256: str) -> bool:
        return self.get_thumbnail_path(sha256).is_file()

    def get_or_create_thumbnail(self, original_path: str | Path, sha256: str) -> Path:
        with _thumbnail_lock:
            return self._generate_thumbnail(original_path, sha256)

    def read_thumbnail(self, sha256: str, original_path: str | Path | None = None) -> bytes:
        """Snapshot small encoded thumbnails before a concurrent purge can unlink.

        An already cached thumbnail remains readable while its source is offline.
        Only callers with a validated original path may request regeneration.
        """
        with _thumbnail_lock:
            path = self.get_thumbnail_path(sha256)
            if not path.is_file():
                if original_path is None:
                    raise FileNotFoundError("Thumbnail is not cached")
                path = self._generate_thumbnail(original_path, sha256)
            return path.read_bytes()

    def remove_thumbnail(self, sha256: str) -> None:
        with _thumbnail_lock:
            self.get_thumbnail_path(sha256).unlink(missing_ok=True)

    def cleanup_abandoned(self) -> int:
        """Inspect at most 128 entries; remove up to 16 owned temps older than a day.

        Never follow symlinks or remove other cache/user files. Concurrent local
        generation is serialized with this maintenance pass.
        """
        removed = 0
        with _thumbnail_lock, os.scandir(self.cache_dir) as entries:
            for index, entry in enumerate(entries):
                if index >= 128 or removed >= 16:
                    break
                if not _TEMP_NAME.fullmatch(entry.name) or not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    if time.time() - entry.stat(follow_symlinks=False).st_mtime >= 86400:
                        Path(entry.path).unlink(missing_ok=True)
                        removed += 1
                except OSError:
                    continue
        return removed

    def _generate_thumbnail(self, original_path: str | Path, sha256: str) -> Path:
        thumb_path = self.get_thumbnail_path(sha256)
        if thumb_path.is_file():
            return thumb_path

        orig = Path(original_path)
        if not orig.is_file():
            raise FileNotFoundError(f"Original image file not found: {orig}")

        self.cleanup_abandoned()
        temp_path = None
        try:
            # Open sources read-only. Close the temp handle before Pillow writes
            # so this works on Windows. Unique files also tolerate other processes.
            with tempfile.NamedTemporaryFile(
                dir=self.cache_dir, prefix=f".pp-thumb-{sha256}-", suffix=".tmp", delete=False,
            ) as temp:
                temp_path = Path(temp.name)
            with Image.open(orig) as source:
                img = ImageOps.exif_transpose(source)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
                img.save(temp_path, format="WEBP", quality=85)
            os.replace(temp_path, thumb_path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

        return thumb_path
