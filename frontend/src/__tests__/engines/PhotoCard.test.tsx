import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { PhotoCard } from '../../engines/library/PhotoCard';
import { ImageItem } from '../../types';

describe('PhotoCard Component', () => {
  const mockPhoto: ImageItem = {
    id: 101,
    library_id: 1,
    sha256: 'abcdef1234567890',
    file_path: '/photos/sunset.jpg',
    filename: 'sunset.jpg',
    file_size: 2 * 1024 * 1024,
    file_modified_at: 1700000000,
    width: 1920,
    height: 1080,
    format: 'JPEG',
    indexed_at: '2026-01-01',
    last_seen_on_disk: '2026-01-01',
    is_present_on_disk: true,
    library_enabled: true,
    library_archived: false,
    source_available: true,
    scan_eligible: true,
    project: 'Holiday 2026',
    last_scanned_at: null,
    scan_count: 0,
    match_count: 0,
    unreviewed_count: 0,
    thumbnail_url: '/api/photos/101/thumbnail',
  };

  it('renders photo details, project badge, and handles selection toggle', () => {
    const handleToggleSelect = vi.fn();
    const handleNavigateToReview = vi.fn();

    render(
      <PhotoCard
        photo={mockPhoto}
        isSelected={false}
        onToggleSelect={handleToggleSelect}
        onNavigateToReview={handleNavigateToReview}
      />
    );

    expect(screen.getByText('sunset.jpg')).toBeInTheDocument();
    expect(screen.getByText('1920×1080')).toBeInTheDocument();
    expect(screen.getByText('2.0MB')).toBeInTheDocument();
    expect(screen.getByText('JPEG')).toBeInTheDocument();
    expect(screen.getByText(/Holiday 2026/)).toBeInTheDocument();

    const card = screen.getByText('sunset.jpg').closest('.group');
    expect(card).toBeInTheDocument();
    fireEvent.click(card!);
    expect(handleToggleSelect).toHaveBeenCalledWith(101);

    fireEvent.keyDown(card!, { key: 'Enter' });
    expect(handleToggleSelect).toHaveBeenCalledTimes(2);
  });

  it('displays Missing warning when file is missing from disk', () => {
    const missingPhoto = { ...mockPhoto, is_present_on_disk: false };
    render(
      <PhotoCard
        photo={missingPhoto}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onNavigateToReview={vi.fn()}
      />
    );

    expect(screen.getByText('Missing')).toBeInTheDocument();
  });

  it('shows the group discoveries on a grouped variant and opens its review', () => {
    const handleNavigateToReview = vi.fn();
    const variant: ImageItem = {
      ...mockPhoto,
      photo_group_id: 7,
      is_primary_representation: 0,
      scan_count: 1,
      match_count: 0,
      unreviewed_count: 0,
      group_match_count: 4,
      group_unreviewed_count: 2,
    };
    render(
      <PhotoCard
        photo={variant}
        isSelected={false}
        onToggleSelect={vi.fn()}
        onNavigateToReview={handleNavigateToReview}
      />
    );
    const pill = screen.getByText('4 matches');
    fireEvent.click(pill);
    expect(handleNavigateToReview).toHaveBeenCalledWith(101);
  });

  it('shows a never-scanned variant of an already-searched group as covered', () => {
    const variant: ImageItem = {
      ...mockPhoto,
      photo_group_id: 7,
      is_primary_representation: 0,
      scan_count: 0,
      group_match_count: 0,
      group_unreviewed_count: 0,
      group_scan_count: 1,
    };
    render(
      <PhotoCard photo={variant} isSelected={false} onToggleSelect={vi.fn()} onNavigateToReview={vi.fn()} />
    );
    expect(screen.getByText('Clean')).toBeInTheDocument();
    expect(screen.queryByText('Unscanned')).not.toBeInTheDocument();
  });

  it.each(['archived', 'disabled', 'missing'])('prevents %s selection and preserves historical review', (state) => {
    const toggle = vi.fn();
    const review = vi.fn();
    const photo = { ...mockPhoto, scan_eligible: false, library_archived: state === 'archived', library_enabled: state !== 'disabled', source_available: state !== 'missing', match_count: 2 };
    render(<PhotoCard photo={photo} isSelected={false} onToggleSelect={toggle} onNavigateToReview={review} />);
    expect(screen.getByRole('button', { name: 'Select sunset.jpg' })).toBeDisabled();
    fireEvent.click(screen.getByTestId('photo-card-sunset.jpg'));
    expect(toggle).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('2 matches'));
    expect(review).toHaveBeenCalledWith(101);
  });

  it('allows a missing active selection served by an eligible group sibling', () => {
    const toggle = vi.fn();
    render(<PhotoCard photo={{ ...mockPhoto, source_available: false, scan_eligible: true }} isSelected={false} onToggleSelect={toggle} onNavigateToReview={vi.fn()} />);
    expect(screen.getByText('Search via group')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Select sunset.jpg' }));
    expect(toggle).toHaveBeenCalledTimes(1);
  });
});

