"""Usage and accounting router."""
from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Query
from backend.models import UsageSummaryOut, ProviderCallOut
from backend.repositories.usage_repo import UsageRepository
from backend.repositories.settings_repo import SettingsRepository
from backend.api.deps import get_usage_repo, get_settings_repo

router = APIRouter(prefix="/api/usage", tags=["usage"])

@router.get("/summary", response_model=UsageSummaryOut)
def get_usage_summary(
    period: Optional[str] = Query(None, pattern="^\\d{4}-\\d{2}$"),
    usage_repo: UsageRepository = Depends(get_usage_repo),
    settings_repo: SettingsRepository = Depends(get_settings_repo),
):
    settings = settings_repo.get_app_settings()
    return usage_repo.get_usage_summary(
        free_tier_allowance=settings.free_tier_monthly_units,
        unit_price_usd=settings.unit_price_usd,
        is_guard_enabled=settings.block_on_free_tier_exceeded,
        period=period,
    )

@router.get("/calls", response_model=list[ProviderCallOut])
def list_provider_calls(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    usage_repo: UsageRepository = Depends(get_usage_repo),
):
    return usage_repo.list_calls(limit=limit, offset=offset)
