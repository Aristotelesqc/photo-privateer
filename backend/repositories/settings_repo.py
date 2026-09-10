"""Repository for application settings."""
from __future__ import annotations

import json
import os
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
        adc_available, adc_project = self._check_adc()

        if valid:
            auth_mode = "service_account"
        elif adc_available:
            auth_mode = "adc"
        else:
            auth_mode = "none"

        return AppSettings(
            active_provider=active_provider,
            google_credentials_path=google_credentials_path,
            free_tier_monthly_units=free_tier,
            block_on_free_tier_exceeded=block_guard,
            unit_price_usd=unit_price,
            google_credentials_valid=valid,
            google_credentials_error=error,
            adc_available=adc_available,
            adc_project_id=adc_project,
            auth_mode=auth_mode,
        )

    def _check_adc(self) -> tuple[bool, Optional[str]]:
        env_adc = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        appdata = os.environ.get("APPDATA")
        gcloud_win = Path(appdata) / "gcloud" / "application_default_credentials.json" if appdata else None
        gcloud_nix = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"

        has_adc_file = (
            bool(env_adc and Path(env_adc).is_file())
            or bool(gcloud_win and gcloud_win.is_file())
            or bool(gcloud_nix.is_file())
        )
        if not has_adc_file:
            return False, None

        try:
            import google.auth
            creds, project_id = google.auth.default()
            return (creds is not None), project_id
        except Exception:
            return False, None

    def test_google_auth(self, credentials_path_override: Optional[str] = None) -> dict[str, Any]:
        """Tests Google Cloud authentication without consuming any Vision API units."""
        target_path = credentials_path_override if credentials_path_override is not None else self.get_setting("google_credentials_path")
        
        if target_path and Path(target_path).is_file():
            try:
                from google.oauth2 import service_account
                import google.auth.transport.requests
                creds = service_account.Credentials.from_service_account_file(
                    target_path,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )
                request = google.auth.transport.requests.Request()
                creds.refresh(request)
                return {
                    "success": True,
                    "auth_mode": "service_account",
                    "project_id": creds.project_id,
                    "service_account_email": creds.service_account_email,
                    "message": f"Service account verified successfully ({creds.service_account_email}).",
                }
            except Exception as e:
                return {
                    "success": False,
                    "auth_mode": "service_account",
                    "error": f"Failed to authenticate using service account key: {str(e)}",
                }

        # Otherwise attempt ADC if detected
        adc_available, _ = self._check_adc()
        if not adc_available:
            return {
                "success": False,
                "auth_mode": "none",
                "error": "No Google Cloud credentials configured. Specify a Service Account key path or run 'gcloud auth application-default login'.",
            }

        try:
            import google.auth
            import google.auth.transport.requests
            creds, project_id = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            request = google.auth.transport.requests.Request()
            creds.refresh(request)
            return {
                "success": True,
                "auth_mode": "adc",
                "project_id": project_id,
                "message": f"Application Default Credentials (ADC) verified successfully (project: {project_id}).",
            }
        except Exception as e:
            return {
                "success": False,
                "auth_mode": "none",
                "error": f"Google authentication failed: {str(e)}",
            }

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
