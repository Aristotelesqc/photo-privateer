import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { ProjectBadge } from '../../components/blocks/ProjectBadge';

describe('ProjectBadge Component', () => {
  it('renders project badge with folder emoji and title', () => {
    render(<ProjectBadge project="Landscape 2026" />);
    const badge = screen.getByText(/Landscape 2026/);
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute('title', 'Project: Landscape 2026');
  });

  it('applies truncate class and custom max-width when truncate is true', () => {
    render(<ProjectBadge project="Very Long Campaign Name That Needs Truncating" truncate maxWidth="max-w-[100px]" />);
    const badge = screen.getByText(/Very Long Campaign/);
    expect(badge.className).toContain('truncate');
    expect(badge.className).toContain('max-w-[100px]');
  });

  it('triggers onClick handler when clicked', () => {
    const handleClick = vi.fn();
    render(<ProjectBadge project="Clickable Project" onClick={handleClick} />);
    const badge = screen.getByText(/Clickable Project/);
    fireEvent.click(badge);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
