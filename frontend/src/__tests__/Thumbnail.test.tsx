import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { Thumbnail } from '../components/Thumbnail';

describe('Thumbnail Component & Remote Privacy Guard', () => {
  it('renders local thumbnail image directly without opt-in hurdle', () => {
    render(<Thumbnail src="/api/photos/1/thumbnail" alt="Local Landscape" isRemote={false} />);
    const img = screen.getByRole('img');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', '/api/photos/1/thumbnail');
  });

  it('enforces privacy opt-in for remote candidate images by default', () => {
    render(
      <Thumbnail
        src="https://suspicious-scraper.biz/images/pirated.jpg"
        alt="Suspect Image"
        isRemote={true}
      />
    );

    // Initial state: Image tag should NOT be in the DOM to prevent leaking IP/referrer
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText(/Load preview/i)).toBeInTheDocument();
  });

  it('renders image with no-referrer policy when user clicks Load Preview', () => {
    render(
      <Thumbnail
        src="https://suspicious-scraper.biz/images/pirated.jpg"
        alt="Suspect Image"
        isRemote={true}
      />
    );

    const button = screen.getByRole('button');
    fireEvent.click(button);

    // Now img tag should be present with strict no-referrer policy
    const img = screen.getByRole('img');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('referrerpolicy', 'no-referrer');
  });

  it('renders declarative fallback message when remote image fails to load', () => {
    render(
      <Thumbnail
        src="https://broken-cdn.biz/not-found.jpg"
        alt="Broken Image"
        isRemote={true}
        autoLoadRemote={true}
      />
    );

    const img = screen.getByRole('img');
    fireEvent.error(img);

    expect(screen.getByText(/Remote unavailable/i)).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
  });
});
