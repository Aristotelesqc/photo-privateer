"""Photos router."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from backend.models import ImageOut, ImageListResponse, BatchProjectUpdate
from backend.repositories.image_repo import ImageRepository
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.image_service import ImageService
from backend.api.deps import (
    get_image_repo,
    get_thumbnail_cache,
    get_image_service,
)

router = APIRouter(prefix="/api/photos", tags=["photos"])

@router.get("/projects", response_model=list[str])
def list_projects(
    library_id: Optional[int] = None,
    repo: ImageRepository = Depends(get_image_repo),
):
    return repo.get_distinct_projects(library_id=library_id)

@router.post("/batch-project")
def batch_assign_project(
    payload: BatchProjectUpdate,
    repo: ImageRepository = Depends(get_image_repo),
):
    count = repo.batch_update_project(payload.photo_ids, payload.project)
    repo.conn.commit()
    return {"updated": count, "project": payload.project}

@router.get("", response_model=ImageListResponse)
def list_photos(
    library_id: Optional[int] = None,
    search: Optional[str] = None,
    project: Optional[str] = None,
    group_id: Optional[int] = None,
    filter_status: Optional[str] = Query(None, pattern="^(all|unscanned|scanned|has_matches|has_unreviewed|grouped)$"),
    sort_by: str = Query("indexed_at", pattern="^(indexed_at|last_scanned_at|filename|project|match_count|unreviewed_count|file_size)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    repo: ImageRepository = Depends(get_image_repo),
):
    offset = (page - 1) * page_size
    images, total = repo.list_images(
        library_id=library_id,
        search=search,
        filter_status=filter_status,
        project=project,
        group_id=group_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=page_size,
        offset=offset,
    )
    return ImageListResponse(
        images=images,
        total=total,
        page=page,
        page_size=page_size,
    )

@router.patch("/{photo_id}/project", response_model=ImageOut)
def update_photo_project(
    photo_id: int,
    project: Optional[str] = Query(None),
    repo: ImageRepository = Depends(get_image_repo),
):
    img = repo.update_project(photo_id, project)
    if not img:
        raise HTTPException(status_code=404, detail="Photo not found")
    repo.conn.commit()
    return img

@router.get("/{photo_id}", response_model=ImageOut)
def get_photo(photo_id: int, repo: ImageRepository = Depends(get_image_repo)):
    img = repo.get_by_id(photo_id)
    if not img:
        raise HTTPException(status_code=404, detail="Photo not found")
    return img

@router.get("/{photo_id}/thumbnail")
def get_photo_thumbnail(
    photo_id: int,
    repo: ImageRepository = Depends(get_image_repo),
    thumb_cache: ThumbnailCache = Depends(get_thumbnail_cache),
):
    img = repo.get_by_id(photo_id)
    if not img:
        raise HTTPException(status_code=404, detail="Photo not found")
    
    thumb_path = thumb_cache.get_thumbnail_path(img.sha256)
    if not thumb_path.is_file():
        try:
            thumb_path = thumb_cache.get_or_create_thumbnail(img.file_path, img.sha256)
        except Exception:
            raise HTTPException(status_code=404, detail="Thumbnail could not be generated")

    return FileResponse(str(thumb_path), media_type="image/webp")

@router.get("/{photo_id}/file")
def get_photo_file(
    photo_id: int,
    repo: ImageRepository = Depends(get_image_repo),
    img_service: ImageService = Depends(get_image_service),
):
    img = repo.get_by_id(photo_id)
    if not img:
        raise HTTPException(status_code=404, detail="Photo not found")

    # Validate strict containment inside enabled library
    safe_path = img_service.validate_and_resolve_image_path(img.file_path)
    return FileResponse(str(safe_path))
