"""Filesystem scanner and photo metadata indexer."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Generator
from PIL import Image, ImageOps

from backend.config import SUPPORTED_EXTENSIONS
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.services.thumbnail_cache import ThumbnailCache

def calculate_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

class LibraryIndexer:
    def __init__(
        self,
        library_repo: LibraryRepository,
        image_repo: ImageRepository,
        thumbnail_cache: ThumbnailCache,
    ):
        self.library_repo = library_repo
        self.image_repo = image_repo
        self.thumbnail_cache = thumbnail_cache

    def _discover_files(self, root_dir: Path, recursive: bool) -> Generator[Path, None, None]:
        if not root_dir.is_dir():
            return

        if recursive:
            for root, _, files in os.walk(root_dir):
                for filename in files:
                    p = Path(root) / filename
                    if p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        yield p
        else:
            for item in root_dir.iterdir():
                if item.is_file() and item.suffix.lower() in SUPPORTED_EXTENSIONS:
                    yield item

    def index_library(self, library_id: int) -> dict[str, int]:
        lib = self.library_repo.get_by_id(library_id)
        if not lib:
            raise ValueError(f"Library with id {library_id} not found")

        root = Path(lib.path).resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Library directory does not exist: {root}")

        scanned = 0
        added_or_updated = 0
        unchanged = 0

        for file_path in self._discover_files(root, lib.recursive):
            scanned += 1
            norm_path = str(file_path.resolve())
            stat = file_path.stat()
            file_size = stat.st_size
            mtime = stat.st_mtime

            # Check if file exists in database with identical mtime and size
            existing = self.image_repo.get_by_path(norm_path)
            if existing and abs(existing.file_modified_at - mtime) < 0.001 and existing.file_size == file_size:
                unchanged += 1
                # Ensure thumbnail exists in cache
                if not self.thumbnail_cache.has_thumbnail(existing.sha256):
                    try:
                        self.thumbnail_cache.get_or_create_thumbnail(file_path, existing.sha256)
                    except Exception:
                        pass
                continue

            # Compute hash and extract dimensions safely
            sha256 = calculate_sha256(file_path)
            width: int | None = None
            height: int | None = None
            img_format: str | None = None

            try:
                with Image.open(file_path) as img:
                    img = ImageOps.exif_transpose(img)
                    width, height = img.size
                    img_format = img.format or file_path.suffix.lstrip(".").upper()
            except Exception:
                # If Pillow fails on unusual metadata, fall back cleanly
                img_format = file_path.suffix.lstrip(".").upper()

            # Pre-generate thumbnail
            try:
                self.thumbnail_cache.get_or_create_thumbnail(file_path, sha256)
            except Exception:
                pass

            # Upsert into database
            self.image_repo.upsert_image(
                library_id=library_id,
                sha256=sha256,
                file_path=norm_path,
                filename=file_path.name,
                file_size=file_size,
                file_modified_at=mtime,
                width=width,
                height=height,
                format=img_format,
            )
            added_or_updated += 1

        # Update library last indexed timestamp
        self.library_repo.update_last_indexed(library_id)

        return {
            "scanned": scanned,
            "added_or_updated": added_or_updated,
            "unchanged": unchanged,
        }
