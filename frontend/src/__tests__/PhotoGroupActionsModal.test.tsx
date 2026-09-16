import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import React from 'react';
import { PhotoGroupActionsModal } from '../engines/library/PhotoGroupActionsModal';
import { ImageItem, PhotoGroup } from '../types';
import * as client from '../api/client';

vi.mock('../api/client', () => ({
  fetchPhotoGroup: vi.fn(),
  setPreferredImage: vi.fn(),
  removeImageFromGroup: vi.fn(),
  deletePhotoGroup: vi.fn(),
}));

const mockPhotoVariant: ImageItem = {
  id: 102,
  library_id: 1,
  sha256: 'def102',
  dhash: '0123456789abcde0',
  photo_group_id: 55,
  is_primary_representation: 0,
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

const mockPhotoPrimary: ImageItem = {
  id: 101,
  library_id: 1,
  sha256: 'abc101',
  dhash: '0123456789abcdef',
  photo_group_id: 55,
  is_primary_representation: 1,
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

const mockGroup: PhotoGroup = {
  id: 55,
  name: 'Sunset Group',
  created_at: '2026-09-14T00:00:00Z',
  updated_at: '2026-09-14T00:00:00Z',
  preferred_image_id: 101,
  images: [mockPhotoPrimary, mockPhotoVariant],
};

describe('PhotoGroupActionsModal Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.fetchPhotoGroup).mockResolvedValue(mockGroup);
  });

  it('renders modal with photo information and group members', async () => {
    render(
      <PhotoGroupActionsModal
        photo={mockPhotoVariant}
        isOpen={true}
        onClose={vi.fn()}
        onGroupUpdated={vi.fn()}
      />
    );

    expect(screen.getByText(/Manage Perceptual Group #55/i)).toBeInTheDocument();
    expect(screen.getByText('sunset_web.jpg')).toBeInTheDocument();
    expect(screen.getByTestId('badge-variant')).toBeInTheDocument();

    await waitFor(() => {
      expect(client.fetchPhotoGroup).toHaveBeenCalledWith(55);
      expect(screen.getByText(/Group Representations \(2 total\):/i)).toBeInTheDocument();
    });
  });

  it('triggers setPreferredImage when clicking Set as Primary Representation', async () => {
    vi.mocked(client.setPreferredImage).mockResolvedValue({ ...mockGroup, preferred_image_id: 102 });
    const onGroupUpdatedMock = vi.fn().mockResolvedValue(undefined);
    const onCloseMock = vi.fn();

    render(
      <PhotoGroupActionsModal
        photo={mockPhotoVariant}
        isOpen={true}
        onClose={onCloseMock}
        onGroupUpdated={onGroupUpdatedMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('btn-set-primary')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-set-primary'));
    });

    expect(client.setPreferredImage).toHaveBeenCalledWith(55, 102);
    expect(onGroupUpdatedMock).toHaveBeenCalled();
    expect(onCloseMock).toHaveBeenCalled();
  });

  it('triggers removeImageFromGroup when clicking Remove from Group', async () => {
    vi.mocked(client.removeImageFromGroup).mockResolvedValue(null);
    const onGroupUpdatedMock = vi.fn().mockResolvedValue(undefined);
    const onCloseMock = vi.fn();

    render(
      <PhotoGroupActionsModal
        photo={mockPhotoVariant}
        isOpen={true}
        onClose={onCloseMock}
        onGroupUpdated={onGroupUpdatedMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('btn-remove-from-group')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-remove-from-group'));
    });

    expect(client.removeImageFromGroup).toHaveBeenCalledWith(55, 102);
    expect(onGroupUpdatedMock).toHaveBeenCalled();
    expect(onCloseMock).toHaveBeenCalled();
  });

  it('confirms and triggers deletePhotoGroup when clicking Ungroup Entire Group', async () => {
    vi.mocked(client.deletePhotoGroup).mockResolvedValue({ status: 'ok', group_id: 55 });
    const onGroupUpdatedMock = vi.fn().mockResolvedValue(undefined);
    const onCloseMock = vi.fn();

    render(
      <PhotoGroupActionsModal
        photo={mockPhotoVariant}
        isOpen={true}
        onClose={onCloseMock}
        onGroupUpdated={onGroupUpdatedMock}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('btn-ungroup-all')).toBeInTheDocument();
    });

    // First click displays confirmation prompt
    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-ungroup-all'));
    });

    expect(screen.getByText(/Dissolve this entire group\?/i)).toBeInTheDocument();
    const confirmBtn = screen.getByTestId('btn-confirm-ungroup');
    expect(confirmBtn).toBeInTheDocument();

    // Confirm click triggers deletion
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    expect(client.deletePhotoGroup).toHaveBeenCalledWith(55);
    expect(onGroupUpdatedMock).toHaveBeenCalled();
    expect(onCloseMock).toHaveBeenCalled();
  });

  it('displays error alert banner when action fails', async () => {
    vi.mocked(client.removeImageFromGroup).mockRejectedValue(new Error('Server database lock error'));

    render(
      <PhotoGroupActionsModal
        photo={mockPhotoVariant}
        isOpen={true}
        onClose={vi.fn()}
        onGroupUpdated={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByTestId('btn-remove-from-group')).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('btn-remove-from-group'));
    });

    const errorBanner = screen.getByTestId('group-actions-error');
    expect(errorBanner).toBeInTheDocument();
    expect(errorBanner).toHaveTextContent('Server database lock error');
  });
});
