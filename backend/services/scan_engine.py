"""Scan coordination and execution engine with local background worker architecture."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from typing import Optional, Callable
from pathlib import Path

from backend.database import get_connection
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.usage_repo import UsageRepository, get_current_billing_period
from backend.repositories.settings_repo import SettingsRepository
from backend.providers import get_provider
from backend.models import ScanSessionOut, ImageOut
from backend.config import CLASS_UNREVIEWED

logger = logging.getLogger(__name__)

class ScanConflictError(ValueError):
    """Raised when an attempt is made to start a scan while another is already running."""
    pass

class ScanEngine:
    def __init__(
        self,
        image_repo: ImageRepository,
        match_repo: MatchRepository,
        rule_repo: DomainRuleRepository,
        usage_repo: UsageRepository,
        settings_repo: SettingsRepository,
        library_repo: Optional[LibraryRepository] = None,
    ):
        self.image_repo = image_repo
        self.match_repo = match_repo
        self.rule_repo = rule_repo
        self.usage_repo = usage_repo
        self.settings_repo = settings_repo
        self.library_repo = library_repo or LibraryRepository(self.image_repo.conn)
        self.db_path: Optional[str] = None
        try:
            cur = self.image_repo.conn.cursor()
            cur.execute("PRAGMA database_list")
            for row in cur.fetchall():
                if row[1] == "main" and row[2]:
                    self.db_path = row[2]
                    break
        except Exception:
            pass

    def validate_scan_request(
        self,
        image_ids: list[int],
        provider_override: Optional[str] = None,
        force_override_guard: bool = False,
    ) -> tuple[list[ImageOut], list[int]]:
        """Validates that no other scan is running, enforces the free-tier safety guard,
        and verifies that selected images exist and are present on disk.
        Returns: (usable_images, missing_image_ids)
        """
        # 1. Enforce single active scan invariant
        active = self.usage_repo.get_active_running_session()
        if active:
            raise ScanConflictError(
                f"Another scan session (#{active.id}) is currently running ({active.processed_images}/{active.total_images} photos). "
                f"Photo Privateer enforces a single active scan at a time to prevent quota races."
            )

        if not image_ids:
            raise ValueError("No image IDs provided for scan.")

        # 2. Enforce active non-archived libraries
        active_libs = {lib.id: lib for lib in self.library_repo.list_libraries(include_archived=False) if lib.enabled}

        # 3. Validate images and filter to those present on disk
        images = self.image_repo.get_by_ids(image_ids)
        image_map = {img.id: img for img in images}

        archived_or_disabled_ids = [
            iid for iid in image_ids
            if iid in image_map and (image_map[iid].library_id not in active_libs)
        ]
        if archived_or_disabled_ids:
            raise ValueError(
                f"Cannot scan images belonging to archived or disabled libraries: {archived_or_disabled_ids}"
            )
        
        usable_images: list[ImageOut] = []
        missing_ids: list[int] = []

        for iid in image_ids:
            img = image_map.get(iid)
            if img is None:
                missing_ids.append(iid)
            elif not img.is_present_on_disk or not Path(img.file_path).exists():
                missing_ids.append(iid)
            else:
                usable_images.append(img)

        if not usable_images:
            raise ValueError(
                f"None of the {len(image_ids)} selected images are currently available on disk. "
                f"Check that files have not been moved or unmounted."
            )

        # 4. Enforce free tier allowance guard on the actual usable scannable image count
        settings = self.settings_repo.get_app_settings()
        provider_id = provider_override or settings.active_provider

        if provider_id == "google_vision" and not force_override_guard:
            current_period = get_current_billing_period()
            current_units = self.usage_repo.get_period_units(current_period, provider="google_vision")
            projected = current_units + len(usable_images)
            if projected > settings.free_tier_monthly_units and settings.block_on_free_tier_exceeded:
                raise ValueError(
                    f"Scan blocked by free tier allowance guard: projected usage ({projected}) "
                    f"exceeds monthly allowance ({settings.free_tier_monthly_units}). "
                    f"Authorize force override to proceed."
                )

        return usable_images, missing_ids


    def start_background_scan(
        self,
        image_ids: list[int],
        provider_override: Optional[str] = None,
        force_override_guard: bool = False,
    ) -> ScanSessionOut:
        """Validates request, commits ScanSession to SQLite immediately, and spawns the local background worker."""
        usable_images, missing_ids = self.validate_scan_request(
            image_ids=image_ids,
            provider_override=provider_override,
            force_override_guard=force_override_guard,
        )

        settings = self.settings_repo.get_app_settings()
        provider_id = provider_override or settings.active_provider
        provider = get_provider(
            provider_id=provider_id,
            credentials_path=settings.google_credentials_path,
        )

        note_str = f"Skipped {len(missing_ids)} missing files." if missing_ids else None

        # Create session and commit
        try:
            session = self.usage_repo.create_scan_session(
                provider=provider.display_name,
                total_images=len(usable_images),
            )
        except sqlite3.IntegrityError as e:
            raise ScanConflictError(
                "Another scan session is currently running. Single active scan enforced."
            ) from e

        if note_str:
            self.usage_repo.update_scan_session_progress(
                session_id=session.id,
                processed=0,
                successful=0,
                failed=0,
                notes=note_str,
            )

        # Spawn local daemon thread worker with isolated DB connection
        worker_thread = threading.Thread(
            target=self._run_scan_worker,
            kwargs={
                "session_id": session.id,
                "ordered_image_ids": [img.id for img in usable_images],
                "provider_id": provider_id,
                "credentials_path": settings.google_credentials_path,
                "free_tier_allowance": settings.free_tier_monthly_units,
                "unit_price_usd": settings.unit_price_usd,
                "db_path": self.db_path,
            },
            daemon=True,
            name=f"scan-worker-{session.id}",
        )
        worker_thread.start()

        return self.usage_repo.get_scan_session(session.id)  # type: ignore

    def cancel_scan(self, session_id: int) -> ScanSessionOut:
        """Signals cooperative cancellation for a running scan session."""
        session = self.usage_repo.get_scan_session(session_id)
        if not session:
            raise ValueError(f"Scan session #{session_id} not found.")
        if session.status != "RUNNING":
            return session

        self.usage_repo.request_cancel_session(session_id)
        return self.usage_repo.get_scan_session(session_id)  # type: ignore

    def _run_scan_worker(
        self,
        session_id: int,
        ordered_image_ids: list[int],
        provider_id: str,
        credentials_path: Optional[str],
        free_tier_allowance: int,
        unit_price_usd: float,
        db_path: Optional[str] = None,
    ) -> None:
        """Background worker loop. Opens its own SQLite connection, executes network calls
        outside write transactions, and commits progress incrementally per image.
        """
        conn = get_connection(db_path or self.db_path)
        try:
            library_repo = LibraryRepository(conn)
            image_repo = ImageRepository(conn)
            match_repo = MatchRepository(conn)
            rule_repo = DomainRuleRepository(conn)
            usage_repo = UsageRepository(conn)

            provider = get_provider(
                provider_id=provider_id,
                credentials_path=credentials_path,
            )

            processed = 0
            successful = 0
            failed = 0
            cancelled = False

            for img_id in ordered_image_ids:
                # 1. Check cooperative cancellation before initiating next external request
                if usage_repo.is_cancel_requested(session_id):
                    cancelled = True
                    break

                img = image_repo.get_by_id(img_id)
                if not img:
                    processed += 1
                    failed += 1
                    usage_repo.update_scan_session_progress(session_id, processed, successful, failed)
                    conn.commit()
                    continue

                # Verify library active & symlink containment
                lib = library_repo.get_by_id(img.library_id)
                if not lib or lib.is_archived or not lib.enabled:
                    processed += 1
                    failed += 1
                    usage_repo.record_scan_item(
                        session_id=session_id,
                        image_id=img.id,
                        status="ERROR",
                        error_message="Image belongs to an archived or disabled library",
                        matches_found=0,
                    )
                    usage_repo.update_scan_session_progress(session_id, processed, successful, failed)
                    conn.commit()
                    continue

                try:
                    real_file = Path(img.file_path).resolve()
                    real_root = Path(lib.path).resolve()
                    if os.path.commonpath([str(real_file), str(real_root)]) != str(real_root):
                        raise ValueError(f"Path traversal detected: {img.file_path} resolves outside library root {lib.path}")
                except Exception as p_err:

                    processed += 1
                    failed += 1
                    usage_repo.record_scan_item(
                        session_id=session_id,
                        image_id=img.id,
                        status="ERROR",
                        error_message=f"Containment check failed: {str(p_err)}",
                        matches_found=0,
                    )
                    usage_repo.update_scan_session_progress(session_id, processed, successful, failed)
                    conn.commit()
                    continue

                # 2. Call external provider OUTSIDE of any database write transaction
                try:
                    provider_result = provider.search(
                        image_path=img.file_path,
                        credentials_path=credentials_path,
                    )
                except Exception as exc:
                    from backend.providers.base import ProviderResult
                    provider_result = ProviderResult(
                        success=False,
                        items=[],
                        units_consumed=0,
                        error_kind="LOCAL_EXECUTION_ERROR",
                        error_message=f"Local execution error: {str(exc)}",
                    )

                # 3. Categorize request result and determine billing semantics
                current_period = get_current_billing_period()
                units_consumed = getattr(provider_result, "units_consumed", 1 if provider_result.success else 0)
                error_kind = getattr(provider_result, "error_kind", None)

                if provider_result.success:
                    req_status = "SUCCESS"
                    attempted_units = units_consumed
                    successful_units = units_consumed
                    failed_units = 0
                else:
                    if error_kind == "REMOTE_API_ERROR" or units_consumed > 0:
                        req_status = "REMOTE_ERROR"
                        attempted_units = units_consumed
                        successful_units = 0
                        failed_units = units_consumed
                    else:
                        req_status = "LOCAL_ERROR"
                        attempted_units = 0
                        successful_units = 0
                        failed_units = 1

                unit_cost = 0.0
                if provider_id == "google_vision" and req_status in ("SUCCESS", "REMOTE_ERROR") and attempted_units > 0:
                    current_units = usage_repo.get_period_units(current_period, provider="google_vision")
                    billable_before = max(0, current_units - free_tier_allowance)
                    billable_after = max(0, current_units + attempted_units - free_tier_allowance)
                    incremental_billable = billable_after - billable_before
                    unit_cost = round(incremental_billable * unit_price_usd, 4)

                # 4. Immediate short SQLite write transaction:
                # Phase A: Durably record provider call accounting in its own immediate transaction
                try:
                    usage_repo.record_call(
                        provider=provider_id,
                        billing_period=current_period,
                        scan_session_id=session_id,
                        image_id=img.id,
                        attempted_units=attempted_units,
                        successful_units=successful_units,
                        failed_units=failed_units,
                        request_status=req_status,
                        estimated_cost=unit_cost,
                        error_message=provider_result.error_message,
                    )
                    conn.commit()
                except Exception as acc_exc:
                    logger.error(f"Error persisting call accounting for image {img.id}: {acc_exc}", exc_info=True)
                    conn.rollback()

                # Phase B: Persist discoveries, item outcome, and session progress
                try:
                    if provider_result.success:
                        matches_count = 0
                        for item in provider_result.items:
                            matching_rule = rule_repo.find_rule_for_domain(item.domain)
                            default_class = matching_rule.classification if matching_rule else CLASS_UNREVIEWED
                            rule_id = matching_rule.id if matching_rule else None

                            match_repo.upsert_match(
                                image_id=img.id,
                                scan_session_id=session_id,
                                domain=item.domain,
                                match_type=item.match_type,
                                provider=provider.provider_id,
                                source_kind=item.source_kind,
                                page_url=item.page_url,
                                page_title=item.page_title,
                                page_score=item.page_score,
                                candidate_image_url=item.candidate_image_url,
                                default_classification=default_class,
                                rule_id=rule_id,
                            )
                            matches_count += 1

                        image_repo.record_scan_completed(img.id)
                        usage_repo.record_scan_item(
                            session_id=session_id,
                            image_id=img.id,
                            status="SUCCESS",
                            matches_found=matches_count,
                        )
                        successful += 1
                    else:
                        failed += 1
                        usage_repo.record_scan_item(
                            session_id=session_id,
                            image_id=img.id,
                            status="ERROR",
                            error_message=provider_result.error_message,
                            matches_found=0,
                        )

                    processed += 1
                    usage_repo.update_scan_session_progress(
                        session_id=session_id,
                        processed=processed,
                        successful=successful,
                        failed=failed,
                    )
                    conn.commit()
                except Exception as db_exc:
                    logger.error(f"Error persisting scan progress for image {img.id}: {db_exc}", exc_info=True)
                    conn.rollback()
                    failed += 1
                    processed += 1
                    try:
                        usage_repo.record_scan_item(
                            session_id=session_id,
                            image_id=img.id,
                            status="ERROR",
                            error_message=f"Database persistence error: {str(db_exc)}",
                            matches_found=0,
                        )
                        usage_repo.update_scan_session_progress(
                            session_id=session_id,
                            processed=processed,
                            successful=successful,
                            failed=failed,
                        )
                        conn.commit()
                    except Exception:
                        pass

            # 5. Final session status update (re-check cancellation for in-flight final image)
            cancelled = cancelled or usage_repo.is_cancel_requested(session_id)
            final_status = (
                "CANCELLED"
                if cancelled
                else ("COMPLETED" if (successful > 0 or len(ordered_image_ids) == 0) else "FAILED")
            )

            usage_repo.update_scan_session_progress(
                session_id=session_id,
                processed=processed,
                successful=successful,
                failed=failed,
                status=final_status,
            )
            conn.commit()

        except Exception as e:
            logger.error(f"Fatal error in scan worker {session_id}: {e}", exc_info=True)
            try:
                usage_repo = UsageRepository(conn)
                usage_repo.update_scan_session_progress(
                    session_id=session_id,
                    processed=processed,
                    successful=successful,
                    failed=failed,
                    status="FAILED",
                    notes=f"Worker error: {str(e)}",
                )
                conn.commit()
            except Exception:
                pass
        finally:
            conn.close()

    def execute_scan(
        self,
        image_ids: list[int],
        provider_override: Optional[str] = None,
        force_override_guard: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> ScanSessionOut:
        """Synchronous scan execution wrapper for direct programmatic use and backend unit tests."""
        usable_images, _ = self.validate_scan_request(
            image_ids=image_ids,
            provider_override=provider_override,
            force_override_guard=force_override_guard,
        )

        settings = self.settings_repo.get_app_settings()
        provider_id = provider_override or settings.active_provider
        provider = get_provider(
            provider_id=provider_id,
            credentials_path=settings.google_credentials_path,
        )

        session = self.usage_repo.create_scan_session(
            provider=provider.display_name,
            total_images=len(usable_images),
        )

        # Run worker synchronously on this thread
        self._run_scan_worker(
            session_id=session.id,
            ordered_image_ids=[img.id for img in usable_images],
            provider_id=provider_id,
            credentials_path=settings.google_credentials_path,
            free_tier_allowance=settings.free_tier_monthly_units,
            unit_price_usd=settings.unit_price_usd,
            db_path=self.db_path,
        )

        return self.usage_repo.get_scan_session(session.id)  # type: ignore

