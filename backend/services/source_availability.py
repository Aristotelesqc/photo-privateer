"""Read-only path availability shared by catalog filters and scan selection."""
import os
from pathlib import Path


def source_path_available(raw_path: str, indexed_present: bool, library_root: str | None) -> bool:
    if not indexed_present or not library_root:
        return False
    try:
        target = Path(raw_path).resolve()
        root = Path(library_root).resolve()
        return target.is_file() and os.path.commonpath([
            os.path.normcase(str(target)), os.path.normcase(str(root))
        ]) == os.path.normcase(str(root))
    except (OSError, ValueError, RuntimeError):
        return False
