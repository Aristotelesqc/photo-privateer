"""Settings router."""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from backend.models import AppSettings, SettingsUpdate
from backend.repositories.settings_repo import SettingsRepository
from backend.api.deps import get_settings_repo

router = APIRouter(prefix="/api/settings", tags=["settings"])

class FolderValidateRequest(BaseModel):
    path: str

class FolderValidateResponse(BaseModel):
    valid: bool
    resolved_path: str
    is_dir: bool
    error: str | None = None

@router.get("", response_model=AppSettings)
def get_settings(repo: SettingsRepository = Depends(get_settings_repo)):
    return repo.get_app_settings()

@router.patch("", response_model=AppSettings)
def update_settings(payload: SettingsUpdate, repo: SettingsRepository = Depends(get_settings_repo)):
    updates = {}
    if payload.active_provider is not None:
        if payload.active_provider not in ("mock", "google_vision"):
            raise HTTPException(status_code=400, detail="Invalid provider. Must be 'mock' or 'google_vision'")
        updates["active_provider"] = payload.active_provider
    if payload.google_credentials_path is not None:
        updates["google_credentials_path"] = payload.google_credentials_path
    if payload.free_tier_monthly_units is not None:
        if payload.free_tier_monthly_units < 0:
            raise HTTPException(status_code=400, detail="Free tier units cannot be negative")
        updates["free_tier_monthly_units"] = payload.free_tier_monthly_units
    if payload.block_on_free_tier_exceeded is not None:
        updates["block_on_free_tier_exceeded"] = payload.block_on_free_tier_exceeded
    if payload.unit_price_usd is not None:
        if payload.unit_price_usd < 0:
            raise HTTPException(status_code=400, detail="Unit price cannot be negative")
        updates["unit_price_usd"] = payload.unit_price_usd

    return repo.update_settings(updates)

@router.post("/validate-folder", response_model=FolderValidateResponse)
def validate_folder(payload: FolderValidateRequest):
    try:
        p = Path(payload.path).expanduser().resolve()
        if not p.exists():
            return FolderValidateResponse(valid=False, resolved_path=str(p), is_dir=False, error="Path does not exist")
        if not p.is_dir():
            return FolderValidateResponse(valid=False, resolved_path=str(p), is_dir=False, error="Path is not a directory")
        return FolderValidateResponse(valid=True, resolved_path=str(p), is_dir=True, error=None)
    except Exception as e:
        return FolderValidateResponse(valid=False, resolved_path=payload.path, is_dir=False, error=str(e))

class TestGoogleAuthRequest(BaseModel):
    credentials_path: str | None = None

class TestGoogleAuthResponse(BaseModel):
    success: bool
    auth_mode: str
    message: str | None = None
    error: str | None = None
    project_id: str | None = None
    service_account_email: str | None = None

@router.post("/test-google-auth", response_model=TestGoogleAuthResponse)
def test_google_auth(
    payload: TestGoogleAuthRequest | None = None,
    repo: SettingsRepository = Depends(get_settings_repo),
):
    path_override = payload.credentials_path if payload else None
    result = repo.test_google_auth(path_override)
    return TestGoogleAuthResponse(**result)

