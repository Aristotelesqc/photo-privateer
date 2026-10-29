"""Photos router."""
from __future__ import annotations

from typing import Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from backend.models import ImageOut, ImageListResponse, BatchProjectUpdate, BatchProjectResponse
from backend.repositories.image_repo import ImageRepository
from backend.services.thumbnail_cache import ThumbnailCache
from backend.services.image_service import ImageService
from backend.services.scan_eligibility import annotate_eligibility
from backend.api.deps import (
    get_image_repo,
    get_thumbnail_cache,
    get_image_service,
)

router = APIRouter(prefix="/api/photos", tags=["photos"])

@router.get("/projects", response_model=list[str])
def list_projects(
    library_id: Optional[int] = None,
    include_inactive: bool = False,
    repo: ImageRepository = Depends(get_image_repo),
):
    return repo.get_distinct_projects(library_id=library_id, active_only=not include_inactive)

@router.post("/batch-project", response_model=BatchProjectResponse)
def batch_assign_project(
    payload: BatchProjectUpdate,
    repo: ImageRepository = Depends(get_image_repo),
):
    selected = annotate_eligibility(repo.get_by_ids(payload.photo_ids), repo)
    if len(selected) != len(set(payload.photo_ids)) or any(not image.scan_eligible for image in selected):
        raise HTTPException(status_code=400, detail="Selection contains unavailable or inactive photos. Refresh the selection or enable/unarchive the library in Settings.")
    count = repo.batch_update_project(payload.photo_ids, payload.project)
    repo.conn.commit()
    return {"updated": count, "project": payload.project}

@router.get("", response_model=ImageListResponse)
def list_photos(
    library_id: Optional[int] = None,
    search: Optional[str] = None,
    project: Optional[str] = None,
    group_id: Optional[int] = None,
    filter_status: Optional[Literal["all", "unscanned", "scanned", "has_matches", "has_unreviewed", "grouped", "ungrouped", "missing"]] = None,
    sort_by: Literal["indexed_at", "last_scanned_at", "filename", "project", "match_count", "unreviewed_count", "file_size"] = "indexed_at",
    sort_dir: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_inactive: bool = False,
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
        active_only=not include_inactive,
    )
    return ImageListResponse(
        images=annotate_eligibility(images, repo),
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
    return annotate_eligibility([img], repo)[0]

@router.get("/{photo_id}", response_model=ImageOut)
def get_photo(photo_id: int, repo: ImageRepository = Depends(get_image_repo)):
    img = repo.get_by_id(photo_id)
    if not img:
        raise HTTPException(status_code=404, detail="Photo not found")
    return annotate_eligibility([img], repo)[0]

@router.get("/{photo_id}/thumbnail", response_class=Response, responses={200: {"content": {"image/webp": {"schema": {"type": "string", "format": "binary"}}}}})
def get_photo_thumbnail(
    photo_id: int,
    repo: ImageRepository = Depends(get_image_repo),
    thumb_cache: ThumbnailCache = Depends(get_thumbnail_cache),
    img_service: ImageService = Depends(get_image_service),
):
    img = repo.get_by_id(photo_id)
    if not img:
        raise HTTPException(status_code=404, detail="Photo not found")
    
    try:
        content = thumb_cache.read_thumbnail(img.sha256)
    except FileNotFoundError:
        # Reading the original requires the same containment check as the original-file route:
        # the file must resolve inside an enabled, non-archived library
        safe_path = img_service.validate_and_resolve_image_path(img.file_path)
        try:
            content = thumb_cache.read_thumbnail(img.sha256, safe_path)
        except Exception:
            raise HTTPException(status_code=404, detail="Thumbnail could not be generated")

    return Response(content, media_type="image/webp")

@router.get("/{photo_id}/file", response_class=FileResponse, responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
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
