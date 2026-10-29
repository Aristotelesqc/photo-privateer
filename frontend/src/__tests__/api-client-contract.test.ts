import { afterEach, expect, it, vi } from 'vitest';
import { fetchPhotos, fetchGroupCandidates, updateMatch } from '../api/client';

afterEach(() => vi.unstubAllGlobals());

it('serializes missing filters and explicit false/null acknowledgement updates', async () => {
  const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', fetchMock);
  await fetchPhotos({ filter_status: 'missing', library_id: 3 });
  expect(fetchMock.mock.calls[0][0]).toContain('filter_status=missing');
  await updateMatch(9, { acknowledged: false, notes: null });
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ acknowledged: false, notes: null });
  await updateMatch(9, { acknowledged: true });
  expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ acknowledged: true });
  await fetchGroupCandidates({ offset: 10 });
  expect(fetchMock.mock.calls[3][0]).toContain('offset=10');
});

it('narrows structured validation errors without assuming a string detail', async () => {
  const detail = [{ loc: ['query', 'page'], msg: 'Invalid page', type: 'greater_than_equal' }];
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail }) }));
  await expect(fetchPhotos({ page: 0 })).rejects.toThrow(JSON.stringify(detail));
});

it('handles null or unreadable error payloads using the HTTP status', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => null }));
  await expect(fetchPhotos({})).rejects.toThrow('Request failed: 500');
});
