import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ScanProgressModal } from '../components/ScanProgressModal';
import { ScanSession } from '../types';
import * as client from '../api/client';

describe('ScanProgressModal Component', () => {
  it('renders live progress and cancel button for RUNNING session', () => {
    const runningSession: ScanSession = {
      id: 42,
      started_at: '2026-09-09T12:00:00Z',
      completed_at: null,
      provider: 'Google Cloud Vision Web Detection',
      total_images: 10,
      processed_images: 4,
      successful_images: 4,
      failed_images: 0,
      status: 'RUNNING',
      cancel_requested: false,
      notes: null,
    };

    render(
      <ScanProgressModal
        session={runningSession}
        loading={false}
        onClose={vi.fn()}
      />
    );

    expect(screen.getByText('Scanning Batch...')).toBeInTheDocument();
    expect(screen.getByText('40%')).toBeInTheDocument();
    expect(screen.getByText('4 / 10 photos')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Cancel Scan/i })).toBeInTheDocument();
  });

  it('triggers cooperative cancellation when Cancel Scan is clicked', async () => {
    const runningSession: ScanSession = {
      id: 42,
      started_at: '2026-09-09T12:00:00Z',
      completed_at: null,
      provider: 'Mock Provider',
      total_images: 10,
      processed_images: 2,
      successful_images: 2,
      failed_images: 0,
      status: 'RUNNING',
      cancel_requested: false,
      notes: null,
    };

    const cancelSpy = vi.spyOn(client, 'cancelScan').mockResolvedValueOnce({
      ...runningSession,
      cancel_requested: true,
    });

    render(
      <ScanProgressModal
        session={runningSession}
        loading={false}
        onClose={vi.fn()}
      />
    );

    const cancelBtn = screen.getByRole('button', { name: /Cancel Scan/i });
    fireEvent.click(cancelBtn);

    expect(cancelSpy).toHaveBeenCalledWith(42);
    expect(await screen.findByText('Cancelling Scan...')).toBeInTheDocument();
  });

  it('renders completed state with metrics and completion action', () => {
    const completedSession: ScanSession = {
      id: 42,
      started_at: '2026-09-09T12:00:00Z',
      completed_at: '2026-09-09T12:01:00Z',
      provider: 'Mock Provider',
      total_images: 5,
      processed_images: 5,
      successful_images: 5,
      failed_images: 0,
      status: 'COMPLETED',
      cancel_requested: false,
      notes: null,
    };

    const onCloseMock = vi.fn();
    const onViewDiscoveriesMock = vi.fn();
    render(
      <ScanProgressModal
        session={completedSession}
        loading={false}
        onClose={onCloseMock}
        onViewDiscoveries={onViewDiscoveriesMock}
      />
    );

    expect(screen.getByText('Batch Completed')).toBeInTheDocument();
    expect(screen.getByText('100%')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /View Discoveries/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /View Discoveries/i }));
    expect(onCloseMock).toHaveBeenCalled();
    expect(onViewDiscoveriesMock).toHaveBeenCalled();
  });
});
