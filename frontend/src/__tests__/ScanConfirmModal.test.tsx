import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ScanConfirmModal } from '../components/ScanConfirmModal';
import { ScanPrepareResponse } from '../types';

describe('ScanConfirmModal Component', () => {
  it('renders mock scan confirmation without cost or blocking guard', () => {
    const mockProjection: ScanPrepareResponse = {
      selected_count: 5,
      usable_count: 5,
      missing_count: 0,
      provider: 'mock',
      current_month: '2026-09',
      units_used_this_month: 0,
      projected_units_total: 0,
      free_tier_allowance: 1000,
      remaining_free_units: 1000,
      estimated_incremental_cost_usd: 0.0,
      free_tier_exceeded: false,
      blocked_by_guard: false,
      disclaimer: 'Mock provider estimate',
    };

    const onConfirmMock = vi.fn();
    render(
      <ScanConfirmModal
        projection={mockProjection}
        onConfirm={onConfirmMock}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/Confirm Reverse Image Scan/i)).toBeInTheDocument();
    expect(screen.getByText('$0.00')).toBeInTheDocument();
    expect(screen.getByText(/Deterministic Mock Provider/i)).toBeInTheDocument();

    const startBtn = screen.getByRole('button', { name: /Start Scan/i });
    expect(startBtn).toBeEnabled();
    fireEvent.click(startBtn);

    expect(onConfirmMock).toHaveBeenCalledWith(false);
  });

  it('blocks start button when free tier is exceeded unless user checks force override', () => {
    const quotaExceededProjection: ScanPrepareResponse = {
      selected_count: 10,
      usable_count: 10,
      missing_count: 0,
      provider: 'google_vision',
      current_month: '2026-09',
      units_used_this_month: 1000,
      projected_units_total: 1010,
      free_tier_allowance: 1000,
      remaining_free_units: 0,
      estimated_incremental_cost_usd: 0.035,
      free_tier_exceeded: true,
      blocked_by_guard: true,
      disclaimer: 'GCP estimate',
    };

    const onConfirmMock = vi.fn();
    render(
      <ScanConfirmModal
        projection={quotaExceededProjection}
        onConfirm={onConfirmMock}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/Free Tier Allowance Exceeded/i)).toBeInTheDocument();

    // Start scan button should be disabled because guard is blocking
    const startBtn = screen.getByRole('button', { name: /Start Scan/i });
    expect(startBtn).toBeDisabled();

    // Check the force override checkbox
    const overrideCheckbox = screen.getByRole('checkbox');
    fireEvent.click(overrideCheckbox);

    // Now button should be enabled
    expect(startBtn).toBeEnabled();
    fireEvent.click(startBtn);

    expect(onConfirmMock).toHaveBeenCalledWith(true);
  });

  it('displays breakdown of available vs missing files when present', () => {
    const projectionWithMissing: ScanPrepareResponse = {
      selected_count: 6,
      usable_count: 4,
      missing_count: 2,
      provider: 'mock',
      current_month: '2026-09',
      units_used_this_month: 0,
      projected_units_total: 0,
      free_tier_allowance: 1000,
      remaining_free_units: 1000,
      estimated_incremental_cost_usd: 0.0,
      free_tier_exceeded: false,
      blocked_by_guard: false,
      disclaimer: 'Mock estimate',
    };

    render(
      <ScanConfirmModal
        projection={projectionWithMissing}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText(/4 available \(2 missing\)/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Start Scan \(4\)/i })).toBeInTheDocument();
  });

  it('disables start button when usable count is zero', () => {
    const zeroUsableProjection: ScanPrepareResponse = {
      selected_count: 3,
      usable_count: 0,
      missing_count: 3,
      provider: 'mock',
      current_month: '2026-09',
      units_used_this_month: 0,
      projected_units_total: 0,
      free_tier_allowance: 1000,
      remaining_free_units: 1000,
      estimated_incremental_cost_usd: 0.0,
      free_tier_exceeded: false,
      blocked_by_guard: false,
      disclaimer: 'Mock estimate',
    };

    render(
      <ScanConfirmModal
        projection={zeroUsableProjection}
        onConfirm={vi.fn()}
        onClose={vi.fn()}
      />
    );

    const startBtn = screen.getByRole('button', { name: /Start Scan \(0\)/i });
    expect(startBtn).toBeDisabled();
  });
});
