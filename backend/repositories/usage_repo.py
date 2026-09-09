"""Repository for API usage accounting and scan sessions."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Optional
from backend.models import (
    ProviderCallOut,
    ScanSessionOut,
    UsageSummaryOut,
)
from backend.config import DEFAULT_UNIT_PRICE_USD, DEFAULT_FREE_TIER_MONTHLY_UNITS

def get_current_billing_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")

class UsageRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # --- Provider Calls Accounting ---
    def record_call(
        self,
        provider: str,
        billing_period: str,
        scan_session_id: Optional[int],
        image_id: Optional[int],
        attempted_units: int,
        successful_units: int,
        failed_units: int,
        request_status: str,
        estimated_cost: float,
        error_message: Optional[str] = None,
    ) -> ProviderCallOut:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO provider_calls (
                provider, timestamp, billing_period, scan_session_id, image_id,
                attempted_units, successful_units, failed_units, request_status,
                estimated_cost, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            provider, now, billing_period, scan_session_id, image_id,
            attempted_units, successful_units, failed_units, request_status,
            estimated_cost, error_message
        ))
        call_id = cur.lastrowid
        return self.get_call_by_id(call_id)  # type: ignore

    def get_call_by_id(self, call_id: int) -> Optional[ProviderCallOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM provider_calls WHERE id = ?", (call_id,))
        r = cur.fetchone()
        if not r:
            return None
        return ProviderCallOut(
            id=r["id"],
            provider=r["provider"],
            timestamp=r["timestamp"],
            billing_period=r["billing_period"],
            scan_session_id=r["scan_session_id"],
            image_id=r["image_id"],
            attempted_units=r["attempted_units"],
            successful_units=r["successful_units"],
            failed_units=r["failed_units"],
            request_status=r["request_status"],
            estimated_cost=r["estimated_cost"],
            error_message=r["error_message"],
        )

    def get_period_units(self, billing_period: str, provider: Optional[str] = None) -> int:
        cur = self.conn.cursor()
        if provider:
            cur.execute("""
                SELECT COALESCE(SUM(successful_units), 0)
                FROM provider_calls
                WHERE billing_period = ? AND provider = ?
            """, (billing_period, provider))
        else:
            cur.execute("""
                SELECT COALESCE(SUM(successful_units), 0)
                FROM provider_calls
                WHERE billing_period = ?
            """, (billing_period,))
        row = cur.fetchone()
        return row[0] if row else 0

    def get_usage_summary(
        self,
        free_tier_allowance: int = DEFAULT_FREE_TIER_MONTHLY_UNITS,
        unit_price_usd: float = DEFAULT_UNIT_PRICE_USD,
        is_guard_enabled: bool = True,
        period: Optional[str] = None,
    ) -> UsageSummaryOut:
        billing_period = period or get_current_billing_period()
        units_used = self.get_period_units(billing_period, provider="google_vision")
        
        # Calculate cost: first free_tier_allowance are free
        billable_units = max(0, units_used - free_tier_allowance)
        est_cost = billable_units * unit_price_usd
        remaining_free = max(0, free_tier_allowance - units_used)

        cur = self.conn.cursor()
        cur.execute("""
            SELECT 
                COUNT(*) as total_calls,
                COALESCE(SUM(successful_units), 0) as total_units
            FROM provider_calls
        """)
        lifetime = cur.fetchone()

        disclaimer = (
            "NOTICE: All usage counts and costs displayed here are local estimates tracked by Photo Privateer. "
            "They do not replace official Google Cloud Platform billing statements. Google's actual billing "
            "may differ based on project-wide activity, currency, taxes, or promotional credits."
        )

        return UsageSummaryOut(
            billing_period=billing_period,
            units_used_this_month=units_used,
            free_tier_allowance=free_tier_allowance,
            remaining_free_units=remaining_free,
            estimated_total_cost_usd=round(est_cost, 4),
            is_guard_enabled=is_guard_enabled,
            disclaimer=disclaimer,
            total_lifetime_calls=lifetime["total_calls"] if lifetime else 0,
            total_lifetime_units=lifetime["total_units"] if lifetime else 0,
        )

    def list_calls(self, limit: int = 50, offset: int = 0) -> list[ProviderCallOut]:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM provider_calls
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """, (limit, offset))
        return [
            ProviderCallOut(
                id=r["id"],
                provider=r["provider"],
                timestamp=r["timestamp"],
                billing_period=r["billing_period"],
                scan_session_id=r["scan_session_id"],
                image_id=r["image_id"],
                attempted_units=r["attempted_units"],
                successful_units=r["successful_units"],
                failed_units=r["failed_units"],
                request_status=r["request_status"],
                estimated_cost=r["estimated_cost"],
                error_message=r["error_message"],
            )
            for r in cur.fetchall()
        ]

    # --- Scan Sessions ---
    def create_scan_session(self, provider: str, total_images: int) -> ScanSessionOut:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO scan_sessions (
                started_at, provider, total_images, processed_images,
                successful_images, failed_images, status
            ) VALUES (?, ?, ?, 0, 0, 0, 'RUNNING')
        """, (now, provider, total_images))
        session_id = cur.lastrowid
        return self.get_scan_session(session_id)  # type: ignore

    def update_scan_session_progress(
        self,
        session_id: int,
        processed: int,
        successful: int,
        failed: int,
        status: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        cur = self.conn.cursor()
        now = datetime.now(timezone.utc).isoformat() if status in ("COMPLETED", "CANCELLED", "FAILED") else None
        
        fields = ["processed_images = ?", "successful_images = ?", "failed_images = ?"]
        params: list[object] = [processed, successful, failed]

        if status:
            fields.append("status = ?")
            params.append(status)
            if now:
                fields.append("completed_at = ?")
                params.append(now)

        if notes:
            fields.append("notes = ?")
            params.append(notes)

        params.append(session_id)
        cur.execute(f"UPDATE scan_sessions SET {', '.join(fields)} WHERE id = ?", tuple(params))

    def get_scan_session(self, session_id: int) -> Optional[ScanSessionOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM scan_sessions WHERE id = ?", (session_id,))
        r = cur.fetchone()
        if not r:
            return None
        return ScanSessionOut(
            id=r["id"],
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            provider=r["provider"],
            total_images=r["total_images"],
            processed_images=r["processed_images"],
            successful_images=r["successful_images"],
            failed_images=r["failed_images"],
            status=r["status"],
            notes=r["notes"],
        )

    def list_scan_sessions(self, limit: int = 20) -> list[ScanSessionOut]:
        cur = self.conn.cursor()
        cur.execute("SELECT * FROM scan_sessions ORDER BY started_at DESC LIMIT ?", (limit,))
        return [
            ScanSessionOut(
                id=r["id"],
                started_at=r["started_at"],
                completed_at=r["completed_at"],
                provider=r["provider"],
                total_images=r["total_images"],
                processed_images=r["processed_images"],
                successful_images=r["successful_images"],
                failed_images=r["failed_images"],
                status=r["status"],
                notes=r["notes"],
            )
            for r in cur.fetchall()
        ]

    def record_scan_item(
        self,
        session_id: int,
        image_id: int,
        status: str,
        error_message: Optional[str] = None,
        matches_found: int = 0,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO scan_items (
                scan_session_id, image_id, status, error_message, matches_found, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, image_id, status, error_message, matches_found, now))
