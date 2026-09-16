"""API usage tracking, projection, and free-tier guard service."""
from __future__ import annotations

from typing import Optional
from backend.repositories.usage_repo import UsageRepository, get_current_billing_period
from backend.repositories.settings_repo import SettingsRepository
from backend.models import ScanPrepareResponse

class UsageTracker:
    def __init__(self, usage_repo: UsageRepository, settings_repo: SettingsRepository):
        self.usage_repo = usage_repo
        self.settings_repo = settings_repo

    def prepare_scan_projection(
        self,
        image_count: int,
        usable_count: Optional[int] = None,
        provider_override: Optional[str] = None,
        missing_count: Optional[int] = None,
    ) -> ScanPrepareResponse:
        settings = self.settings_repo.get_app_settings()
        provider = provider_override or settings.active_provider
        current_period = get_current_billing_period()
        effective_count = usable_count if usable_count is not None else image_count
        calc_missing = missing_count if missing_count is not None else max(0, image_count - effective_count)

        # If mock provider, costs and billable units are 0
        if provider == "mock":
            return ScanPrepareResponse(
                selected_count=image_count,
                usable_count=effective_count,
                missing_count=calc_missing,
                provider="mock",
                current_month=current_period,
                units_used_this_month=0,
                projected_units_total=0,
                free_tier_allowance=settings.free_tier_monthly_units,
                remaining_free_units=settings.free_tier_monthly_units,
                estimated_incremental_cost_usd=0.0,
                free_tier_exceeded=False,
                blocked_by_guard=False,
                disclaimer="Mock provider is active. No Google Cloud Vision API calls or charges will occur.",
            )

        # Real provider usage calculation
        current_used = self.usage_repo.get_period_units(current_period, provider="google_vision")
        projected_total = current_used + effective_count
        allowance = settings.free_tier_monthly_units
        remaining_free_before = max(0, allowance - current_used)

        # How many units in this pending scan fall beyond the free allowance?
        if current_used >= allowance:
            # Already in paid territory
            billable_in_this_scan = effective_count
        else:
            # Partially or fully in free tier
            billable_in_this_scan = max(0, projected_total - allowance)

        estimated_incremental_cost = billable_in_this_scan * settings.unit_price_usd
        free_tier_exceeded = projected_total > allowance
        blocked_by_guard = free_tier_exceeded and settings.block_on_free_tier_exceeded

        disclaimer = (
            f"NOTICE: Costs and units displayed are local estimates based on Google Cloud Vision Web Detection's "
            f"standard published rates (first {allowance:,} units/mo free, then ${(settings.unit_price_usd * 1000):.2f} "
            f"per 1,000 units / ${settings.unit_price_usd:.4f} per unit). They do not represent an official Google invoice "
            f"and may not account for taxes, other project usage, or active promotional credits."
        )

        return ScanPrepareResponse(
            selected_count=image_count,
            usable_count=effective_count,
            missing_count=calc_missing,
            provider="google_vision",
            current_month=current_period,
            units_used_this_month=current_used,
            projected_units_total=projected_total,
            free_tier_allowance=allowance,
            remaining_free_units=remaining_free_before,
            estimated_incremental_cost_usd=round(estimated_incremental_cost, 4),
            free_tier_exceeded=free_tier_exceeded,
            blocked_by_guard=blocked_by_guard,
            disclaimer=disclaimer,
        )
