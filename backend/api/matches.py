"""Matches router."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.models import MatchOut, MatchUpdate, MatchListResponse
from backend.repositories.match_repo import MatchRepository
from backend.config import VALID_CLASSIFICATIONS
from backend.api.deps import get_match_repo

router = APIRouter(prefix="/api/matches", tags=["matches"])

@router.get("", response_model=MatchListResponse)
def list_matches(
    image_id: Optional[int] = None,
    project: Optional[str] = None,
    classification: Optional[str] = None,
    is_new_only: bool = False,
    domain: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query("last_seen_at", pattern="^(last_seen_at|first_seen_at|domain|page_title|classification|match_type)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    repo: MatchRepository = Depends(get_match_repo),
):
    if classification and classification not in VALID_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid classification: {classification}")

    offset = (page - 1) * page_size
    matches, total = repo.list_matches(
        image_id=image_id,
        project=project,
        classification=classification,
        is_new_only=is_new_only,
        domain=domain,
        search=search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=page_size,
        offset=offset,
    )
    return MatchListResponse(
        matches=matches,
        total=total,
        page=page,
        page_size=page_size,
    )

@router.get("/{match_id}", response_model=MatchOut)
def get_match(match_id: int, repo: MatchRepository = Depends(get_match_repo)):
    m = repo.get_by_id(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")
    return m

@router.patch("/{match_id}", response_model=MatchOut)
def update_match(
    match_id: int,
    payload: MatchUpdate,
    repo: MatchRepository = Depends(get_match_repo),
):
    if payload.classification is not None and payload.classification not in VALID_CLASSIFICATIONS:
        raise HTTPException(status_code=400, detail=f"Invalid classification: {payload.classification}")

    m = repo.get_by_id(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="Match not found")

    clear_notes = False
    notes_val = None
    if "notes" in payload.model_fields_set:
        if payload.notes is None or payload.notes.strip() == "":
            clear_notes = True
        else:
            notes_val = payload.notes

    updated = repo.update_classification_and_notes(
        match_id=match_id,
        classification=payload.classification,
        notes=notes_val,
        clear_notes=clear_notes,
        acknowledged=payload.acknowledged,
    )
    return updated

