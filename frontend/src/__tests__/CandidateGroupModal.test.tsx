import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { CandidateGroupModal } from '../components/CandidateGroupModal';
import { GroupCandidatePair, ImageItem } from '../types';

const mockImageA: ImageItem = {
  id: 101,
  library_id: 1,
  sha256: 'abc101',
  dhash: '0123456789abcdef',
  file_path: '/photos/sunset_highres.jpg',
  filename: 'sunset_highres.jpg',
  file_size: 2048000,
  file_modified_at: 1726000000.0,
  width: 3000,
  height: 2000,
  format: 'JPEG',
  indexed_at: '2026-09-14T00:00:00Z',
  last_seen_on_disk: '2026-09-14T00:00:00Z',
  is_present_on_disk: true,
  project: 'Vacation',
  project_source: 'manual',
  last_scanned_at: null,
  scan_count: 0,
  match_count: 0,
  unreviewed_count: 0,
  thumbnail_url: '/api/photos/101/thumbnail',
};

const mockImageB: ImageItem = {
  id: 102,
  library_id: 1,
  sha256: 'def102',
  dhash: '0123456789abcde0',
  file_path: '/photos/sunset_web.jpg',
  filename: 'sunset_web.jpg',
  file_size: 204800,
  file_modified_at: 1726000000.0,
  width: 800,
  height: 533,
  format: 'JPEG',
  indexed_at: '2026-09-14T00:00:00Z',
  last_seen_on_disk: '2026-09-14T00:00:00Z',
  is_present_on_disk: true,
  project: 'Vacation',
  project_source: 'manual',
  last_scanned_at: null,
  scan_count: 0,
  match_count: 0,
  unreviewed_count: 0,
  thumbnail_url: '/api/photos/102/thumbnail',
};

const mockCandidate: GroupCandidatePair = {
  image_a: mockImageA,
  image_b: mockImageB,
  hamming_distance: 3,
  is_exact_duplicate: false,
};

describe('CandidateGroupModal Component', () => {
  it('renders empty state when no candidates remain', () => {
    render(
      <CandidateGroupModal
        candidates={[]}
        onGroup={vi.fn()}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/All Caught Up/i)).toBeInTheDocument();
    expect(screen.getByText(/No unreviewed candidate photo representations/i)).toBeInTheDocument();
  });

  it('renders candidate representations side-by-side with match metrics', () => {
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        onGroup={vi.fn()}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/Perceptual Source Representations/i)).toBeInTheDocument();
    expect(screen.getByText('sunset_highres.jpg')).toBeInTheDocument();
    expect(screen.getByText('sunset_web.jpg')).toBeInTheDocument();
    expect(screen.getByText(/3\/64 bits difference/i)).toBeInTheDocument();
    expect(screen.getByTestId('btn-group-representations')).toBeInTheDocument();
    expect(screen.getByTestId('btn-keep-separate')).toBeInTheDocument();
  });

  it('triggers onGroup with selected preferred image when clicking Group as Representations', async () => {
    const onGroupMock = vi.fn().mockResolvedValue(undefined);
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        onGroup={onGroupMock}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    const groupBtn = screen.getByTestId('btn-group-representations');
    await act(async () => {
      fireEvent.click(groupBtn);
    });

    expect(onGroupMock).toHaveBeenCalledWith(101, 102, 101);
  });

  it('allows switching preferred image to B before grouping', async () => {
    const onGroupMock = vi.fn().mockResolvedValue(undefined);
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        onGroup={onGroupMock}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    const candidateBCard = screen.getByText('Candidate B').closest('div');
    if (candidateBCard) {
      await act(async () => {
        fireEvent.click(candidateBCard);
      });
    }

    const groupBtn = screen.getByTestId('btn-group-representations');
    await act(async () => {
      fireEvent.click(groupBtn);
    });

    expect(onGroupMock).toHaveBeenCalledWith(101, 102, 102);
  });

  it('triggers onDismiss when clicking Keep Separate', async () => {
    const onDismissMock = vi.fn().mockResolvedValue(undefined);
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        onGroup={vi.fn()}
        onDismiss={onDismissMock}
        onClose={vi.fn()}
      />
    );

    const dismissBtn = screen.getByTestId('btn-keep-separate');
    await act(async () => {
      fireEvent.click(dismissBtn);
    });

    expect(onDismissMock).toHaveBeenCalledWith(101, 102);
  });
});
