"""Scans router."""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status
from backend.models import (
    ScanPrepareRequest,
    ScanPrepareResponse,
    ScanStartRequest,
    ScanSessionOut,
)
from backend.services.usage_tracker import UsageTracker
from backend.services.scan_engine import ScanEngine, ScanConflictError
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.image_repo import ImageRepository
from backend.api.deps import (
    get_usage_tracker,
    get_scan_engine,
    get_usage_repo,
    get_image_repo,
)

router = APIRouter(prefix="/api/scans", tags=["scans"])

@router.post("/prepare", response_model=ScanPrepareResponse)
def prepare_scan(
    payload: ScanPrepareRequest,
    tracker: UsageTracker = Depends(get_usage_tracker),
    engine: ScanEngine = Depends(get_scan_engine),
):
    if not payload.image_ids:
        raise HTTPException(status_code=400, detail="No images selected for scan")
    
    unique_ids = list(dict.fromkeys(payload.image_ids))
    try:
        usable_images, missing_ids = engine.validate_scan_request(
            image_ids=unique_ids,
            provider_override=payload.provider,
            force_override_guard=True,
        )
    except ScanConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return tracker.prepare_scan_projection(
        image_count=len(unique_ids),
        usable_count=len(usable_images),
        provider_override=payload.provider,
        missing_count=len(missing_ids),
    )


@router.post("/start", response_model=ScanSessionOut)
def start_scan(
    payload: ScanStartRequest,
    engine: ScanEngine = Depends(get_scan_engine),
):
    if not payload.image_ids:
        raise HTTPException(status_code=400, detail="No images selected for scan")

    unique_ids = list(dict.fromkeys(payload.image_ids))
    try:
        session = engine.start_background_scan(
            image_ids=unique_ids,
            provider_override=payload.provider,
            force_override_guard=payload.force_override_guard,
        )
        return session
    except ScanConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan start failed: {str(e)}")

@router.post("/{session_id}/cancel", response_model=ScanSessionOut)
def cancel_scan(
    session_id: int,
    engine: ScanEngine = Depends(get_scan_engine),
):
    try:
        return engine.cancel_scan(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cancellation failed: {str(e)}")

@router.get("/history", response_model=list[ScanSessionOut])
def list_scan_sessions(
    limit: int = 20,
    repo: UsageRepository = Depends(get_usage_repo),
):
    return repo.list_scan_sessions(limit=limit)

@router.get("/{session_id}", response_model=ScanSessionOut)
def get_scan_session(
    session_id: int,
    repo: UsageRepository = Depends(get_usage_repo),
):
    session = repo.get_scan_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Scan session not found")
    return session
