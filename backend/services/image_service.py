"""Safe local image access service with strict containment validation."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from fastapi import HTTPException
from backend.repositories.library_repo import LibraryRepository

class ImageService:
    def __init__(self, library_repo: LibraryRepository):
        self.library_repo = library_repo

    def validate_and_resolve_image_path(self, raw_path: str) -> Path:
        """Validates that a file path exists and is strictly contained within an enabled library."""
        target = Path(raw_path).resolve()
        if not target.is_file():
            raise HTTPException(status_code=404, detail="Image file not found on disk")

        # Check against all enabled library roots
        libraries = self.library_repo.list_libraries()
        target_str = str(target)
        
        is_contained = False
        for lib in libraries:
            if not lib.enabled or lib.is_archived:
                continue
            lib_root = str(Path(lib.path).resolve())
            try:
                # commonpath raises ValueError if on different drives
                common = os.path.commonpath([lib_root, target_str])
                if common == lib_root:
                    is_contained = True
                    break
            except ValueError:
                continue

        if not is_contained:
            raise HTTPException(status_code=403, detail="Access denied: file is not within an enabled library folder")

        return target
