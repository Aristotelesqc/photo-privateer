import type { ApiSchemas, ApiOperations } from '../api/generated';

// Public names used by the UI, all derived from the server's generated contract.
export type Library = ApiSchemas['LibraryOut'];
export type ImageItem = ApiSchemas['ImageOut'];
export type ImageListResponse = ApiSchemas['ImageListResponse'];
export type PhotoGroup = ApiSchemas['PhotoGroupOut'];
export type GroupCandidatePair = ApiSchemas['GroupCandidatePairOut'];
export type GroupCandidateList = ApiSchemas['GroupCandidateListOut'];
export type PhotoGroupCreatePayload = ApiSchemas['PhotoGroupCreate'];
export type AddImageToGroupPayload = ApiSchemas['AddImageToGroupRequest'];
export type MatchItem = ApiSchemas['MatchOut'];
export type MatchListResponse = ApiSchemas['MatchListResponse'];
export type ClassificationType = ApiSchemas['DomainRuleCreate']['classification'];
export type DomainRule = ApiSchemas['DomainRuleOut'];
export type ScanSession = ApiSchemas['ScanSessionOut'];
export type ScanPrepareResponse = ApiSchemas['ScanPrepareResponse'];
export type UsageSummary = ApiSchemas['UsageSummaryOut'];
export type ProviderCall = ApiSchemas['ProviderCallOut'];
export type AppSettings = ApiSchemas['AppSettings'];
export type TestGoogleAuthResponse = ApiSchemas['TestGoogleAuthResponse'];
export type StatusFilterType = NonNullable<ApiOperations['GET /api/photos']['query']['filter_status']>;
