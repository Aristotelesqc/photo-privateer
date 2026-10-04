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
  PhotoGroup,
  GroupCandidateList,
  AddImageToGroupPayload,
  PhotoGroupCreatePayload,
} from '../types';
import type { ApiSchemas, ApiOperations } from './generated';

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
      const errorJson: unknown = await res.json();
      if (errorJson && typeof errorJson === 'object' && 'detail' in errorJson && errorJson.detail) {
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

function jsonBody<K extends keyof ApiOperations>(_operation: K, payload: ApiOperations[K]['body']): string {
  return JSON.stringify(payload);
}

// URL query strings omit null; JSON bodies retain null as an explicit value.
type QueryInput<T> = { [K in keyof T]: Exclude<T[K], null> };

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
    body: jsonBody('POST /api/libraries', { path, name, recursive, subfolders_as_projects }),
  });

export const updateLibrary = (
  id: number,
  updates: ApiSchemas['LibraryUpdate']
) =>
  request<Library>(`/libraries/${id}`, {
    method: 'PATCH',
    body: jsonBody('PATCH /api/libraries/{library_id}', updates),
  });

export const deleteLibrary = (id: number, purgePermanently: boolean = false) =>
  request<ApiOperations['DELETE /api/libraries/{library_id}']['response']>(
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
  request<ApiOperations['POST /api/libraries/browse-folder']['response']>('/libraries/browse-folder', {
    method: 'POST',
  });

export const indexLibrary = (id: number) =>
  request<ApiOperations['POST /api/libraries/{library_id}/index']['response']>(
    `/libraries/${id}/index`,
    { method: 'POST' }
  );

export const detectLibraryProjects = (id: number) =>
  request<ApiOperations['POST /api/libraries/{library_id}/detect-projects']['response']>(
    `/libraries/${id}/detect-projects`,
    { method: 'POST' }
  );

// --- Photos ---
export const fetchProjects = (library_id?: number) => {
  const query = library_id !== undefined ? `?library_id=${library_id}` : '';
  return request<string[]>(`/photos/projects${query}`);
};

export const batchAssignProject = (photo_ids: number[], project: string | null) =>
  request<ApiOperations['POST /api/photos/batch-project']['response']>('/photos/batch-project', {
    method: 'POST',
    body: jsonBody('POST /api/photos/batch-project', { photo_ids, project }),
  });

export const fetchPhotos = (params: QueryInput<ApiOperations['GET /api/photos']['query']>) => {
  const query = new URLSearchParams();
  if (params.library_id !== undefined) query.set('library_id', String(params.library_id));
  if (params.search) query.set('search', params.search);
  if (params.project) query.set('project', params.project);
  if (params.group_id !== undefined) query.set('group_id', String(params.group_id));
  if (params.filter_status) query.set('filter_status', params.filter_status);
  if (params.sort_by) query.set('sort_by', params.sort_by);
  if (params.sort_dir) query.set('sort_dir', params.sort_dir);
  if (params.page) query.set('page', String(params.page));
  if (params.page_size) query.set('page_size', String(params.page_size));

  return request<ImageListResponse>(`/photos?${query.toString()}`);
};

export const fetchPhoto = (id: number) => request<ImageItem>(`/photos/${id}`);

// --- Scans ---
export const prepareScan = (image_ids: number[], provider?: AppSettings['active_provider']) =>
  request<ScanPrepareResponse>('/scans/prepare', {
    method: 'POST',
    body: jsonBody('POST /api/scans/prepare', { image_ids, provider }),
  });

export const startScan = (image_ids: number[], provider?: AppSettings['active_provider'], force_override_guard: boolean = false) =>
  request<ScanSession>('/scans/start', {
    method: 'POST',
    body: jsonBody('POST /api/scans/start', { image_ids, provider, force_override_guard }),
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
export const fetchMatches = (params: QueryInput<ApiOperations['GET /api/matches']['query']>) => {
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

export const updateMatch = (id: number, updates: ApiSchemas['MatchUpdate']) =>
  request<MatchItem>(`/matches/${id}`, {
    method: 'PATCH',
    body: jsonBody('PATCH /api/matches/{match_id}', updates),
  });


// --- Domain Rules ---
export const fetchRules = () => request<DomainRule[]>('/rules');

export const createRule = (domain: string, classification: ClassificationType, notes?: string) =>
  request<DomainRule>('/rules', {
    method: 'POST',
    body: jsonBody('POST /api/rules', { domain, classification, notes }),
  });

export const deleteRule = (id: number) =>
  request<ApiOperations['DELETE /api/rules/{rule_id}']['response']>(`/rules/${id}`, {
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

export const updateSettings = (updates: ApiSchemas['SettingsUpdate']) =>
  request<AppSettings>('/settings', {
    method: 'PATCH',
    body: jsonBody('PATCH /api/settings', updates),
  });

export const validateFolder = (path: string) =>
  request<ApiOperations['POST /api/settings/validate-folder']['response']>(
    '/settings/validate-folder',
    {
      method: 'POST',
      body: jsonBody('POST /api/settings/validate-folder', { path }),
    }
  );

export const testGoogleAuth = (credentials_path?: string) =>
  request<TestGoogleAuthResponse>('/settings/test-google-auth', {
    method: 'POST',
    body: jsonBody('POST /api/settings/test-google-auth', { credentials_path: credentials_path || null }),
  });

// --- Photo Groups & Deduplication ---
export const fetchGroupCandidates = (
  params?: QueryInput<ApiOperations['GET /api/groups/candidates']['query']> | number,
  limitParam: number = 50
) => {
  let threshold = 10;
  let limit = 50;
  let libraryId: number | undefined = undefined;
  let offset = 0;

  if (typeof params === 'number') {
    threshold = params;
    limit = limitParam;
  } else if (params && typeof params === 'object') {
    if (params.threshold !== undefined) threshold = params.threshold;
    if (params.limit !== undefined) limit = params.limit;
    if (params.library_id !== undefined) libraryId = params.library_id;
    if (params.offset !== undefined) offset = params.offset;
  }

  const query = new URLSearchParams({
    threshold: String(threshold),
    limit: String(limit),
    offset: String(offset),
  });
  if (libraryId !== undefined) {
    query.set('library_id', String(libraryId));
  }

  return request<GroupCandidateList>(`/groups/candidates?${query.toString()}`);
};

export const addImageToGroup = (groupId: number, imageId: number, preferredImageId?: number) => {
  const payload: AddImageToGroupPayload = { image_id: imageId };
  if (preferredImageId !== undefined) payload.preferred_image_id = preferredImageId;
  return request<PhotoGroup>(`/groups/${groupId}/images`, {
    method: 'POST',
    body: jsonBody('POST /api/groups/{group_id}/images', payload),
  });
};

export const dismissGroupCandidate = (imageAId: number, imageBId: number) =>
  request<ApiOperations['POST /api/groups/candidates/dismiss']['response']>('/groups/candidates/dismiss', {
    method: 'POST',
    body: jsonBody('POST /api/groups/candidates/dismiss', { image_a_id: imageAId, image_b_id: imageBId }),
  });

export const createPhotoGroup = (payload: PhotoGroupCreatePayload) =>
  request<PhotoGroup>('/groups', {
    method: 'POST',
    body: jsonBody('POST /api/groups', payload),
  });

export const fetchPhotoGroups = () => request<PhotoGroup[]>('/groups');

export const fetchPhotoGroup = (groupId: number) => request<PhotoGroup>(`/groups/${groupId}`);

export const setPreferredImage = (groupId: number, imageId: number) =>
  request<PhotoGroup>(`/groups/${groupId}/preferred`, {
    method: 'PUT',
    body: jsonBody('PUT /api/groups/{group_id}/preferred', { preferred_image_id: imageId }),
  });

export const deletePhotoGroup = (groupId: number) =>
  request<ApiOperations['DELETE /api/groups/{group_id}']['response']>(`/groups/${groupId}`, {
    method: 'DELETE',
  });

export const removeImageFromGroup = (groupId: number, imageId: number) =>
  request<PhotoGroup | null>(`/groups/${groupId}/images/${imageId}`, {
    method: 'DELETE',
  });
