"""Libraries router."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from backend.models import LibraryCreate, LibraryUpdate, LibraryOut
from backend.repositories.library_repo import LibraryRepository
from backend.services.library_indexer import LibraryIndexer
from backend.api.deps import get_library_repo, get_library_indexer

router = APIRouter(prefix="/api/libraries", tags=["libraries"])

@router.get("", response_model=list[LibraryOut])
def list_libraries(repo: LibraryRepository = Depends(get_library_repo)):
    return repo.list_libraries()

@router.post("/browse-folder")
def browse_folder():
    """Attempt to open a local native folder picker on the desktop host."""
    selected_path = None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="Select Photograph Folder")
        root.destroy()
        if selected:
            selected_path = str(Path(selected).resolve())
    except Exception:
        pass
    return {"path": selected_path}

@router.post("", response_model=LibraryOut)
def create_library(payload: LibraryCreate, repo: LibraryRepository = Depends(get_library_repo)):
    p = Path(payload.path).resolve()
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory does not exist: {payload.path}")
    
    existing = repo.get_by_path(str(p))
    if existing:
        raise HTTPException(status_code=409, detail="A library with this path already exists")

    return repo.create(path=str(p), name=payload.name, recursive=payload.recursive)

@router.patch("/{library_id}", response_model=LibraryOut)
def update_library(library_id: int, payload: LibraryUpdate, repo: LibraryRepository = Depends(get_library_repo)):
    lib = repo.get_by_id(library_id)
    if not lib:
        raise HTTPException(status_code=404, detail="Library not found")
    return repo.update(library_id, name=payload.name, enabled=payload.enabled, recursive=payload.recursive)

@router.delete("/{library_id}")
def delete_library(library_id: int, repo: LibraryRepository = Depends(get_library_repo)):
    success = repo.delete(library_id)
    if not success:
        raise HTTPException(status_code=404, detail="Library not found")
    return {"status": "success", "message": "Library removed"}

@router.post("/{library_id}/index")
def index_library(library_id: int, indexer: LibraryIndexer = Depends(get_library_indexer)):
    try:
        results = indexer.index_library(library_id)
        return {"status": "success", "results": results}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Indexing failed: {str(e)}")
