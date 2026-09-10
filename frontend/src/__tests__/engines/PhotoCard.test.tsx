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
});
