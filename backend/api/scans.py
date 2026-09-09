"""Scans router."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from backend.models import (
    ScanPrepareRequest,
    ScanPrepareResponse,
    ScanStartRequest,
    ScanSessionOut,
)
from backend.services.usage_tracker import UsageTracker
from backend.services.scan_engine import ScanEngine
from backend.repositories.usage_repo import UsageRepository
from backend.api.deps import (
    get_usage_tracker,
    get_scan_engine,
    get_usage_repo,
)

router = APIRouter(prefix="/api/scans", tags=["scans"])

@router.post("/prepare", response_model=ScanPrepareResponse)
def prepare_scan(
    payload: ScanPrepareRequest,
    tracker: UsageTracker = Depends(get_usage_tracker),
):
    if not payload.image_ids:
        raise HTTPException(status_code=400, detail="No images selected for scan")
    
    return tracker.prepare_scan_projection(
        image_count=len(payload.image_ids),
        provider_override=payload.provider,
    )

@router.post("/start", response_model=ScanSessionOut)
def start_scan(
    payload: ScanStartRequest,
    engine: ScanEngine = Depends(get_scan_engine),
):
    if not payload.image_ids:
        raise HTTPException(status_code=400, detail="No images selected for scan")

    try:
        session = engine.execute_scan(
            image_ids=payload.image_ids,
            provider_override=payload.provider,
            force_override_guard=payload.force_override_guard,
        )
        return session
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")

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
