"""Scan coordination and execution engine."""
from __future__ import annotations

import logging
from typing import Optional, Callable
from backend.repositories.image_repo import ImageRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.usage_repo import UsageRepository, get_current_billing_period
from backend.repositories.settings_repo import SettingsRepository
from backend.providers import get_provider
from backend.models import ScanSessionOut
from backend.config import CLASS_UNREVIEWED

logger = logging.getLogger(__name__)

class ScanEngine:
    def __init__(
        self,
        image_repo: ImageRepository,
        match_repo: MatchRepository,
        rule_repo: DomainRuleRepository,
        usage_repo: UsageRepository,
        settings_repo: SettingsRepository,
    ):
        self.image_repo = image_repo
        self.match_repo = match_repo
        self.rule_repo = rule_repo
        self.usage_repo = usage_repo
        self.settings_repo = settings_repo

    def execute_scan(
        self,
        image_ids: list[int],
        provider_override: Optional[str] = None,
        force_override_guard: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> ScanSessionOut:
        settings = self.settings_repo.get_app_settings()
        provider_id = provider_override or settings.active_provider

        # Check guard if real provider
        if provider_id == "google_vision" and not force_override_guard:
            current_period = get_current_billing_period()
            current_units = self.usage_repo.get_period_units(current_period, provider="google_vision")
            if (current_units + len(image_ids)) > settings.free_tier_monthly_units and settings.block_on_free_tier_exceeded:
                raise ValueError("Scan blocked by free tier allowance guard. Force override required to proceed.")

        # Initialize provider instance
        provider = get_provider(
            provider_id=provider_id,
            credentials_path=settings.google_credentials_path,
        )

        # Create scan session
        session = self.usage_repo.create_scan_session(
            provider=provider.display_name,
            total_images=len(image_ids),
        )

        images = self.image_repo.get_by_ids(image_ids)
        # Preserve input order
        image_map = {img.id: img for img in images}
        ordered_images = [image_map[iid] for iid in image_ids if iid in image_map]

        processed = 0
        successful = 0
        failed = 0
        current_period = get_current_billing_period()

        for idx, img in enumerate(ordered_images):
            if progress_callback:
                progress_callback(idx, len(ordered_images), f"Scanning {img.filename}...")

            # Run search through provider
            provider_result = provider.search(
                image_path=img.file_path,
                credentials_path=settings.google_credentials_path,
            )

            # Estimate cost for this single unit
            unit_cost = 0.0
            if provider_id == "google_vision" and provider_result.success:
                # Check if this unit is billable
                current_used = self.usage_repo.get_period_units(current_period, provider="google_vision")
                if current_used >= settings.free_tier_monthly_units:
                    unit_cost = settings.unit_price_usd

            # Record call in usage repository
            self.usage_repo.record_call(
                provider=provider_id,
                billing_period=current_period,
                scan_session_id=session.id,
                image_id=img.id,
                attempted_units=1,
                successful_units=1 if provider_result.success else 0,
                failed_units=0 if provider_result.success else 1,
                request_status="SUCCESS" if provider_result.success else "FAILED",
                estimated_cost=unit_cost,
                error_message=provider_result.error_message,
            )

            if provider_result.success:
                successful += 1
                matches_found = 0
                for item in provider_result.items:
                    # Check domain rules
                    matching_rule = self.rule_repo.find_rule_for_domain(item.domain)
                    default_class = matching_rule.classification if matching_rule else CLASS_UNREVIEWED
                    rule_id = matching_rule.id if matching_rule else None

                    # Upsert match into database (preserves any existing user classification!)
                    _, is_new = self.match_repo.upsert_match(
                        image_id=img.id,
                        scan_session_id=session.id,
                        page_url=item.page_url,
                        page_title=item.page_title,
                        page_score=item.page_score,
                        domain=item.domain,
                        candidate_image_url=item.candidate_image_url,
                        match_type=item.match_type,
                        provider=provider.provider_id,
                        default_classification=default_class,
                        rule_id=rule_id,
                    )
                    matches_found += 1

                # Update image record with scan counts and last_scanned_at
                self.image_repo.record_scan_completed(img.id)

                # Record scan item
                self.usage_repo.record_scan_item(
                    session_id=session.id,
                    image_id=img.id,
                    status="SUCCESS",
                    matches_found=matches_found,
                )
            else:
                failed += 1
                self.usage_repo.record_scan_item(
                    session_id=session.id,
                    image_id=img.id,
                    status="ERROR",
                    error_message=provider_result.error_message,
                    matches_found=0,
                )

            processed += 1
            self.usage_repo.update_scan_session_progress(
                session_id=session.id,
                processed=processed,
                successful=successful,
                failed=failed,
            )

        # Final status
        final_status = "COMPLETED" if successful > 0 or len(ordered_images) == 0 else "FAILED"
        self.usage_repo.update_scan_session_progress(
            session_id=session.id,
            processed=processed,
            successful=successful,
            failed=failed,
            status=final_status,
        )

        if progress_callback:
            progress_callback(len(ordered_images), len(ordered_images), "Scan finished.")

        return self.usage_repo.get_scan_session(session.id)  # type: ignore
