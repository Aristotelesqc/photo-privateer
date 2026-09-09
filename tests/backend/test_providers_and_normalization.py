"""Tests for providers and URL/domain normalization."""
from __future__ import annotations

from pathlib import Path
from backend.providers.base import normalize_web_url, normalize_domain_from_url
from backend.providers.mock_provider import MockSearchProvider
from backend.providers.google_vision_provider import GoogleVisionSearchProvider

def test_url_normalization():
    # Strips utm tracking parameters while keeping essential query params
    url1 = "https://example.com/blog/photo-post?utm_source=twitter&utm_medium=social&article_id=42"
    norm1 = normalize_web_url(url1)
    assert "utm_source" not in norm1
    assert "article_id=42" in norm1

    # Normalizes trailing slashes
    url2 = "https://photo-agency.org/portfolio/nature/"
    assert normalize_web_url(url2) == "https://photo-agency.org/portfolio/nature"

    # Preserves root slash
    url3 = "https://photo-agency.org/"
    assert normalize_web_url(url3) == "https://photo-agency.org/"

def test_domain_extraction():
    assert normalize_domain_from_url("https://www.example.com/photos/1") == "example.com"
    assert normalize_domain_from_url("http://sub.portfolio.co.uk:8080/page") == "sub.portfolio.co.uk"
    assert normalize_domain_from_url("https://wildlife-mag.com?query=alps") == "wildlife-mag.com"

def test_mock_provider_scenarios(sample_images_dir: Path):
    provider = MockSearchProvider()
    assert provider.provider_id == "mock"

    # 1. Error simulation
    res_err = provider.search(str(sample_images_dir / "error_test_photo.jpg"))
    assert not res_err.success
    assert res_err.error_message is not None

    # 2. Clean/empty simulation
    res_clean = provider.search(str(sample_images_dir / "clean_portrait.jpg"))
    assert res_clean.success
    assert len(res_clean.items) == 0

    # 3. Multi-url on single domain simulation
    res_multi = provider.search(str(sample_images_dir / "multi_domain_photo.jpg"))
    assert res_multi.success
    assert len(res_multi.items) >= 2
    domains = [item.domain for item in res_multi.items]
    assert domains.count("curated-exhibits.art") >= 2

    # 4. Standard photo simulation
    res_std = provider.search(str(sample_images_dir / "mountain_landscape.jpg"))
    assert res_std.success
    assert len(res_std.items) > 0

def test_google_vision_provider_image_prep(sample_images_dir: Path):
    provider = GoogleVisionSearchProvider()
    assert provider.provider_id == "google_vision"
    
    # Verify in-memory preparation does not alter the source file
    src_file = sample_images_dir / "forest_canopy.png"
    size_before = src_file.stat().st_size
    
    prepared_bytes = provider._prepare_image_bytes(str(src_file))
    assert len(prepared_bytes) > 0
    assert src_file.stat().st_size == size_before
