"""Pydantic data schemas for Photo Privateer API and domain models."""
from __future__ import annotations

from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict
from backend.config import (
    DEFAULT_UNIT_PRICE_USD,
    DEFAULT_FREE_TIER_MONTHLY_UNITS,
    DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED,
)

# --- Providers ---
ProviderKind = Literal["mock", "google_vision"]

class APIResponse(BaseModel):
    # The response serializer includes defaults; OpenAPI must describe those
    # fields as present rather than making the generated client guess.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

class ActionResponse(APIResponse):
    status: str

class ActionMessageResponse(ActionResponse):
    message: str

class FolderBrowseResponse(APIResponse):
    path: Optional[str]

class IndexResults(APIResponse):
    scanned: int
    added_or_updated: int
    unchanged: int
    missing: int

class IndexResponse(ActionResponse):
    results: IndexResults

class ProjectDetectionResponse(ActionResponse):
    updated_count: int

class BatchProjectResponse(APIResponse):
    updated: int
    project: Optional[str]

class GroupDeleteResponse(ActionResponse):
    group_id: int

class CandidateDismissResponse(ActionResponse):
    image_a_id: int
    image_b_id: int

# --- Libraries ---
class LibraryCreate(BaseModel):
    path: str = Field(..., description="Absolute path to directory on local disk")
    name: Optional[str] = Field(None, description="Optional nickname for the library")
    recursive: bool = Field(True, description="Whether to index subfolders recursively")
    subfolders_as_projects: bool = Field(True, description="Whether to auto-detect subfolders as distinct projects")

class LibraryUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    recursive: Optional[bool] = None
    subfolders_as_projects: Optional[bool] = None

class LibraryOut(APIResponse):
    id: int
    path: str
    name: str
    enabled: bool
    recursive: bool
    is_archived: bool = False
    subfolders_as_projects: bool = True
    created_at: str
    last_indexed_at: Optional[str] = None
    image_count: int = 0

# --- Images ---
class ImageOut(APIResponse):
    id: int
    library_id: int
    sha256: str
    dhash: Optional[str] = None
    photo_group_id: Optional[int] = None
    is_primary_representation: int = 1
    file_path: str
    filename: str
    file_size: int
    file_modified_at: float
    file_modified_at_ns: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    indexed_at: str
    last_seen_on_disk: str
    is_present_on_disk: bool = True
    project: Optional[str] = None
    project_source: Literal["auto", "manual"] = "auto"
    last_scanned_at: Optional[str] = None
    scan_count: int = 0
    match_count: int = 0
    unreviewed_count: int = 0
    # Aggregates across all members of the image's photo group (only set by photo listings)
    group_match_count: Optional[int] = None
    group_unreviewed_count: Optional[int] = None
    group_scan_count: Optional[int] = None
    group_last_scanned_at: Optional[str] = None
    thumbnail_url: str

class BatchProjectUpdate(BaseModel):
    photo_ids: List[int] = Field(..., description="List of image IDs to assign or clear project")
    project: Optional[str] = Field(None, description="Project name, or null/empty to clear")

class ImageListResponse(APIResponse):
    images: List[ImageOut]
    total: int
    page: int
    page_size: int

# --- Photo Groups ---
class PhotoGroupOut(APIResponse):
    id: int
    name: Optional[str] = None
    created_at: str
    updated_at: str
    preferred_image_id: Optional[int] = None
    notes: Optional[str] = None
    images: List[ImageOut] = Field(default_factory=list)

class PhotoGroupCreate(BaseModel):
    name: Optional[str] = None
    image_ids: List[int] = Field(..., min_length=2, description="At least two image IDs to group")
    preferred_image_id: Optional[int] = None
    notes: Optional[str] = None

class GroupCandidatePairOut(APIResponse):
    image_a: ImageOut
    image_b: ImageOut
    hamming_distance: int
    is_exact_duplicate: bool

class DismissCandidateRequest(BaseModel):
    image_a_id: int
    image_b_id: int

class SetPreferredRequest(BaseModel):
    preferred_image_id: int

class AddImageToGroupRequest(BaseModel):
    image_id: int
    set_preferred: bool = False
    # Optional explicit primary representation: the added image or any existing member
    preferred_image_id: Optional[int] = None

class GroupCandidateListOut(APIResponse):
    total: int
    pairs: List[GroupCandidatePairOut]
    # True when the list is not exhaustive (per-photo candidate cap or comparison budget reached)
    truncated: bool = False

# --- Matches ---
ClassificationLiteral = Literal["UNREVIEWED", "APPROVED", "UNAUTHORIZED", "IRRELEVANT"]
SourceKindLiteral = Literal["PAGE", "ASSET_ONLY"]
MatchTypeLiteral = Literal["FULL", "PARTIAL", "PAGE", "OTHER"]

class MatchOut(APIResponse):
    id: int
    image_id: int
    scan_session_id: Optional[int] = None
    source_kind: SourceKindLiteral = "PAGE"
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    page_score: Optional[float] = None
    domain: str
    candidate_image_url: Optional[str] = None
    match_type: MatchTypeLiteral = "FULL"
    provider: str
    first_seen_at: str
    last_seen_at: str
    is_new: bool
    acknowledged_at: Optional[str] = None
    classification: ClassificationLiteral = "UNREVIEWED"
    classified_at: Optional[str] = None
    auto_classified_by_rule_id: Optional[int] = None
    notes: Optional[str] = None
    # Joined photo details for display
    # Photo to preview: the owner when present, otherwise an available member of its group
    display_image_id: Optional[int] = None
    # Set on an observation folded into another logical discovery (its id)
    canonical_match_id: Optional[int] = None
    # Physical observations behind this logical discovery (itself plus folded observations)
    observation_count: int = 1
    # This physical observation's own original triage (differs from classification/notes when
    # the row carries a merged logical discovery state)
    observed_classification: Optional[str] = None
    observed_notes: Optional[str] = None
    observed_classified_at: Optional[str] = None
    observed_rule_id: Optional[int] = None
    # Merged observations carry incompatible decisions; cleared only by an explicit classification
    triage_conflict: bool = False
    # Last explicit review action by the user (classification, acknowledgement or notes)
    explicit_review_at: Optional[str] = None
    # Discovery inherited from a permanently purged photo of the same group (provenance)
    inherited_from: Optional[str] = None
    image_filename: Optional[str] = None
    image_thumbnail_url: Optional[str] = None
    image_project: Optional[str] = None

class MatchUpdate(BaseModel):
    classification: Optional[ClassificationLiteral] = None
    notes: Optional[str] = None
    acknowledged: Optional[bool] = None

class MatchListResponse(APIResponse):
    matches: List[MatchOut]
    total: int
    page: int
    page_size: int

# --- Domain Rules ---
class DomainRuleCreate(BaseModel):
    domain: str = Field(..., min_length=1)
    classification: ClassificationLiteral
    notes: Optional[str] = None

class DomainRuleOut(APIResponse):
    id: int
    domain: str
    classification: ClassificationLiteral
    created_at: str
    updated_at: str
    notes: Optional[str] = None

# --- Scans ---
class ScanPrepareRequest(BaseModel):
    image_ids: List[int] = Field(..., min_length=1)
    provider: Optional[ProviderKind] = None

class ScanPrepareResponse(APIResponse):
    selected_count: int
    usable_count: int
    missing_count: int
    # Selected photos that are not sent to the provider themselves because their photo
    # group is searched once through its primary representation
    grouped_variant_count: int = 0
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
    image_ids: List[int] = Field(..., min_length=1)
    provider: Optional[ProviderKind] = None  # None = use configured provider
    force_override_guard: bool = False

ScanStatusLiteral = Literal["RUNNING", "COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"]

class ScanSessionOut(APIResponse):
    id: int
    started_at: str
    completed_at: Optional[str] = None
    provider: str
    total_images: int
    processed_images: int
    successful_images: int
    failed_images: int
    status: ScanStatusLiteral
    cancel_requested: bool = False
    notes: Optional[str] = None

# --- Usage & Accounting ---
class UsageSummaryOut(APIResponse):
    billing_period: str
    units_used_this_month: int
    free_tier_allowance: int
    remaining_free_units: int
    estimated_total_cost_usd: float
    is_guard_enabled: bool
    disclaimer: str
    total_lifetime_calls: int
    total_lifetime_units: int

class ProviderCallOut(APIResponse):
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
class AppSettings(APIResponse):
    active_provider: ProviderKind = "mock"
    google_credentials_path: Optional[str] = None
    free_tier_monthly_units: int = Field(default=DEFAULT_FREE_TIER_MONTHLY_UNITS, ge=0)
    block_on_free_tier_exceeded: bool = DEFAULT_BLOCK_ON_FREE_TIER_EXCEEDED
    unit_price_usd: float = Field(default=DEFAULT_UNIT_PRICE_USD, ge=0.0)
    google_credentials_valid: bool = False
    google_credentials_error: Optional[str] = None
    adc_available: bool = False
    adc_project_id: Optional[str] = None
    auth_mode: Literal["adc", "service_account", "none"] = "none"

class SettingsUpdate(BaseModel):
    active_provider: Optional[Literal["mock", "google_vision"]] = None
    google_credentials_path: Optional[str] = None
    free_tier_monthly_units: Optional[int] = Field(default=None, ge=0)
    block_on_free_tier_exceeded: Optional[bool] = None
    unit_price_usd: Optional[float] = Field(default=None, ge=0.0)

