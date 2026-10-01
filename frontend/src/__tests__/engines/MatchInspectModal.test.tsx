import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import React from 'react';
import { MatchInspectModal } from '../../engines/review/MatchInspectModal';
import { MatchItem } from '../../types';

const baseMatch: MatchItem = {
  id: 501,
  image_id: 101,
  scan_session_id: 1,
  page_url: 'https://infringing-site.example/page.html',
  page_title: 'Uncredited Portfolio Post',
  page_score: 0.95,
  domain: 'infringing-site.example',
  candidate_image_url: 'https://infringing-site.example/stolen.jpg',
  match_type: 'FULL',
  source_kind: 'PAGE',
  provider: 'mock',
  first_seen_at: '2026-02-01T12:00:00Z',
  last_seen_at: '2026-02-01T12:00:00Z',
  is_new: true,
  acknowledged_at: null,
  classification: 'UNREVIEWED',
  classified_at: null,
  auto_classified_by_rule_id: null,
  notes: null,
  image_filename: 'master.jpg',
  image_thumbnail_url: '/api/photos/101/thumbnail',
  image_project: null,
};

const originalSrcs = (container: HTMLElement) =>
  Array.from(container.querySelectorAll('img')).map((img) => img.getAttribute('src'));

describe('MatchInspectModal original preview', () => {
  it('previews the available group member when the owning photo is missing', () => {
    const { container } = render(
      <MatchInspectModal match={{ ...baseMatch, display_image_id: 102 }} onClose={vi.fn()} onClassify={vi.fn()} />
    );
    expect(originalSrcs(container)).toContain('/api/photos/102/file');
    expect(originalSrcs(container)).not.toContain('/api/photos/101/file');
  });

  it('falls back to the owning photo when no display photo is provided', () => {
    const { container } = render(<MatchInspectModal match={baseMatch} onClose={vi.fn()} onClassify={vi.fn()} />);
    expect(originalSrcs(container)).toContain('/api/photos/101/file');
  });
});
