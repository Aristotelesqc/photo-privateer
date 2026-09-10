"""Base interface and normalization helpers for reverse image search providers."""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional, Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

def normalize_domain_from_url(url: str) -> str:
    """Extracts a clean lowercase domain without www prefix."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        return netloc or "unknown-domain"
    except Exception:
        return "unknown-domain"

def normalize_web_url(url: str) -> str:
    """Normalizes URL by stripping common marketing tracker parameters while preserving path."""
    try:
        parsed = urlparse(url)
        # Filter tracking params - only genuine marketing trackers, never semantic query parameters
        tracking_prefixes = {"utm_", "fbclid", "gclid", "msclkid"}
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        filtered_query = [
            (k, v) for k, v in query_pairs
            if not any(k.lower().startswith(prefix) for prefix in tracking_prefixes)
        ]
        # Re-encode query
        new_query = urlencode(filtered_query)
        # Normalize path trailing slash (except root)
        path = parsed.path
        if path.endswith("/") and len(path) > 1:
            path = path.rstrip("/")
        normalized = urlunparse((
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            path,
            parsed.params,
            new_query,
            ""  # drop fragment
        ))
        return normalized
    except Exception:
        return url

@dataclass
class SearchResultItem:
    domain: str
    match_type: str  # "FULL", "PARTIAL", "PAGE", "OTHER"
    source_kind: str = "PAGE"  # "PAGE" or "ASSET_ONLY"
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    page_score: Optional[float] = None
    candidate_image_url: Optional[str] = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ProviderResult:
    success: bool
    items: list[SearchResultItem]
    units_consumed: int = 1
    error_message: Optional[str] = None
    error_kind: Optional[str] = None

class SearchProvider(abc.ABC):
    @property
    @abc.abstractmethod
    def provider_id(self) -> str:
        """Unique identifier e.g. 'google_vision' or 'mock'."""
        pass

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """User-friendly name e.g. 'Google Cloud Vision Web Detection'."""
        pass

    @abc.abstractmethod
    def search(self, image_path: str, **kwargs: Any) -> ProviderResult:
        """Executes reverse image search for the local image file."""
        pass
