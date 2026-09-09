"""Tests for API usage accounting, cost projection, and free allowance guard."""
from __future__ import annotations

import pytest

def test_usage_summary_and_cost_calculation(repos):
    usage_repo = repos["usage_repo"]
    tracker = repos["tracker"]
    settings_repo = repos["settings_repo"]

    # Free tier default: 1000 units, price $0.0035
    period = "2026-09"

    # 1. Zero usage state
    summary0 = usage_repo.get_usage_summary(period=period)
    assert summary0.units_used_this_month == 0
    assert summary0.remaining_free_units == 1000
    assert summary0.estimated_total_cost_usd == 0.0

    # 2. Record 600 units within free tier
    usage_repo.record_call(
        provider="google_vision",
        billing_period=period,
        scan_session_id=None,
        image_id=None,
        attempted_units=600,
        successful_units=600,
        failed_units=0,
        request_status="SUCCESS",
        estimated_cost=0.0,
    )

    summary1 = usage_repo.get_usage_summary(period=period)
    assert summary1.units_used_this_month == 600
    assert summary1.remaining_free_units == 400
    assert summary1.estimated_total_cost_usd == 0.0

    # 3. Project a pending scan of 200 units (still inside free tier)
    proj1 = tracker.prepare_scan_projection(image_count=200, provider_override="google_vision")
    assert proj1.projected_units_total == 800
    assert proj1.estimated_incremental_cost_usd == 0.0
    assert proj1.free_tier_exceeded is False
    assert proj1.blocked_by_guard is False

    # 4. Project a pending scan of 600 units (crosses 1000 threshold by 200 units)
    proj2 = tracker.prepare_scan_projection(image_count=600, provider_override="google_vision")
    assert proj2.projected_units_total == 1200
    # 200 billable units * 0.0035 = $0.70
    assert proj2.estimated_incremental_cost_usd == 0.70
    assert proj2.free_tier_exceeded is True
    assert proj2.blocked_by_guard is True

    # 5. Disable guard in settings
    settings_repo.update_settings({"block_on_free_tier_exceeded": False})
    proj3 = tracker.prepare_scan_projection(image_count=600, provider_override="google_vision")
    assert proj3.free_tier_exceeded is True
    assert proj3.blocked_by_guard is False

def test_scan_engine_guard_blocking(repos):
    scan_engine = repos["scan_engine"]
    usage_repo = repos["usage_repo"]
    settings_repo = repos["settings_repo"]

    # Set free tier allowance low to 5 units for testing
    settings_repo.update_settings({
        "active_provider": "google_vision",
        "free_tier_monthly_units": 5,
        "block_on_free_tier_exceeded": True,
    })

    # Record 5 units used
    usage_repo.record_call(
        provider="google_vision",
        billing_period=repos["usage_repo"].get_usage_summary().billing_period,
        scan_session_id=None,
        image_id=None,
        attempted_units=5,
        successful_units=5,
        failed_units=0,
        request_status="SUCCESS",
        estimated_cost=0.0,
    )

    # Attempting to scan 2 photos without override should be blocked
    with pytest.raises(ValueError, match="Scan blocked by free tier allowance guard"):
        scan_engine.execute_scan(
            image_ids=[1, 2],
            provider_override="google_vision",
            force_override_guard=False,
        )
