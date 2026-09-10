"""Official Google Cloud Vision Web Detection reverse image search provider."""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Any, Optional
from PIL import Image, ImageOps

from backend.providers.base import (
    SearchProvider,
    ProviderResult,
    SearchResultItem,
    normalize_domain_from_url,
    normalize_web_url,
)

class GoogleVisionSearchProvider(SearchProvider):
    def __init__(self, credentials_path: Optional[str] = None):
        self.credentials_path = credentials_path

    @property
    def provider_id(self) -> str:
        return "google_vision"

    @property
    def display_name(self) -> str:
        return "Google Cloud Vision Web Detection"

    def _prepare_image_bytes(self, image_path: str) -> bytes:
        """Reads local image, transposing EXIF orientation, stripping all EXIF/GPS/IPTC/XMP metadata,
        and producing a clean high-quality JPEG in-memory for reverse image search.
        Original source image on disk is strictly read-only and never modified.
        """
        path = Path(image_path)
        with Image.open(path) as raw_img:
            # 1. Apply EXIF orientation to visual pixel matrix
            img = ImageOps.exif_transpose(raw_img)

            # 2. Ensure compatible color mode (convert CMYK, RGBA, etc. to RGB)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            
            # 3. Resize conservatively if huge (max 2048px on longest edge)
            max_dim = 2048
            if max(img.width, img.height) > max_dim:
                img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)

            # 4. Strip ALL metadata: create fresh PIL image without any existing info or EXIF dictionaries
            clean_img = Image.new("RGB", img.size)
            clean_img.paste(img)

            buffer = io.BytesIO()
            clean_img.save(buffer, format="JPEG", quality=90, optimize=True)
            return buffer.getvalue()

    def search(self, image_path: str, **kwargs: Any) -> ProviderResult:
        if os.environ.get("PHOTO_PRIVATEER_TEST_MODE") == "1":
            raise RuntimeError("Google Vision network calls are strictly forbidden in test mode.")
        try:
            from google.cloud import vision
            from google.api_core.exceptions import GoogleAPICallError
        except ImportError:
            return ProviderResult(
                success=False,
                items=[],
                units_consumed=0,
                error_kind="LOCAL_PREP_ERROR",
                error_message="google-cloud-vision Python package is not installed",
            )

        # Resolve credentials
        creds_path = kwargs.get("credentials_path") or self.credentials_path
        client: Any = None
        try:
            if creds_path and os.path.isfile(creds_path):
                client = vision.ImageAnnotatorClient.from_service_account_file(creds_path)
            else:
                # Fallback to standard environment variable or default application credentials
                client = vision.ImageAnnotatorClient()
        except Exception as e:
            return ProviderResult(
                success=False,
                items=[],
                units_consumed=0,
                error_kind="LOCAL_AUTH_ERROR",
                error_message=f"Google Cloud authentication failed: {str(e)}",
            )

        try:
            image_bytes = self._prepare_image_bytes(image_path)
            image = vision.Image(content=image_bytes)
            
            # Invoke Web Detection
            response = client.web_detection(image=image)

            if response.error and response.error.message:
                return ProviderResult(
                    success=False,
                    items=[],
                    units_consumed=1,
                    error_kind="REMOTE_API_ERROR",
                    error_message=f"Google Vision API Error: {response.error.message}",
                )

            web_detection = response.web_detection
            items: list[SearchResultItem] = []
            seen_combos: set[tuple[Optional[str], Optional[str]]] = set()

            # 1. Pages with matching images
            if web_detection.pages_with_matching_images:
                for page in web_detection.pages_with_matching_images:
                    p_url = normalize_web_url(page.url) if page.url else None
                    p_title = page.page_title if page.page_title else None
                    p_score = float(page.score) if page.score else None
                    domain = normalize_domain_from_url(p_url) if p_url else "unknown-domain"

                    # Normalize all matching images without dropping full vs partial
                    candidate_pairs: list[tuple[Optional[str], str]] = []
                    if page.full_matching_images:
                        for full_img in page.full_matching_images:
                            if full_img.url:
                                candidate_pairs.append((full_img.url, "FULL"))
                    if page.partial_matching_images:
                        for part_img in page.partial_matching_images:
                            if part_img.url:
                                candidate_pairs.append((part_img.url, "PARTIAL"))

                    if not candidate_pairs:
                        candidate_pairs.append((None, "PAGE"))

                    for c_url, m_type in candidate_pairs:
                        combo = (p_url, c_url)
                        if combo not in seen_combos:
                            seen_combos.add(combo)
                            items.append(SearchResultItem(
                                source_kind="PAGE",
                                page_url=p_url,
                                domain=domain,
                                match_type=m_type,
                                page_title=p_title,
                                page_score=p_score,
                                candidate_image_url=c_url,
                                provider_metadata={"source": "pages_with_matching_images"},
                            ))

            # 2. Full matching images without page wrapper (represented honestly as ASSET_ONLY)
            if web_detection.full_matching_images:
                for img in web_detection.full_matching_images:
                    c_url = img.url
                    if not c_url:
                        continue
                    domain = normalize_domain_from_url(c_url)
                    combo = (None, c_url)
                    if combo not in seen_combos:
                        seen_combos.add(combo)
                        items.append(SearchResultItem(
                            source_kind="ASSET_ONLY",
                            page_url=None,
                            domain=domain,
                            match_type="FULL",
                            page_title=None,
                            page_score=None,
                            candidate_image_url=c_url,
                            provider_metadata={"source": "full_matching_images"},
                        ))

            # 3. Partial matching images without page wrapper (represented honestly as ASSET_ONLY)
            if web_detection.partial_matching_images:
                for img in web_detection.partial_matching_images:
                    c_url = img.url
                    if not c_url:
                        continue
                    domain = normalize_domain_from_url(c_url)
                    combo = (None, c_url)
                    if combo not in seen_combos:
                        seen_combos.add(combo)
                        items.append(SearchResultItem(
                            source_kind="ASSET_ONLY",
                            page_url=None,
                            domain=domain,
                            match_type="PARTIAL",
                            page_title=None,
                            page_score=None,
                            candidate_image_url=c_url,
                            provider_metadata={"source": "partial_matching_images"},
                        ))

            return ProviderResult(
                success=True,
                items=items,
                units_consumed=1,
            )

        except GoogleAPICallError as e:
            return ProviderResult(
                success=False,
                items=[],
                units_consumed=1,
                error_kind="REMOTE_API_ERROR",
                error_message=f"Google Cloud Vision API call failed: {e.message or str(e)}",
            )
        except Exception as e:
            return ProviderResult(
                success=False,
                items=[],
                units_consumed=0,
                error_kind="LOCAL_PREP_ERROR",
                error_message=f"Unexpected error executing search: {str(e)}",
            )
