import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { LibraryView } from '../views/LibraryView';
import { fetchPhotos, fetchProjects } from '../api/client';

vi.mock('../api/client', () => ({
  fetchPhotos: vi.fn(async () => ({ images: [], total: 0 })),
  fetchProjects: vi.fn(async () => ['Active project']),
  fetchGroupCandidates: vi.fn(async () => ({ pairs: [], total: 0 })),
  fetchScanHistory: vi.fn(async () => []),
  prepareScan: vi.fn(), startScan: vi.fn(), batchAssignProject: vi.fn(), dismissGroupCandidate: vi.fn(),
}));

const libraries = [
  { id: 1, name: 'Active', enabled: true, is_archived: false, image_count: 0 },
  { id: 2, name: 'History', enabled: false, is_archived: true, image_count: 0 },
];

function mount() {
  return render(<LibraryView libraries={libraries as never} settings={null} onRefreshData={vi.fn()} onNavigateToSettings={vi.fn()} onNavigateToReviewForPhoto={vi.fn()} />);
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  vi.mocked(fetchProjects).mockImplementation(async () => ['Active project']);
});

describe('Library browsing context', () => {
  it('clears a historical project filter when returning to active sources', async () => {
    vi.mocked(fetchProjects).mockImplementation(async (_library, include) => include ? ['Active project', 'Historical project'] : ['Active project']);
    mount();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include archived / disabled' }));
    const historical = await screen.findByRole('option', { name: /Historical project/ });
    fireEvent.change(historical.parentElement!, { target: { value: 'Historical project' } });
    await waitFor(() => expect(fetchPhotos).toHaveBeenLastCalledWith(expect.objectContaining({ project: 'Historical project' })));
    fireEvent.click(screen.getByRole('checkbox', { name: 'Include archived / disabled' }));
    await waitFor(() => expect(fetchPhotos).toHaveBeenLastCalledWith(expect.objectContaining({ project: undefined, include_inactive: false })));
    await waitFor(() => expect(screen.queryByRole('option', { name: /Historical project/ })).not.toBeInTheDocument());
    expect(localStorage.getItem('pp-include-inactive')).toBe('false');
  });

  it('ignores late historical project responses after the context changes', async () => {
    let resolveHistory!: (value: string[]) => void;
    const delayed = new Promise<string[]>((resolve) => { resolveHistory = resolve; });
    vi.mocked(fetchProjects).mockImplementation((_library, include) => include ? delayed : Promise.resolve(['Active project']));
    mount();
    await screen.findByRole('option', { name: /Active project/ });
    const include = screen.getByRole('checkbox', { name: 'Include archived / disabled' });
    fireEvent.click(include);
    fireEvent.click(include);
    await act(async () => { resolveHistory(['Historical project']); await delayed; });
    expect(include).not.toBeChecked();
    expect(screen.queryByRole('option', { name: /Historical project/ })).not.toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Active project/ })).toBeInTheDocument();
  });
});
