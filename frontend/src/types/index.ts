export interface Library {
  id: number;
  path: string;
  name: string;
  enabled: boolean;
  recursive: boolean;
  is_archived: boolean;
  subfolders_as_projects: boolean;
  created_at: string;
  last_indexed_at: string | null;
  image_count: number;
}

export interface ImageItem {
  id: number;
  library_id: number;
  sha256: string;
  dhash?: string | null;
  photo_group_id?: number | null;
  is_primary_representation?: number;
  file_path: string;
  filename: string;
  file_size: number;
  file_modified_at: number;
  width: number | null;
  height: number | null;
  format: string | null;
  indexed_at: string;
  last_seen_on_disk: string;
  is_present_on_disk: boolean;
  project: string | null;
  project_source?: 'auto' | 'manual';
  last_scanned_at: string | null;
  scan_count: number;
  match_count: number;
  unreviewed_count: number;
  thumbnail_url: string;
}

export interface PhotoGroup {
  id: number;
  name?: string | null;
  created_at: string;
  updated_at: string;
  preferred_image_id?: number | null;
  notes?: string | null;
  images: ImageItem[];
}

export interface GroupCandidatePair {
  image_a: ImageItem;
  image_b: ImageItem;
  hamming_distance: number;
  is_exact_duplicate: boolean;
}

export interface PhotoGroupCreatePayload {
  name?: string;
  image_ids: number[];
  preferred_image_id?: number;
  notes?: string;
}

export interface ImageListResponse {
  images: ImageItem[];
  total: number;
  page: number;
  page_size: number;
}

export type ClassificationType = 'UNREVIEWED' | 'APPROVED' | 'UNAUTHORIZED' | 'IRRELEVANT';

export interface MatchItem {
  id: number;
  image_id: number;
  scan_session_id: number | null;
  page_url: string | null;
  page_title: string | null;
  page_score: number | null;
  domain: string;
  candidate_image_url: string | null;
  match_type: 'FULL' | 'PARTIAL' | 'PAGE' | 'OTHER';
  source_kind: 'PAGE' | 'ASSET_ONLY';

  provider: string;
  first_seen_at: string;
  last_seen_at: string;
  is_new: boolean;
  acknowledged_at: string | null;
  classification: ClassificationType;
  classified_at: string | null;
  auto_classified_by_rule_id: number | null;
  notes: string | null;
  image_filename?: string | null;
  image_thumbnail_url?: string | null;
  image_project?: string | null;
}

export interface MatchListResponse {
  matches: MatchItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface DomainRule {
  id: number;
  domain: string;
  classification: ClassificationType;
  created_at: string;
  updated_at: string;
  notes: string | null;
}

export interface ScanSession {
  id: number;
  started_at: string;
  completed_at: string | null;
  provider: string;
  total_images: number;
  processed_images: number;
  successful_images: number;
  failed_images: number;
  status: 'RUNNING' | 'COMPLETED' | 'CANCELLED' | 'FAILED' | 'INTERRUPTED';
  cancel_requested: boolean;
  notes: string | null;
}

export interface ScanPrepareResponse {
  selected_count: number;
  usable_count: number;
  missing_count: number;
  provider: string;
  current_month: string;
  units_used_this_month: number;
  projected_units_total: number;
  free_tier_allowance: number;
  remaining_free_units: number;
  estimated_incremental_cost_usd: number;
  free_tier_exceeded: boolean;
  blocked_by_guard: boolean;
  disclaimer: string;
}

export interface UsageSummary {
  billing_period: string;
  units_used_this_month: number;
  free_tier_allowance: number;
  remaining_free_units: number;
  estimated_total_cost_usd: number;
  is_guard_enabled: boolean;
  disclaimer: string;
  total_lifetime_calls: number;
  total_lifetime_units: number;
}

export interface ProviderCall {
  id: number;
  provider: string;
  timestamp: string;
  billing_period: string;
  scan_session_id: number | null;
  image_id: number | null;
  attempted_units: number;
  successful_units: number;
  failed_units: number;
  request_status: string;
  estimated_cost: number;
  error_message: string | null;
}

export interface AppSettings {
  active_provider: 'mock' | 'google_vision';
  google_credentials_path: string | null;
  free_tier_monthly_units: number;
  block_on_free_tier_exceeded: boolean;
  unit_price_usd: number;
  google_credentials_valid: boolean;
  google_credentials_error: string | null;
  adc_available: boolean;
  adc_project_id: string | null;
  auth_mode: 'adc' | 'service_account' | 'none';
}

export interface TestGoogleAuthResponse {
  success: boolean;
  auth_mode: string;
  message: string | null;
  error: string | null;
  project_id: string | null;
  service_account_email: string | null;
}
