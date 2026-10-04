"""Scan coordination and execution engine with local background worker architecture."""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable
from pathlib import Path

from backend.database import get_connection
from backend.repositories.library_repo import LibraryRepository
from backend.repositories.image_repo import ImageRepository
from backend.repositories.match_repo import MatchRepository
from backend.repositories.domain_rule_repo import DomainRuleRepository
from backend.repositories.usage_repo import UsageRepository, get_current_billing_period
from backend.repositories.settings_repo import SettingsRepository
from backend.repositories.group_repo import PhotoGroupRepository
from backend.providers import get_provider
from backend.models import ScanSessionOut, ImageOut
from backend.config import CLASS_UNREVIEWED
from backend.services.catalog_coordinator import CatalogOperationConflict, coordinator_for
from backend.services.scan_eligibility import is_available

logger = logging.getLogger(__name__)

_scan_start_lock = threading.Lock()

ScanConflictError = CatalogOperationConflict  # Backwards-compatible public exception.

@dataclass
class ScanPlan:
    """Result of validating a scan request.

    scannable_images: images actually sent to the provider (one per photo group).
    missing_ids: selected images unavailable on disk.
    grouped_variant_ids: selected, available images that are not searched themselves because
        their photo group is searched once through another member (its primary representation).
    """
    scannable_images: list[ImageOut]
    missing_ids: list[int]
    grouped_variant_ids: list[int] = field(default_factory=list)


class ScanEngine:
    def __init__(
        self,
        image_repo: ImageRepository,
        match_repo: MatchRepository,
        rule_repo: DomainRuleRepository,
        usage_repo: UsageRepository,
        settings_repo: SettingsRepository,
        library_repo: Optional[LibraryRepository] = None,
        group_repo: Optional[PhotoGroupRepository] = None,
    ):
        self.image_repo = image_repo
        self.match_repo = match_repo
        self.rule_repo = rule_repo
        self.usage_repo = usage_repo
        self.settings_repo = settings_repo
        self.library_repo = library_repo or LibraryRepository(self.image_repo.conn)
        self.group_repo = group_repo or PhotoGroupRepository(self.image_repo.conn)
        self.coordinator = coordinator_for(self.image_repo.conn)
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
        """Validates a scan request. Returns: (scannable_images, missing_image_ids).
        See plan_scan for the full result including grouped variants.
        """
        plan = self.plan_scan(
            image_ids=image_ids,
            provider_override=provider_override,
            force_override_guard=force_override_guard,
        )
        return plan.scannable_images, plan.missing_ids

    def plan_scan(
        self,
        image_ids: list[int],
        provider_override: Optional[str] = None,
        force_override_guard: bool = False,
    ) -> ScanPlan:
        """Validates that no other scan is running, enforces the free-tier safety guard,
        verifies that selected images exist and are present on disk, and collapses grouped
        photos to one provider search per group.
        """
        # 1. Enforce single active scan invariant with worker thread liveness check
        self.coordinator.check_scan_preparation()
        active = self.usage_repo.get_active_running_session()
        if active:
            worker_name = f"scan-worker-{active.id}"
            is_alive = any(t.name == worker_name and t.is_alive() for t in threading.enumerate())
            if not is_alive:
                # Guard against race conditions with freshly launched sessions:
                # Only auto-recover if the session was started more than 5 seconds ago
                is_stale = True
                if active.started_at:
                    try:
                        started = datetime.fromisoformat(active.started_at)
                        if started.tzinfo is None:
                            started = started.replace(tzinfo=timezone.utc)
                        age_sec = (datetime.now(timezone.utc) - started).total_seconds()
                        if age_sec < 5.0:
                            is_stale = False
                    except Exception:
                        pass

                if is_stale:
                    logger.warning(
                        f"Dangling RUNNING scan session #{active.id} detected without active worker thread. Auto-recovering to FAILED."
                    )
                    try:
                        self.usage_repo.update_scan_session_progress(
                            session_id=active.id,
                            processed=active.processed_images,
                            successful=active.successful_images,
                            failed=active.failed_images,
                            status="FAILED",
                            notes="Auto-recovered from crashed worker thread.",
                        )
                        self.usage_repo.conn.commit()
                        active = None
                    except Exception as exc:
                        logger.error(f"Failed to auto-recover dangling session #{active.id}: {exc}")

            if active:
                raise ScanConflictError(
                    f"Another scan session (#{active.id}) is currently running ({active.processed_images}/{active.total_images} photos). "
                    f"Photo Privateer enforces a single active scan at a time to prevent quota races."
                )

        if not image_ids:
            raise ValueError("No image IDs provided for scan.")

        # Deduplicate image IDs server-side while preserving original request order
        unique_image_ids = list(dict.fromkeys(image_ids))

        # 2. Enforce active non-archived libraries
        active_libs = {lib.id: lib for lib in self.library_repo.list_libraries(include_archived=False) if lib.enabled}

        # 3. Validate images and filter to those present on disk
        images = self.image_repo.get_by_ids(unique_image_ids)
        image_map = {img.id: img for img in images}

        archived_or_disabled_ids = [
            iid for iid in unique_image_ids
            if iid in image_map and (image_map[iid].library_id not in active_libs)
        ]
        if archived_or_disabled_ids:
            raise ValueError(
                f"Cannot scan images belonging to archived or disabled libraries: {archived_or_disabled_ids}. "
                "Refresh your selection, or enable/unarchive their library in Settings before scanning."
            )
        
        def available(candidate: ImageOut) -> bool:
            return is_available(candidate, active_libs)

        # 4. Resolve availability per photo group and collapse each group to 1 search call.
        # A grouped photo is searched through the group's preferred representation when it is
        # available, otherwise through the selected photo, otherwise through any available member;
        # it is only reported missing when no member of its group can be searched.
        group_reps: dict[int, Optional[ImageOut]] = {}

        def resolve_group(gid: int, selected: ImageOut) -> Optional[ImageOut]:
            if gid in group_reps:
                return group_reps[gid]
            rep: Optional[ImageOut] = None
            try:
                pref_id = self.group_repo.get_preferred_image_id(gid)
                members = self.image_repo.get_images_for_group(gid)
                ordered = sorted(members, key=lambda m: (m.id != pref_id, m.id != selected.id, m.id))
                rep = next((m for m in ordered if available(m)), None)
            except Exception as exc:
                logger.warning(
                    f"Could not resolve the representations of photo group #{gid}; "
                    f"scanning selected photo #{selected.id} instead: {exc}"
                )
                rep = selected if available(selected) else None
            group_reps[gid] = rep
            return rep

        scannable_images: list[ImageOut] = []
        seen_scannable_ids: set[int] = set()
        missing_ids: list[int] = []
        grouped_variant_ids: list[int] = []

        for iid in unique_image_ids:
            img = image_map.get(iid)
            if img is None:
                missing_ids.append(iid)
                continue
            if img.photo_group_id is None:
                target = img if available(img) else None
            else:
                target = resolve_group(img.photo_group_id, img)
            if target is None:
                missing_ids.append(iid)
                continue
            if target.id != iid:
                grouped_variant_ids.append(iid)
            if target.id not in seen_scannable_ids:
                scannable_images.append(target)
                seen_scannable_ids.add(target.id)

        if not scannable_images:
            raise ValueError(
                f"None of the {len(unique_image_ids)} selected images are currently available on disk. "
                f"Check that files have not been moved or unmounted."
            )

        # 5. Enforce free tier allowance guard on the actual usable scannable image count
        settings = self.settings_repo.get_app_settings()
        provider_id = provider_override or settings.active_provider

        if provider_id == "google_vision" and not force_override_guard:
            current_period = get_current_billing_period()
            current_units = self.usage_repo.get_period_units(current_period, provider="google_vision")
            projected = current_units + len(scannable_images)
            if projected > settings.free_tier_monthly_units and settings.block_on_free_tier_exceeded:
                raise ValueError(
                    f"Scan blocked by free tier allowance guard: projected usage ({projected}) "
                    f"exceeds monthly allowance ({settings.free_tier_monthly_units}). "
                    f"Authorize force override to proceed."
                )

        return ScanPlan(
            scannable_images=scannable_images,
            missing_ids=missing_ids,
            grouped_variant_ids=grouped_variant_ids,
        )


    def start_background_scan(
        self,
        image_ids: list[int],
        provider_override: Optional[str] = None,
        force_override_guard: bool = False,
    ) -> ScanSessionOut:
        token = self.coordinator.acquire("scanning")
        try:
            return self._start_background_scan(image_ids, provider_override, force_override_guard, token)
        except Exception:
            self.coordinator.release(token)
            raise

    def _start_background_scan(
        self, image_ids: list[int], provider_override: Optional[str],
        force_override_guard: bool, reservation_token: object,
    ) -> ScanSessionOut:
        """Validates request, commits ScanSession to SQLite immediately, and spawns the local background worker."""
        with _scan_start_lock:
            plan = self.plan_scan(
                image_ids=image_ids,
                provider_override=provider_override,
                force_override_guard=force_override_guard,
            )
            usable_images, missing_ids = plan.scannable_images, plan.missing_ids

            settings = self.settings_repo.get_app_settings()
            provider_id = provider_override or settings.active_provider
            provider = get_provider(
                provider_id=provider_id,
                credentials_path=settings.google_credentials_path,
            )

            notes: list[str] = []
            if missing_ids:
                notes.append(f"Skipped {len(missing_ids)} missing files.")
            if plan.grouped_variant_ids:
                count = len(plan.grouped_variant_ids)
                notes.append(
                    f"{count} selected {'photo is' if count == 1 else 'photos are'} covered by "
                    f"the search of another photo in {'its' if count == 1 else 'their'} photo group."
                )
            note_str = " ".join(notes) if notes else None

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

            created_session_id = session.id
            try:
                if note_str:
                    self.usage_repo.update_scan_session_progress(
                        session_id=session.id, processed=0, successful=0, failed=0, notes=note_str,
                    )
                worker_thread = threading.Thread(
                    target=self._run_reserved_scan_worker,
                    kwargs={
                        "reservation_token": reservation_token,
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
                # Read before transferring ownership: no fallible DB query after
                # launch may release a reservation while its worker is alive.
                session = self.usage_repo.get_scan_session(created_session_id)
                worker_thread.start()
            except Exception:
                try:
                    self.usage_repo.update_scan_session_progress(
                        session_id=created_session_id, processed=0, successful=0, failed=0,
                        status="FAILED", notes="Scan worker could not start; retry the scan.",
                    )
                except Exception:
                    logger.exception("Could not persist launch failure; startup recovery will retry.")
                raise

            return session  # type: ignore

    def _run_reserved_scan_worker(self, reservation_token: object, **kwargs) -> None:
        try:
            self._run_scan_worker(**kwargs)
        except Exception:
            # This also covers failures before the worker opens its DB connection.
            logger.exception("Scan worker failed before its normal recovery boundary.")
            try:
                with get_connection(kwargs.get("db_path") or self.db_path) as conn:
                    UsageRepository(conn).update_scan_session_progress(
                        session_id=kwargs["session_id"], processed=0, successful=0, failed=0,
                        status="FAILED", notes="Scan worker failed; retry the scan.",
                    )
            except Exception:
                logger.exception("Could not persist scan worker failure; startup recovery will retry.")
        finally:
            self.coordinator.release(reservation_token)

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
            aborted_due_to_accounting_failure = False

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
                    norm_file = os.path.normcase(str(Path(img.file_path).resolve()))
                    norm_root = os.path.normcase(str(Path(lib.path).resolve()))
                    if os.path.commonpath([norm_file, norm_root]) != norm_root:
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

                # A photo grouped while the scan is running is covered when another current member
                # of its group was already searched successfully in this session, whether it was
                # grouped before, during or after that search: resolved against current membership
                if img.photo_group_id is not None and conn.execute(
                    """
                    SELECT 1 FROM scan_items s JOIN images i ON i.id = s.image_id
                    WHERE s.scan_session_id = ? AND s.status = 'SUCCESS'
                      AND i.photo_group_id = ? AND s.image_id != ?
                    LIMIT 1
                    """,
                    (session_id, img.photo_group_id, img.id),
                ).fetchone():
                    processed += 1
                    successful += 1
                    usage_repo.record_scan_item(
                        session_id=session_id,
                        image_id=img.id,
                        status="SKIPPED",
                        error_message=f"Covered by this session's search of photo group #{img.photo_group_id}",
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
                accounting_persisted = False
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
                    accounting_persisted = True
                except Exception as acc_exc:
                    logger.critical(
                        f"CRITICAL: Failed to durably record provider call accounting for image {img.id} "
                        f"in session {session_id}: {acc_exc}. Failing closed to prevent unmetered external calls.",
                        exc_info=True,
                    )
                    try:
                        conn.rollback()
                    except Exception:
                        pass

                    # Invariant: If a potentially billable external provider call occurred (or provider is google_vision),
                    # failure to persist accounting locally MUST fail closed immediately.
                    if attempted_units > 0 or provider_id == "google_vision" or req_status in ("SUCCESS", "REMOTE_ERROR"):
                        aborted_due_to_accounting_failure = True
                        failed += 1
                        processed += 1
                        try:
                            usage_repo.record_scan_item(
                                session_id=session_id,
                                image_id=img.id,
                                status="ERROR",
                                error_message=f"Durable accounting persistence failed after provider request: {str(acc_exc)}",
                                matches_found=0,
                            )
                            usage_repo.update_scan_session_progress(
                                session_id=session_id,
                                processed=processed,
                                successful=successful,
                                failed=failed,
                                status="FAILED",
                                notes=(
                                    f"Scan aborted: local SQLite write failed while persisting provider call accounting "
                                    f"for photo #{img.id}. Halted to prevent unmetered external API calls."
                                ),
                            )
                            conn.commit()
                        except Exception as log_exc:
                            logger.error(f"Could not persist session failure state: {log_exc}")
                        break

                if not accounting_persisted:
                    continue

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

                        # Physical per-file history only: siblings are covered through derived
                        # group coverage (MAX over members), never by writing scans they did not get
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
            if aborted_due_to_accounting_failure:
                return

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
        token = self.coordinator.acquire("scanning")
        try:
            return self._execute_scan(image_ids, provider_override, force_override_guard, progress_callback, token)
        finally:
            self.coordinator.release(token)

    def _execute_scan(
        self, image_ids: list[int], provider_override: Optional[str],
        force_override_guard: bool, progress_callback, reservation_token: object,
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
        self._run_reserved_scan_worker(
            reservation_token=reservation_token,
            session_id=session.id,
            ordered_image_ids=[img.id for img in usable_images],
            provider_id=provider_id,
            credentials_path=settings.google_credentials_path,
            free_tier_allowance=settings.free_tier_monthly_units,
            unit_price_usd=settings.unit_price_usd,
            db_path=self.db_path,
        )

        return self.usage_repo.get_scan_session(session.id)  # type: ignore

