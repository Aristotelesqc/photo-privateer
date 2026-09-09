"""Pydantic data schemas for Photo Privateer API and domain models."""
from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field
from backend.config import (
    DEFAULT_UNIT_PRICE_USD,
    DEFAULT_FREE_TIER_MONTHLY_UNITS,
    DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED,
)

# --- Libraries ---
class LibraryCreate(BaseModel):
    path: str = Field(..., description="Absolute path to directory on local disk")
    name: Optional[str] = Field(None, description="Optional nickname for the library")
    recursive: bool = Field(True, description="Whether to index subfolders recursively")

class LibraryUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    recursive: Optional[bool] = None

class LibraryOut(BaseModel):
    id: int
    path: str
    name: str
    enabled: bool
    recursive: bool
    created_at: str
    last_indexed_at: Optional[str] = None
    image_count: int = 0

# --- Images ---
class ImageOut(BaseModel):
    id: int
    library_id: int
    sha256: str
    file_path: str
    filename: str
    file_size: int
    file_modified_at: float
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    indexed_at: str
    last_seen_on_disk: str
    last_scanned_at: Optional[str] = None
    scan_count: int = 0
    match_count: int = 0
    unreviewed_count: int = 0
    thumbnail_url: str

class ImageListResponse(BaseModel):
    images: List[ImageOut]
    total: int
    page: int
    page_size: int

# --- Matches ---
class MatchOut(BaseModel):
    id: int
    image_id: int
    scan_session_id: Optional[int] = None
    page_url: str
    page_title: Optional[str] = None
    page_score: Optional[float] = None
    domain: str
    candidate_image_url: Optional[str] = None
    match_type: str  # FULL, PARTIAL, PAGE, OTHER
    provider: str
    first_seen_at: str
    last_seen_at: str
    is_new: bool
    classification: str
    classified_at: Optional[str] = None
    auto_classified_by_rule_id: Optional[int] = None
    notes: Optional[str] = None
    # Joined photo details for display
    image_filename: Optional[str] = None
    image_thumbnail_url: Optional[str] = None

class MatchUpdate(BaseModel):
    classification: Optional[str] = None
    notes: Optional[str] = None

class MatchListResponse(BaseModel):
    matches: List[MatchOut]
    total: int
    page: int
    page_size: int

# --- Domain Rules ---
class DomainRuleCreate(BaseModel):
    domain: str
    classification: str
    notes: Optional[str] = None

class DomainRuleOut(BaseModel):
    id: int
    domain: str
    classification: str
    created_at: str
    updated_at: str
    notes: Optional[str] = None

# --- Scans ---
class ScanPrepareRequest(BaseModel):
    image_ids: List[int]
    provider: Optional[str] = None

class ScanPrepareResponse(BaseModel):
    selected_count: int
    provider: str
    current_month: str
    units_used_this_month: int
    projected_units_total: int
    free_tier_allowance: int
    remaining_free_units: int
    estimated_incremental_cost_usd: float
    free_tier_exceeded: bool
    blocked_by_guard: bool
    disclaimer: str

class ScanStartRequest(BaseModel):
    image_ids: List[int]
    provider: Optional[str] = None  # None = use configured provider
    force_override_guard: bool = False

class ScanSessionOut(BaseModel):
    id: int
    started_at: str
    completed_at: Optional[str] = None
    provider: str
    total_images: int
    processed_images: int
    successful_images: int
    failed_images: int
    status: str
    notes: Optional[str] = None

# --- Usage & Accounting ---
class UsageSummaryOut(BaseModel):
    billing_period: str
    units_used_this_month: int
    free_tier_allowance: int
    remaining_free_units: int
    estimated_total_cost_usd: float
    is_guard_enabled: bool
    disclaimer: str
    total_lifetime_calls: int
    total_lifetime_units: int

class ProviderCallOut(BaseModel):
    id: int
    provider: str
    timestamp: str
    billing_period: str
    scan_session_id: Optional[int] = None
    image_id: Optional[int] = None
    attempted_units: int
    successful_units: int
    failed_units: int
    request_status: str
    estimated_cost: float
    error_message: Optional[str] = None

# --- Settings ---
class AppSettings(BaseModel):
    active_provider: str = "mock"  # "mock" or "google_vision"
    google_credentials_path: Optional[str] = None
    free_tier_monthly_units: int = DEFAULT_FREE_TIER_MONTHLY_UNITS
    block_on_free_tier_exceeded: bool = DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED
    unit_price_usd: float = DEFAULT_UNIT_PRICE_USD
    google_credentials_valid: bool = False
    google_credentials_error: Optional[str] = None

class SettingsUpdate(BaseModel):
    active_provider: Optional[str] = None
    google_credentials_path: Optional[str] = None
    free_tier_monthly_units: Optional[int] = None
    block_on_free_tier_exceeded: Optional[bool] = None
    unit_price_usd: Optional[float] = None
