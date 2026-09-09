"""Repository for application settings."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional
from backend.config import (
    DEFAULT_FREE_TIER_MONTHLY_UNITS,
    DEFAULT_UNIT_PRICE_USD,
    DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED,
)
from backend.models import AppSettings

class SettingsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )

    def get_app_settings(self) -> AppSettings:
        active_provider = self.get_setting("active_provider", "mock")
        google_credentials_path = self.get_setting("google_credentials_path")
        free_tier_str = self.get_setting("free_tier_monthly_units")
        free_tier = int(free_tier_str) if free_tier_str else DEFAULT_FREE_TIER_MONTHLY_UNITS
        block_guard_str = self.get_setting("block_on_free_tier_exceeded")
        block_guard = (block_guard_str.lower() in ("1", "true")) if block_guard_str else DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED
        unit_price_str = self.get_setting("unit_price_usd")
        unit_price = float(unit_price_str) if unit_price_str else DEFAULT_UNIT_PRICE_USD

        # Validate google credentials path if set
        valid, error = self._validate_credentials_path(google_credentials_path)

        return AppSettings(
            active_provider=active_provider,
            google_credentials_path=google_credentials_path,
            free_tier_monthly_units=free_tier,
            block_on_free_tier_exceeded=block_guard,
            unit_price_usd=unit_price,
            google_credentials_valid=valid,
            google_credentials_error=error,
        )

    def update_settings(self, updates: dict[str, Any]) -> AppSettings:
        for k, v in updates.items():
            if v is not None:
                self.set_setting(k, str(v))
        return self.get_app_settings()

    def _validate_credentials_path(self, path_str: Optional[str]) -> tuple[bool, Optional[str]]:
        if not path_str:
            return False, "No credentials path configured"
        path = Path(path_str)
        if not path.is_file():
            return False, f"File not found: {path.name}"
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("type") != "service_account":
                return False, "JSON does not appear to be a Google service account key"
            if "client_email" not in data or "private_key" not in data:
                return False, "Missing required service account key fields"
            return True, None
        except Exception as e:
            return False, f"Invalid JSON credential: {str(e)}"
