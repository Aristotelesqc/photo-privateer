import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import React from 'react';
import { CandidateGroupModal } from '../components/CandidateGroupModal';
import * as client from '../api/client';
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

  it('triggers onDismiss and closes modal when resolving the last pair', async () => {
    const onDismissMock = vi.fn().mockResolvedValue(undefined);
    const onCloseMock = vi.fn();
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        onGroup={vi.fn()}
        onDismiss={onDismissMock}
        onClose={onCloseMock}
      />
    );

    const dismissBtn = screen.getByTestId('btn-keep-separate');
    await act(async () => {
      fireEvent.click(dismissBtn);
    });

    expect(onDismissMock).toHaveBeenCalledWith(101, 102);
    expect(onCloseMock).toHaveBeenCalled();
  });

  it('triggers onClose when clicking header close button', async () => {
    const onCloseMock = vi.fn();
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        onGroup={vi.fn()}
        onDismiss={vi.fn()}
        onClose={onCloseMock}
      />
    );

    const closeBtn = screen.getByTestId('btn-close-candidate-modal');
    await act(async () => {
      fireEvent.click(closeBtn);
    });

    expect(onCloseMock).toHaveBeenCalled();
  });

  it('renders exact duplicate badge with 100% match', () => {
    const exactCandidate: GroupCandidatePair = {
      ...mockCandidate,
      hamming_distance: 0,
      is_exact_duplicate: true,
    };
    render(
      <CandidateGroupModal
        candidates={[exactCandidate]}
        onGroup={vi.fn()}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/Exact Duplicate \(100% Match\)/i)).toBeInTheDocument();
  });

  it('resets selected preferred representation to Candidate A when advancing to next pair', async () => {
    const pair2: GroupCandidatePair = {
      image_a: { ...mockImageA, id: 201, filename: 'photo2_a.jpg' },
      image_b: { ...mockImageB, id: 202, filename: 'photo2_b.jpg' },
      hamming_distance: 2,
      is_exact_duplicate: false,
    };
    const onGroupMock = vi.fn().mockResolvedValue(undefined);
    render(
      <CandidateGroupModal
        candidates={[mockCandidate, pair2]}
        onGroup={onGroupMock}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    // Select Candidate B on pair 1
    const candidateBCard = screen.getByText('Candidate B').closest('div');
    if (candidateBCard) {
      await act(async () => {
        fireEvent.click(candidateBCard);
      });
    }

    // Advance to pair 2
    const nextBtn = screen.getByTitle('Next candidate');
    await act(async () => {
      fireEvent.click(nextBtn);
    });

    // Group pair 2 - should default to Candidate A (id 201) because of state reset
    const groupBtn = screen.getByTestId('btn-group-representations');
    await act(async () => {
      fireEvent.click(groupBtn);
    });

    expect(onGroupMock).toHaveBeenCalledWith(201, 202, 201);
  });

  it('displays candidate-group-error alert banner when grouping action fails', async () => {
    const onGroupMock = vi.fn().mockRejectedValue(new Error('Network failure'));
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

    const errorAlert = screen.getByTestId('candidate-group-error');
    expect(errorAlert).toBeInTheDocument();
    expect(errorAlert).toHaveTextContent('Network failure');
  });

  it('displays dynamic label "Add to Existing Group" when candidate is already grouped', () => {
    const alreadyGroupedCandidate: GroupCandidatePair = {
      image_a: { ...mockImageA, photo_group_id: 10 },
      image_b: mockImageB,
      hamming_distance: 4,
      is_exact_duplicate: false,
    };
    render(
      <CandidateGroupModal
        candidates={[alreadyGroupedCandidate]}
        onGroup={vi.fn()}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Add to Existing Group')).toBeInTheDocument();
    expect(screen.getByTestId('btn-add-to-existing-group')).toBeInTheDocument();
  });

  describe('preferred representation with an existing group (fallback path)', () => {
    beforeEach(() => {
      vi.restoreAllMocks();
    });

    it('promotes the already-grouped photo when the user picks it while adding the new one', async () => {
      const addSpy = vi.spyOn(client, 'addImageToGroup').mockResolvedValue({
        id: 10, created_at: '', updated_at: '', preferred_image_id: 101, images: [],
      });
      const pair: GroupCandidatePair = {
        image_a: { ...mockImageA, photo_group_id: 10, is_primary_representation: 0 },
        image_b: mockImageB,
        hamming_distance: 4,
        is_exact_duplicate: false,
      };
      render(<CandidateGroupModal candidates={[pair]} onClose={vi.fn()} />);

      // Candidate A (the grouped variant) is selected by default
      await act(async () => {
        fireEvent.click(screen.getByTestId('btn-add-to-existing-group'));
      });
      expect(addSpy).toHaveBeenCalledWith(10, 102, 101);
    });

    it('keeps an existing group primary selected by default even when it is Candidate B', async () => {
      const addSpy = vi.spyOn(client, 'addImageToGroup').mockResolvedValue({
        id: 20, created_at: '', updated_at: '', preferred_image_id: 102, images: [],
      });
      const pair: GroupCandidatePair = {
        image_a: mockImageA,
        image_b: { ...mockImageB, photo_group_id: 20, is_primary_representation: 1 },
        hamming_distance: 2,
        is_exact_duplicate: false,
      };
      render(<CandidateGroupModal candidates={[pair]} onClose={vi.fn()} />);

      await act(async () => {
        fireEvent.click(screen.getByTestId('btn-add-to-existing-group'));
      });
      expect(addSpy).toHaveBeenCalledWith(20, 101, 102);
    });
  });

  it('shows the total number of candidates when only the closest page is loaded', () => {
    render(
      <CandidateGroupModal
        candidates={[mockCandidate]}
        totalCount={66}
        onGroup={vi.fn()}
        onDismiss={vi.fn()}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByTestId('candidate-total-note')).toHaveTextContent('showing the 1 closest of 66');
  });
});
