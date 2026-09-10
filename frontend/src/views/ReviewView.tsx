import React, { useState, useEffect } from 'react';
import {
  CheckCircle,
  AlertOctagon,
  EyeOff,
  RotateCcw,
  Maximize2,
  X,
  ExternalLink,
  Filter,
  Search,
  Globe,
  Eye,
  ImageOff,
} from 'lucide-react';
import { MatchItem, ClassificationType } from '../types';
import { fetchMatches, updateMatch, createRule } from '../api/client';
import { Thumbnail } from '../components/Thumbnail';
import { DomainRuleModal } from '../components/DomainRuleModal';

interface ReviewViewProps {
  initialPhotoId?: number;
  onClearPhotoFilter: () => void;
  onClassificationChanged: () => void;
}

export const ReviewView: React.FC<ReviewViewProps> = ({
  initialPhotoId,
  onClearPhotoFilter,
  onClassificationChanged,
}) => {
  const [matches, setMatches] = useState<MatchItem[]>([]);
  const [totalMatches, setTotalMatches] = useState(0);
  const [loading, setLoading] = useState(true);

  // Filters
  const [activeClassification, setActiveClassification] = useState<ClassificationType | 'ALL'>('UNREVIEWED');
  const [isNewOnly, setIsNewOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [photoFilterId, setPhotoFilterId] = useState<number | undefined>(initialPhotoId);
  const [page, setPage] = useState(1);
  const pageSize = 30;

  // Domain Rule Modal State
  const [ruleModalDomain, setRuleModalDomain] = useState<string | null>(null);

  // Side-by-side Inspection Modal State
  const [inspectingMatch, setInspectingMatch] = useState<MatchItem | null>(null);
  const [inspectRemoteError, setInspectRemoteError] = useState(false);
  const [inspectRemoteRevealed, setInspectRemoteRevealed] = useState(false);

  useEffect(() => {
    setInspectRemoteError(false);
    setInspectRemoteRevealed(false);
  }, [inspectingMatch?.id]);

  // Notes editing state
  const [editingNotes, setEditingNotes] = useState<{ [matchId: number]: string }>({});

  const loadMatches = async () => {
    setLoading(true);
    try {
      const res = await fetchMatches({
        image_id: photoFilterId,
        classification: activeClassification === 'ALL' ? undefined : activeClassification,
        is_new_only: isNewOnly,
        search: searchQuery.trim() || undefined,
        page,
        page_size: pageSize,
      });
      setMatches(res.matches);
      setTotalMatches(res.total);
    } catch (err) {
      console.error('Failed loading matches', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMatches();
  }, [activeClassification, isNewOnly, searchQuery, photoFilterId, page]);

  // Handle classification click
  const handleClassify = async (matchId: number, classification: ClassificationType) => {
    // Optimistic UI update
    setMatches((prev) =>
      prev.map((m) =>
        m.id === matchId
          ? { ...m, classification, auto_classified_by_rule_id: null }
          : m
      )
    );
    try {
      await updateMatch(matchId, { classification });
      onClassificationChanged();
    } catch (err) {
      console.error('Failed updating classification', err);
      loadMatches();
    }
  };

  // Handle saving notes on blur
  const handleSaveNotes = async (matchId: number) => {
    const noteText = editingNotes[matchId];
    if (noteText === undefined) return;
    try {
      await updateMatch(matchId, { notes: noteText.trim() || undefined });
      setMatches((prev) =>
        prev.map((m) => (m.id === matchId ? { ...m, notes: noteText.trim() || null } : m))
      );
    } catch (err) {
      console.error('Failed saving note', err);
    }
  };

  // Handle Domain Rule creation
  const handleRuleSaved = async (domain: string, classification: ClassificationType, notes?: string) => {
    await createRule(domain, classification, notes);
    setRuleModalDomain(null);
    onClassificationChanged();
    loadMatches();
  };

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-4 space-y-4">
      {/* Photo Filter Active Banner */}
      {photoFilterId && (
        <div className="bg-accent-600/10 border border-accent-500/30 px-3.5 py-2 rounded-lg flex items-center justify-between text-xs text-accent-300">
          <div className="flex items-center gap-2">
            <Filter className="w-3.5 h-3.5 text-accent-400" />
            <span>Filtering discoveries for Photo #{photoFilterId}</span>
          </div>
          <button
            onClick={() => {
              setPhotoFilterId(undefined);
              onClearPhotoFilter();
            }}
            className="text-white hover:underline font-medium text-xs"
          >
            Clear Filter
          </button>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* Classification Tabs */}
        <div className="flex items-center gap-0.5 bg-carbon-950 p-0.5 rounded-md border border-carbon-800 overflow-x-auto">
          {(
            [
              ['UNREVIEWED', 'Needs Review'],
              ['ALL', 'All'],
              ['APPROVED', 'Approved'],
              ['UNAUTHORIZED', 'Infringing'],
              ['IRRELEVANT', 'Irrelevant'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => {
                setActiveClassification(key);
                setPage(1);
              }}
              className={`px-3 py-1 rounded text-xs font-medium whitespace-nowrap transition-all ${
                activeClassification === key
                  ? 'bg-carbon-800 text-white shadow-xs'
                  : 'text-carbon-400 hover:text-carbon-200 hover:bg-carbon-900'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Search & New Discovery Toggle */}
        <div className="flex items-center gap-3">
          <div className="relative w-48 sm:w-64">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-carbon-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
              placeholder="Search domain or page title..."
              className="w-full bg-carbon-950 border border-carbon-800 rounded-md pl-8 pr-2.5 py-1 text-xs text-white placeholder-carbon-500 focus:outline-none focus:border-accent-500"
            />
          </div>

          <label className="flex items-center gap-1.5 text-xs text-carbon-300 font-medium cursor-pointer shrink-0">
            <input
              type="checkbox"
              checked={isNewOnly}
              onChange={(e) => {
                setIsNewOnly(e.target.checked);
                setPage(1);
              }}
              className="rounded bg-carbon-950 border-carbon-800 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
            />
            <span>New Only</span>
          </label>
        </div>
      </div>

      {/* Match Cards High-Throughput Desk */}
      {loading ? (
        <div className="space-y-2.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-28 bg-carbon-900 rounded-lg animate-pulse border border-carbon-800" />
          ))}
        </div>
      ) : matches.length === 0 ? (
        <div className="bg-carbon-900/60 border border-carbon-800 rounded-lg py-16 text-center">
          <CheckCircle className="w-8 h-8 mx-auto mb-2 text-emerald-500/70" />
          <p className="text-xs font-semibold text-carbon-200">
            {activeClassification === 'UNREVIEWED' ? 'Review Queue Clear' : 'No Discoveries Found'}
          </p>
          <p className="text-[11px] text-carbon-500 mt-0.5">
            {activeClassification === 'UNREVIEWED'
              ? 'All discovered matches have been processed.'
              : 'Try selecting a different classification filter.'}
          </p>
        </div>
      ) : (
        <div className="space-y-2.5">
          {matches.map((m) => {
            const isUnreviewed = m.classification === 'UNREVIEWED';
            const isApproved = m.classification === 'APPROVED';
            const isUnauthorized = m.classification === 'UNAUTHORIZED';
            const isIrrelevant = m.classification === 'IRRELEVANT';

            return (
              <div
                key={m.id}
                className="bg-carbon-900 border border-carbon-800 hover:border-carbon-700/80 rounded-lg p-3 transition-colors flex flex-col md:flex-row gap-3.5 items-start text-xs shadow-2xs"
              >
                {/* 1. Comparison Thumbnails */}
                <div
                  onClick={() => setInspectingMatch(m)}
                  className="flex items-center gap-2 shrink-0 cursor-pointer group/inspect relative"
                  title="Click to inspect large side-by-side comparison"
                >
                  {/* Original photo */}
                  <div className="w-20 h-20 rounded-md overflow-hidden border border-carbon-800 group-hover/inspect:border-accent-500/60 relative bg-carbon-950 transition-colors">
                    <Thumbnail
                      src={m.image_thumbnail_url || `/api/photos/${m.image_id}/thumbnail`}
                      alt={m.image_filename || 'Original'}
                      className="w-full h-full"
                    />
                    <span className="absolute bottom-0.5 left-0.5 px-1 py-0.2 rounded text-[8px] bg-black/80 font-mono text-carbon-400">
                      Original
                    </span>
                    <div className="absolute inset-0 bg-carbon-950/40 opacity-0 group-hover/inspect:opacity-100 flex items-center justify-center transition-opacity">
                      <Maximize2 className="w-3.5 h-3.5 text-white drop-shadow" />
                    </div>
                  </div>

                  {/* Found remote preview */}
                  {m.candidate_image_url && (
                    <div className="w-20 h-20 rounded-md overflow-hidden border border-carbon-800 group-hover/inspect:border-accent-500/60 relative bg-carbon-950 transition-colors">
                      <Thumbnail
                        src={m.candidate_image_url}
                        alt="Candidate preview"
                        isRemote={true}
                        className="w-full h-full"
                      />
                      <span className="absolute bottom-0.5 left-0.5 px-1 py-0.2 rounded text-[8px] bg-black/80 font-mono text-carbon-400">
                        Found
                      </span>
                    </div>
                  )}
                </div>

                {/* 2. Metadata Middle Cluster */}
                <div className="flex-1 min-w-0 space-y-1 w-full">
                  <div className="flex flex-wrap items-center gap-1.5">
                    {/* Domain */}
                    <div className="flex items-center gap-1 font-semibold text-white text-xs">
                      <Globe className="w-3 h-3 text-carbon-400" />
                      <span>{m.domain}</span>
                    </div>

                    {/* Match Type */}
                    <span className="px-1.5 py-0.2 rounded text-[9px] font-mono uppercase bg-carbon-800 text-carbon-300 border border-carbon-700">
                      {m.match_type} Match
                    </span>

                    {/* Asset-only badge if no page context */}
                    {m.source_kind === 'ASSET_ONLY' && (
                      <span className="px-1.5 py-0.2 rounded text-[9px] font-mono uppercase bg-amber-500/10 text-amber-300 border border-amber-500/30">
                        Asset Only
                      </span>
                    )}

                    {/* New Badge */}
                    {m.is_new && (
                      <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-accent-500/20 text-accent-300 border border-accent-500/30">
                        NEW
                      </span>
                    )}

                    {/* Rule applied badge */}
                    {m.auto_classified_by_rule_id && (
                      <span className="px-1.5 py-0.2 rounded text-[9px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30">
                        Rule Applied
                      </span>
                    )}
                  </div>

                  {/* Page Title */}
                  <h4 className="text-xs font-medium text-carbon-100 line-clamp-1" title={m.page_title || m.page_url || m.candidate_image_url || 'Discovered Asset'}>
                    {m.page_title || (m.source_kind === 'ASSET_ONLY' ? 'Standalone Image Asset' : 'Untitled Web Page')}
                  </h4>

                  {/* Page URL & Open Tab */}
                  <div className="flex items-center gap-2 text-[11px] font-mono text-carbon-400 truncate">
                    {m.page_url ? (
                      <a
                        href={m.page_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent-400 hover:text-accent-300 hover:underline truncate inline-flex items-center gap-1"
                      >
                        <span>{m.page_url}</span>
                        <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                      </a>
                    ) : m.candidate_image_url ? (
                      <a
                        href={m.candidate_image_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-accent-400 hover:text-accent-300 hover:underline truncate inline-flex items-center gap-1"
                      >
                        <span>Direct Image Asset: {m.candidate_image_url}</span>
                        <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                      </a>
                    ) : (
                      <span className="text-carbon-500 italic">No web URL provided</span>
                    )}
                  </div>

                  {/* Timestamps & Photo Ref */}
                  <div className="flex items-center gap-3 text-[10px] font-mono text-carbon-400 tabular-nums pt-0.5">
                    <span>First: {new Date(m.first_seen_at).toLocaleDateString()}</span>
                    <span>Last: {new Date(m.last_seen_at).toLocaleDateString()}</span>
                    {m.image_filename && <span className="truncate">Photo: {m.image_filename}</span>}
                  </div>

                  {/* Inline Note */}
                  <div className="pt-1">
                    <input
                      type="text"
                      placeholder="Add an inline note..."
                      value={editingNotes[m.id] !== undefined ? editingNotes[m.id] : m.notes || ''}
                      onChange={(e) => setEditingNotes({ ...editingNotes, [m.id]: e.target.value })}
                      onBlur={() => handleSaveNotes(m.id)}
                      className="w-full bg-carbon-950 border border-carbon-800 rounded px-2 py-1 text-xs text-carbon-200 placeholder-carbon-500 focus:outline-none focus:border-accent-500"
                    />
                  </div>
                </div>

                {/* 3. Classification Keypad / Right Column */}
                <div className="flex flex-col gap-1.5 shrink-0 w-full md:w-48 pt-1 md:pt-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] font-mono uppercase tracking-wider text-carbon-400">
                      Decision
                    </span>
                    <button
                      onClick={() => setInspectingMatch(m)}
                      className="text-[10px] font-mono text-accent-400 hover:text-accent-300 flex items-center gap-0.5"
                    >
                      <Maximize2 className="w-2.5 h-2.5" />
                      <span>Inspect</span>
                    </button>
                  </div>

                  {/* Primary Decisions (Prominent) */}
                  <div className="grid grid-cols-3 gap-1">
                    <button
                      onClick={() => handleClassify(m.id, 'APPROVED')}
                      className={`px-1.5 py-1.5 rounded text-xs font-medium flex flex-col items-center justify-center gap-0.5 transition-all ${
                        isApproved
                          ? 'bg-emerald-500 text-carbon-950 font-bold shadow-xs'
                          : 'bg-carbon-950 border border-carbon-800 text-carbon-300 hover:text-white hover:border-emerald-500/40'
                      }`}
                      title="Approve as legitimate use"
                    >
                      <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                      <span className="text-[11px]">Approved</span>
                    </button>

                    <button
                      onClick={() => handleClassify(m.id, 'UNAUTHORIZED')}
                      className={`px-1.5 py-1.5 rounded text-xs font-medium flex flex-col items-center justify-center gap-0.5 transition-all ${
                        isUnauthorized
                          ? 'bg-rose-500 text-white font-bold shadow-xs'
                          : 'bg-carbon-950 border border-carbon-800 text-carbon-300 hover:text-white hover:border-rose-500/40'
                      }`}
                      title="Flag as unauthorized or infringing reuse"
                    >
                      <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
                      <span className="text-[11px]">Infringing</span>
                    </button>

                    <button
                      onClick={() => handleClassify(m.id, 'IRRELEVANT')}
                      className={`px-1.5 py-1.5 rounded text-xs font-medium flex flex-col items-center justify-center gap-0.5 transition-all ${
                        isIrrelevant
                          ? 'bg-carbon-700 text-white font-bold shadow-xs'
                          : 'bg-carbon-950 border border-carbon-800 text-carbon-300 hover:text-white hover:border-carbon-600'
                      }`}
                      title="Mark as irrelevant discovery"
                    >
                      <EyeOff className="w-3.5 h-3.5 text-carbon-400" />
                      <span className="text-[11px]">Irrelevant</span>
                    </button>
                  </div>

                  {/* Secondary Actions (Reset & Domain Rule) */}
                  <div className="flex items-center justify-between gap-1 pt-0.5 text-[10px] text-carbon-400">
                    <button
                      onClick={() => handleClassify(m.id, 'UNREVIEWED')}
                      className={`px-1.5 py-0.5 rounded flex items-center gap-1 transition-colors ${
                        isUnreviewed
                          ? 'text-amber-400 font-mono font-medium bg-amber-500/10'
                          : 'text-carbon-500 hover:text-carbon-300 hover:bg-carbon-850'
                      }`}
                      title="Reset classification back to unreviewed"
                    >
                      <RotateCcw className="w-2.5 h-2.5" />
                      <span>Reset</span>
                    </button>

                    <button
                      onClick={() => setRuleModalDomain(m.domain)}
                      className="hover:text-carbon-200 flex items-center gap-1 py-0.5 px-1.5 rounded hover:bg-carbon-850"
                      title={`Create auto-rule for domain ${m.domain}`}
                    >
                      <Filter className="w-2.5 h-2.5" />
                      <span>Rule</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {totalMatches > pageSize && (
        <div className="flex items-center justify-between pt-3 text-xs text-carbon-400 border-t border-carbon-800">
          <span className="tabular-nums">
            Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalMatches)} of {totalMatches}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-2.5 py-1 rounded bg-carbon-900 border border-carbon-800 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-carbon-800"
            >
              Prev
            </button>
            <span className="px-2 font-mono text-xs tabular-nums">Page {page}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * pageSize >= totalMatches}
              className="px-2.5 py-1 rounded bg-carbon-900 border border-carbon-800 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-carbon-800"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Domain Rule Modal */}
      {ruleModalDomain && (
        <DomainRuleModal
          initialDomain={ruleModalDomain}
          onSave={handleRuleSaved}
          onClose={() => setRuleModalDomain(null)}
        />
      )}

      {/* Side-by-side Inspection Modal */}
      {inspectingMatch && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-carbon-900 border border-carbon-700 rounded-xl max-w-5xl w-full max-h-[92vh] flex flex-col overflow-hidden shadow-2xl animate-in fade-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="px-5 py-3 border-b border-carbon-800 flex items-center justify-between bg-carbon-950/80">
              <div className="flex items-center gap-2 min-w-0">
                <Globe className="w-4 h-4 text-accent-400 shrink-0" />
                <span className="font-semibold text-white text-sm truncate">{inspectingMatch.domain}</span>
                <span className="px-1.5 py-0.2 rounded text-[10px] font-mono uppercase bg-carbon-800 text-carbon-300 border border-carbon-700">
                  {inspectingMatch.match_type} Match
                </span>
                {inspectingMatch.is_new && (
                  <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-accent-500/20 text-accent-300 border border-accent-500/30">
                    NEW
                  </span>
                )}
              </div>
              <button
                onClick={() => setInspectingMatch(null)}
                className="p-1 rounded-md text-carbon-400 hover:text-white hover:bg-carbon-800 transition-colors"
                title="Close inspection"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal Body: Large Side-by-Side Images */}
            <div className="p-5 overflow-y-auto grid grid-cols-1 md:grid-cols-2 gap-4 flex-1">
              {/* Left: Original Photograph */}
              <div className="flex flex-col gap-2 bg-carbon-950 p-3 rounded-lg border border-carbon-800">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-carbon-400 font-semibold tracking-wide uppercase text-[10px]">
                    Original Photograph
                  </span>
                  <span className="font-mono text-carbon-500 text-[10px] truncate max-w-[200px]">
                    {inspectingMatch.image_filename}
                  </span>
                </div>
                <div className="flex-1 min-h-[280px] max-h-[50vh] flex items-center justify-center overflow-hidden rounded bg-carbon-900/60 border border-carbon-800/80">
                  <img
                    src={`/api/photos/${inspectingMatch.image_id}/file`}
                    alt={inspectingMatch.image_filename || 'Original photo'}
                    className="max-h-[48vh] max-w-full object-contain rounded"
                  />
                </div>
              </div>

              {/* Right: Found Web Match */}
              <div className="flex flex-col gap-2 bg-carbon-950 p-3 rounded-lg border border-carbon-800">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-accent-400 font-semibold tracking-wide uppercase text-[10px]">
                    {inspectingMatch.source_kind === 'ASSET_ONLY' ? 'Discovered Asset' : 'Found Web Match'}
                  </span>
                  {inspectingMatch.page_url ? (
                    <a
                      href={inspectingMatch.page_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent-400 hover:text-accent-300 hover:underline flex items-center gap-1 text-[11px] font-mono"
                    >
                      <span>Open Web Page</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : inspectingMatch.candidate_image_url ? (
                    <a
                      href={inspectingMatch.candidate_image_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent-400 hover:text-accent-300 hover:underline flex items-center gap-1 text-[11px] font-mono"
                    >
                      <span>Open Image Asset</span>
                      <ExternalLink className="w-3 h-3" />
                    </a>
                  ) : null}
                </div>
                <div className="flex-1 min-h-[280px] max-h-[50vh] flex items-center justify-center overflow-hidden rounded bg-carbon-900/60 border border-carbon-800/80 p-2">
                  {!inspectingMatch.candidate_image_url ? (
                    <div className="text-carbon-500 text-xs font-mono p-4 text-center">
                      No candidate image URL provided by provider. Page match only.
                    </div>
                  ) : !inspectRemoteRevealed ? (
                    <div className="flex flex-col items-center justify-center p-6 text-center space-y-3">
                      <div className="w-10 h-10 rounded-full bg-carbon-900 border border-carbon-800 flex items-center justify-center text-carbon-400">
                        <Eye className="w-5 h-5 text-accent-400" />
                      </div>
                      <div>
                        <p className="text-xs font-medium text-carbon-200">Remote Match Image</p>
                        <p className="text-[11px] text-carbon-400 max-w-xs mt-0.5">
                          Hosted on <span className="font-mono text-carbon-300">{inspectingMatch.domain}</span>. Privacy protection active (no referrer sent).
                        </p>
                      </div>
                      <button
                        onClick={() => setInspectRemoteRevealed(true)}
                        className="px-3 py-1.5 rounded bg-accent-600 hover:bg-accent-500 text-white text-xs font-semibold transition-all active:scale-98"
                      >
                        Load Discovered Image
                      </button>
                    </div>
                  ) : inspectRemoteError ? (
                    <div className="text-carbon-400 text-xs font-mono p-6 text-center space-y-2">
                      <ImageOff className="w-6 h-6 mx-auto text-carbon-600" />
                      <p className="text-carbon-300">Remote candidate image could not be loaded directly.</p>
                      <p className="text-[10px] text-carbon-500">The remote host may block direct hotlinking.</p>
                      {(inspectingMatch.page_url || inspectingMatch.candidate_image_url) && (
                        <a
                          href={inspectingMatch.page_url || inspectingMatch.candidate_image_url || '#'}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-accent-400 hover:underline text-[11px] pt-1"
                        >
                          <span>{inspectingMatch.page_url ? 'Open Web Page' : 'Open Image Asset'}</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      )}
                    </div>
                  ) : (
                    <img
                      src={inspectingMatch.candidate_image_url}
                      alt="Discovered match preview"
                      referrerPolicy="no-referrer"
                      className="max-h-[48vh] max-w-full object-contain rounded"
                      onError={() => setInspectRemoteError(true)}
                    />
                  )}
                </div>
                <div className="text-[11px] font-mono text-carbon-400 truncate pt-1">
                  <p className="text-carbon-200 line-clamp-1">{inspectingMatch.page_title || 'Untitled Page'}</p>
                  <p className="text-carbon-500 truncate text-[10px]">{inspectingMatch.page_url || inspectingMatch.candidate_image_url}</p>
                </div>
              </div>
            </div>

            {/* Modal Footer: Decisions & Close */}
            <div className="px-5 py-3 border-t border-carbon-800 bg-carbon-950/80 flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-carbon-400 font-mono uppercase text-[10px]">Set Decision:</span>
                <button
                  onClick={() => {
                    handleClassify(inspectingMatch.id, 'APPROVED');
                    setInspectingMatch((m) => (m ? { ...m, classification: 'APPROVED' } : null));
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium flex items-center gap-1.5 transition-colors ${
                    inspectingMatch.classification === 'APPROVED'
                      ? 'bg-emerald-500 text-carbon-950 font-bold'
                      : 'bg-carbon-900 border border-carbon-700 text-carbon-200 hover:border-emerald-500/50'
                  }`}
                >
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Approved</span>
                </button>
                <button
                  onClick={() => {
                    handleClassify(inspectingMatch.id, 'UNAUTHORIZED');
                    setInspectingMatch((m) => (m ? { ...m, classification: 'UNAUTHORIZED' } : null));
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium flex items-center gap-1.5 transition-colors ${
                    inspectingMatch.classification === 'UNAUTHORIZED'
                      ? 'bg-rose-500 text-white font-bold'
                      : 'bg-carbon-900 border border-carbon-700 text-carbon-200 hover:border-rose-500/50'
                  }`}
                >
                  <AlertOctagon className="w-3.5 h-3.5 text-rose-400" />
                  <span>Infringing</span>
                </button>
                <button
                  onClick={() => {
                    handleClassify(inspectingMatch.id, 'IRRELEVANT');
                    setInspectingMatch((m) => (m ? { ...m, classification: 'IRRELEVANT' } : null));
                  }}
                  className={`px-3 py-1 rounded text-xs font-medium flex items-center gap-1.5 transition-colors ${
                    inspectingMatch.classification === 'IRRELEVANT'
                      ? 'bg-carbon-700 text-white font-bold'
                      : 'bg-carbon-900 border border-carbon-700 text-carbon-200 hover:border-carbon-600'
                  }`}
                >
                  <EyeOff className="w-3.5 h-3.5 text-carbon-400" />
                  <span>Irrelevant</span>
                </button>
                <button
                  onClick={() => {
                    handleClassify(inspectingMatch.id, 'UNREVIEWED');
                    setInspectingMatch((m) => (m ? { ...m, classification: 'UNREVIEWED' } : null));
                  }}
                  className={`px-2 py-1 rounded text-xs transition-colors text-carbon-400 hover:text-carbon-200 ${
                    inspectingMatch.classification === 'UNREVIEWED' ? 'font-mono text-amber-400' : ''
                  }`}
                >
                  <RotateCcw className="w-3 h-3 inline mr-1" />
                  <span>Reset</span>
                </button>
              </div>

              <button
                onClick={() => setInspectingMatch(null)}
                className="px-3.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-white text-xs font-medium transition-colors"
              >
                Back to Review Queue
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
