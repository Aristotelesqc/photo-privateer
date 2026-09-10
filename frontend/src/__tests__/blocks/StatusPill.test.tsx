import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { StatusPill } from '../../components/blocks/StatusPill';

describe('StatusPill Component', () => {
  it('renders "Unscanned" by default when unscanned', () => {
    render(<StatusPill scanCount={0} matchCount={0} />);
    expect(screen.getByText('Unscanned')).toBeInTheDocument();
  });

  it('renders "Clean" when scanned with 0 matches', () => {
    render(<StatusPill scanCount={1} matchCount={0} />);
    expect(screen.getByText('Clean')).toBeInTheDocument();
  });

  it('renders matches count and pulse indicator for unreviewed discoveries', () => {
    const handleClick = vi.fn();
    const { container } = render(
      <StatusPill
        scanCount={2}
        matchCount={3}
        unreviewedCount={1}
        onMatchClick={handleClick}
      />
    );
    expect(screen.getByText('3 matches')).toBeInTheDocument();
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();

    const button = screen.getByRole('button');
    fireEvent.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
