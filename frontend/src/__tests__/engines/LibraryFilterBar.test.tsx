import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { LibraryFilterBar } from '../../engines/library/LibraryFilterBar';
import { Library } from '../../types';

describe('LibraryFilterBar Component', () => {
  const mockLibraries: Library[] = [
    {
      id: 1,
      name: 'Landscape Archive',
      path: '/photos/landscapes',
      enabled: true,
      recursive: true,
      is_archived: false,
      subfolders_as_projects: true,
      created_at: '2026-01-01',
      last_indexed_at: '2026-01-02',
      image_count: 42,
    },
  ];

  it('renders filter controls and triggers callbacks', () => {
    const handleSelectLibrary = vi.fn();
    const handleSelectProject = vi.fn();
    const handleSearchChange = vi.fn();
    const handleStatusFilterChange = vi.fn();
    const handleDensityChange = vi.fn();
    const handleScanClicked = vi.fn();

    render(
      <LibraryFilterBar
        libraries={mockLibraries}
        totalPhotos={42}
        selectedLibraryId={undefined}
        onSelectLibrary={handleSelectLibrary}
        projects={['Campaign 2026']}
        selectedProject={undefined}
        onSelectProject={handleSelectProject}
        searchQuery=""
        onSearchChange={handleSearchChange}
        statusFilter="all"
        onStatusFilterChange={handleStatusFilterChange}
        density="standard"
        onDensityChange={handleDensityChange}
        selectedCount={5}
        preparingScan={false}
        activeProvider="mock"
        onScanClicked={handleScanClicked}
      />
    );

    expect(screen.getByText('Active Libraries (42)')).toBeInTheDocument();
    expect(screen.getByText('📁 Campaign 2026')).toBeInTheDocument();

    const searchInput = screen.getByPlaceholderText(/Filter by filename/);
    fireEvent.change(searchInput, { target: { value: 'sunset' } });
    expect(handleSearchChange).toHaveBeenCalledWith('sunset');

    const unscannedChip = screen.getByRole('button', { name: 'Unscanned' });
    fireEvent.click(unscannedChip);
    expect(handleStatusFilterChange).toHaveBeenCalledWith('unscanned');

    const scanBtn = screen.getByRole('button', { name: /Scan Selected \(5\)/ });
    expect(scanBtn).toBeEnabled();
    fireEvent.click(scanBtn);
    expect(handleScanClicked).toHaveBeenCalledTimes(1);
  });
});
