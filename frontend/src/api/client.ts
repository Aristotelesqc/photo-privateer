import {
  Library,
  ImageItem,
  ImageListResponse,
  MatchItem,
  MatchListResponse,
  ClassificationType,
  DomainRule,
  ScanSession,
  ScanPrepareResponse,
  UsageSummary,
  ProviderCall,
  AppSettings,
  TestGoogleAuthResponse,
} from '../types';

const API_BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!res.ok) {
    let errorDetail = `Request failed: ${res.status}`;
    try {
      const errorJson = await res.json();
      if (errorJson.detail) {
        errorDetail = typeof errorJson.detail === 'string' ? errorJson.detail : JSON.stringify(errorJson.detail);
      }
    } catch {
      // fallback to status text
      errorDetail = res.statusText || errorDetail;
    }
    throw new Error(errorDetail);
  }

  return res.json();
}

// --- Libraries ---
export const fetchLibraries = () => request<Library[]>('/libraries');

export const createLibrary = (
  path: string,
  name?: string,
  recursive: boolean = true,
  subfolders_as_projects: boolean = true
) =>
  request<Library>('/libraries', {
    method: 'POST',
    body: JSON.stringify({ path, name, recursive, subfolders_as_projects }),
  });

export const updateLibrary = (
  id: number,
  updates: { name?: string; enabled?: boolean; recursive?: boolean; subfolders_as_projects?: boolean }
) =>
  request<Library>(`/libraries/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });

export const deleteLibrary = (id: number, purgePermanently: boolean = false) =>
  request<{ status: string; message: string }>(
    purgePermanently ? `/libraries/${id}?purge_permanently=true` : `/libraries/${id}`,
    {
      method: 'DELETE',
    }
  );

export const archiveLibrary = (id: number) =>
  request<Library>(`/libraries/${id}/archive`, {
    method: 'POST',
  });

export const unarchiveLibrary = (id: number) =>
  request<Library>(`/libraries/${id}/unarchive`, {
    method: 'POST',
  });

export const browseFolder = () =>
  request<{ path: string | null }>('/libraries/browse-folder', {
    method: 'POST',
  });

export const indexLibrary = (id: number) =>
  request<{ status: string; results: { scanned: number; added_or_updated: number; unchanged: number } }>(
    `/libraries/${id}/index`,
    { method: 'POST' }
  );

export const detectLibraryProjects = (id: number) =>
  request<{ status: string; updated_count: number }>(
    `/libraries/${id}/detect-projects`,
    { method: 'POST' }
  );

// --- Photos ---
export const fetchProjects = (library_id?: number) => {
  const query = library_id !== undefined ? `?library_id=${library_id}` : '';
  return request<string[]>(`/photos/projects${query}`);
};

export const batchAssignProject = (photo_ids: number[], project: string | null) =>
  request<{ updated: number; project: string | null }>('/photos/batch-project', {
    method: 'POST',
    body: JSON.stringify({ photo_ids, project }),
  });

export const fetchPhotos = (params: {
  library_id?: number;
  search?: string;
  project?: string;
  filter_status?: 'all' | 'unscanned' | 'scanned' | 'has_matches' | 'has_unreviewed';
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}) => {
  const query = new URLSearchParams();
  if (params.library_id !== undefined) query.set('library_id', String(params.library_id));
  if (params.search) query.set('search', params.search);
  if (params.project) query.set('project', params.project);
  if (params.filter_status) query.set('filter_status', params.filter_status);
  if (params.sort_by) query.set('sort_by', params.sort_by);
  if (params.sort_dir) query.set('sort_dir', params.sort_dir);
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));

  return request<ImageListResponse>(`/photos?${query.toString()}`);
};

export const fetchPhoto = (id: number) => request<ImageItem>(`/photos/${id}`);

// --- Scans ---
export const prepareScan = (image_ids: number[], provider?: string) =>
  request<ScanPrepareResponse>('/scans/prepare', {
    method: 'POST',
    body: JSON.stringify({ image_ids, provider }),
  });

export const startScan = (image_ids: number[], provider?: string, force_override_guard: boolean = false) =>
  request<ScanSession>('/scans/start', {
    method: 'POST',
    body: JSON.stringify({ image_ids, provider, force_override_guard }),
  });

export const fetchScanHistory = (limit: number = 20) =>
  request<ScanSession[]>(`/scans/history?limit=${limit}`);

export const fetchScanSession = (id: number) =>
  request<ScanSession>(`/scans/${id}`);

export const cancelScan = (id: number) =>
  request<ScanSession>(`/scans/${id}/cancel`, {
    method: 'POST',
  });

// --- Matches ---
export const fetchMatches = (params: {
  image_id?: number;
  project?: string;
  classification?: ClassificationType;
  is_new_only?: boolean;
  domain?: string;
  search?: string;
  sort_by?: string;
  sort_dir?: 'asc' | 'desc';
  page?: number;
  page_size?: number;
}) => {
  const query = new URLSearchParams();
  if (params.image_id !== undefined) query.set('image_id', String(params.image_id));
  if (params.project) query.set('project', params.project);
  if (params.classification) query.set('classification', params.classification);
  if (params.is_new_only) query.set('is_new_only', 'true');
  if (params.domain) query.set('domain', params.domain);
  if (params.search) query.set('search', params.search);
  if (params.sort_by) query.set('sort_by', params.sort_by);
  if (params.sort_dir) query.set('sort_dir', params.sort_dir);
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));

  return request<MatchListResponse>(`/matches?${query.toString()}`);
};

export const updateMatch = (id: number, updates: { classification?: ClassificationType; notes?: string | null }) =>
  request<MatchItem>(`/matches/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });


// --- Domain Rules ---
export const fetchRules = () => request<DomainRule[]>('/rules');

export const createRule = (domain: string, classification: ClassificationType, notes?: string) =>
  request<DomainRule>('/rules', {
    method: 'POST',
    body: JSON.stringify({ domain, classification, notes }),
  });

export const deleteRule = (id: number) =>
  request<{ status: string; message: string }>(`/rules/${id}`, {
    method: 'DELETE',
  });

// --- Usage ---
export const fetchUsageSummary = (period?: string) => {
  const query = period ? `?period=${period}` : '';
  return request<UsageSummary>(`/usage/summary${query}`);
};

export const fetchProviderCalls = (limit: number = 50, offset: number = 0) =>
  request<ProviderCall[]>(`/usage/calls?limit=${limit}&offset=${offset}`);

// --- Settings ---
export const fetchSettings = () => request<AppSettings>('/settings');

export const updateSettings = (updates: Partial<AppSettings>) =>
  request<AppSettings>('/settings', {
    method: 'PATCH',
    body: JSON.stringify(updates),
  });

export const validateFolder = (path: string) =>
  request<{ valid: boolean; resolved_path: string; is_dir: boolean; error: string | null }>(
    '/settings/validate-folder',
    {
      method: 'POST',
      body: JSON.stringify({ path }),
    }
  );

export const testGoogleAuth = (credentials_path?: string) =>
  request<TestGoogleAuthResponse>('/settings/test-google-auth', {
    method: 'POST',
    body: JSON.stringify({ credentials_path: credentials_path || null }),
  });
