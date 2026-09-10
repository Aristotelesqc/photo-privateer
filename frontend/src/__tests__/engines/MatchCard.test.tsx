import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import { MatchCard } from '../../engines/review/MatchCard';
import { MatchItem } from '../../types';

describe('MatchCard Component', () => {
  const mockMatch: MatchItem = {
    id: 501,
    image_id: 101,
    scan_session_id: 1,
    page_url: 'https://infringing-site.example/page.html',
    page_title: 'Uncredited Portfolio Post',
    page_score: 0.95,
    domain: 'infringing-site.example',
    candidate_image_url: 'https://infringing-site.example/stolen.jpg',
    match_type: 'FULL',
    source_kind: 'FULL',
    provider: 'mock',
    first_seen_at: '2026-02-01T12:00:00Z',
    last_seen_at: '2026-02-01T12:00:00Z',
    is_new: true,
    acknowledged_at: null,
    classification: 'UNREVIEWED',
    classified_at: null,
    auto_classified_by_rule_id: null,
    notes: 'Needs investigation',
    image_filename: 'sunset.jpg',
    image_thumbnail_url: '/api/photos/101/thumbnail',
    image_project: 'Holiday 2026',
  };

  it('renders match metadata and triggers classification actions', () => {
    const handleClassify = vi.fn();
    const handleInspect = vi.fn();
    const handleRequestRuleModal = vi.fn();
    const handleSaveNotes = vi.fn();
    const handleNoteChange = vi.fn();

    render(
      <MatchCard
        match={mockMatch}
        editingNote={undefined}
        onNoteChange={handleNoteChange}
        onSaveNotes={handleSaveNotes}
        onClassify={handleClassify}
        onInspect={handleInspect}
        onRequestRuleModal={handleRequestRuleModal}
      />
    );

    expect(screen.getByText('infringing-site.example')).toBeInTheDocument();
    expect(screen.getByText('FULL Match')).toBeInTheDocument();
    expect(screen.getByText('NEW')).toBeInTheDocument();
    expect(screen.getByText('Uncredited Portfolio Post')).toBeInTheDocument();
    expect(screen.getByText(/Holiday 2026/)).toBeInTheDocument();

    const approveBtn = screen.getByRole('button', { name: /Approved/ });
    fireEvent.click(approveBtn);
    expect(handleClassify).toHaveBeenCalledWith('APPROVED');

    const infringingBtn = screen.getByRole('button', { name: /Infringing/ });
    fireEvent.click(infringingBtn);
    expect(handleClassify).toHaveBeenCalledWith('UNAUTHORIZED');

    const ruleBtn = screen.getByRole('button', { name: /Rule/ });
    fireEvent.click(ruleBtn);
    expect(handleRequestRuleModal).toHaveBeenCalledWith('infringing-site.example');
  });
});
