import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import React from 'react';
import { CandidateBanner } from '../../engines/library/CandidateBanner';

describe('CandidateBanner', () => {
  it('shows the exact total when the candidate list is exhaustive', () => {
    render(<CandidateBanner count={66} onReview={vi.fn()} />);
    expect(screen.getByTestId('btn-review-candidates')).toHaveTextContent('Review Candidates (66)');
  });

  it('marks the total as a lower bound when the search was capped', () => {
    render(<CandidateBanner count={50} truncated onReview={vi.fn()} />);
    expect(screen.getByTestId('btn-review-candidates')).toHaveTextContent('Review Candidates (50+)');
  });
});
