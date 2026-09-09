"""Deterministic mock reverse image search provider for offline testing and demos."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from backend.providers.base import (
    SearchProvider,
    ProviderResult,
    SearchResultItem,
    normalize_domain_from_url,
    normalize_web_url,
)

class MockSearchProvider(SearchProvider):
    @property
    def provider_id(self) -> str:
        return "mock"

    @property
    def display_name(self) -> str:
        return "Mock / Demo Provider (Offline)"

    def search(self, image_path: str, **kwargs: Any) -> ProviderResult:
        path = Path(image_path)
        name_lower = path.name.lower()

        # Simulated provider failure test case
        if "fail" in name_lower or "error" in name_lower:
            return ProviderResult(
                success=False,
                items=[],
                units_consumed=1,
                error_message="Simulated mock provider failure: upstream connection timeout",
            )

        # Deterministic seed from image bytes or filename
        try:
            with open(path, "rb") as f:
                content = f.read(4096)
            seed_hash = hashlib.sha256(content).hexdigest()
        except Exception:
            seed_hash = hashlib.sha256(path.name.encode()).hexdigest()

        val = int(seed_hash[:8], 16)

        # Scenario 1: Zero results (10% chance or if name has 'clean' / 'empty')
        if "clean" in name_lower or "empty" in name_lower or (val % 10 == 0):
            return ProviderResult(
                success=True,
                items=[],
                units_consumed=1,
            )

        # Scenario 2: Multiple URLs on single domain
        if "multi" in name_lower or (val % 10 in (1, 2)):
            items = [
                SearchResultItem(
                    page_url=normalize_web_url("https://curated-exhibits.art/feature/contemporary-landscapes"),
                    domain=normalize_domain_from_url("https://curated-exhibits.art"),
                    match_type="FULL",
                    page_title="Curated Exhibits: Contemporary Landscapes",
                    page_score=0.96,
                    candidate_image_url="https://curated-exhibits.art/static/hero-preview.jpg",
                    provider_metadata={"mock_scenario": "multi_url_domain"},
                ),
                SearchResultItem(
                    page_url=normalize_web_url("https://curated-exhibits.art/archive/2025/spotlight-gallery"),
                    domain=normalize_domain_from_url("https://curated-exhibits.art"),
                    match_type="PAGE",
                    page_title="Curated Exhibits: 2025 Spotlight Gallery Archive",
                    page_score=0.88,
                    candidate_image_url=None,
                    provider_metadata={"mock_scenario": "multi_url_domain"},
                ),
                SearchResultItem(
                    page_url=normalize_web_url("https://spam-scraper-repost.biz/feed/image-stream-339"),
                    domain=normalize_domain_from_url("https://spam-scraper-repost.biz"),
                    match_type="PARTIAL",
                    page_title="AutoFeed Image Stream #339",
                    page_score=0.45,
                    candidate_image_url="https://spam-scraper-repost.biz/thumbs/crop_339.jpg",
                    provider_metadata={"mock_scenario": "scraper"},
                ),
            ]
            return ProviderResult(success=True, items=items, units_consumed=1)

        # Scenario 3: Standard mixed results (Full match on client site, partial on design blog, scraper)
        items = [
            SearchResultItem(
                page_url=normalize_web_url(f"https://alpinetravel-magazine.org/articles/alps-high-peaks-{val % 50}"),
                domain=normalize_domain_from_url("https://alpinetravel-magazine.org"),
                match_type="FULL",
                page_title="Alpine Travel Magazine: High Peak Wonders",
                page_score=0.98,
                candidate_image_url=f"https://alpinetravel-magazine.org/images/cover-{val % 50}.jpg",
                provider_metadata={"mock_scenario": "full_legit"},
            ),
            SearchResultItem(
                page_url=normalize_web_url(f"https://minimalist-aesthetic-notes.io/inspiration/editorial-selects-{val % 30}"),
                domain=normalize_domain_from_url("https://minimalist-aesthetic-notes.io"),
                match_type="PARTIAL",
                page_title="Minimalist Aesthetic: Curated Editorial Photography",
                page_score=0.74,
                candidate_image_url=f"https://minimalist-aesthetic-notes.io/media/crops/editorial-{val % 30}.webp",
                provider_metadata={"mock_scenario": "partial_cropped"},
            ),
            SearchResultItem(
                page_url=normalize_web_url(f"https://hd-desktop-collector.cc/wallpapers/nature-{val % 100}.html"),
                domain=normalize_domain_from_url("https://hd-desktop-collector.cc"),
                match_type="FULL",
                page_title="Free HD 4K Desktop Wallpaper Download",
                page_score=0.62,
                candidate_image_url=f"https://hd-desktop-collector.cc/thumbs/thumb-{val % 100}.jpg",
                provider_metadata={"mock_scenario": "unauthorized_scraper"},
            ),
        ]
        return ProviderResult(success=True, items=items, units_consumed=1)
