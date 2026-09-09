"""Provider factory and registry."""
from __future__ import annotations

from typing import Optional
from backend.providers.base import SearchProvider
from backend.providers.mock_provider import MockSearchProvider
from backend.providers.google_vision_provider import GoogleVisionSearchProvider

def get_provider(provider_id: str = "mock", credentials_path: Optional[str] = None) -> SearchProvider:
    if provider_id == "google_vision":
        return GoogleVisionSearchProvider(credentials_path=credentials_path)
    return MockSearchProvider()
