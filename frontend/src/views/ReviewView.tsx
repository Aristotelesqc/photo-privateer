import React, { useState, useEffect } from 'react';
import {
  CheckCircle,
  Filter,
} from 'lucide-react';
import { MatchItem, ClassificationType } from '../types';
import { fetchMatches, updateMatch, createRule, fetchProjects } from '../api/client';
import { DomainRuleModal } from '../components/DomainRuleModal';
import { ReviewFilterBar } from '../engines/review/ReviewFilterBar';
import { MatchCard } from '../engines/review/MatchCard';
import { MatchInspectModal } from '../engines/review/MatchInspectModal';

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
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [photoFilterId, setPhotoFilterId] = useState<number | undefined>(initialPhotoId);
  const [projects, setProjects] = useState<string[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const pageSize = 30;

  // Domain Rule Modal State
  const [ruleModalDomain, setRuleModalDomain] = useState<string | null>(null);

  // Side-by-side Inspection Modal State
  const [inspectingMatch, setInspectingMatch] = useState<MatchItem | null>(null);

  // Notes editing state
  const [editingNotes, setEditingNotes] = useState<{ [matchId: number]: string }>({});
  const [noteSaveStates, setNoteSaveStates] = useState<{ [matchId: number]: 'saving' | 'saved' | 'error' }>({});

  useEffect(() => {
    if (!searchQuery.trim()) {
      setDebouncedSearch('');
      return;
    }
    const timer = setTimeout(() => {
      setDebouncedSearch(searchQuery.trim());
    }, 250);
    return () => clearTimeout(timer);
  }, [searchQuery]);

  useEffect(() => {
    fetchProjects().then(setProjects).catch(() => {});
  }, []);

  const loadMatches = async () => {
    setLoading(true);
    try {
      const res = await fetchMatches({
        image_id: photoFilterId,
        project: selectedProject,
        classification: activeClassification === 'ALL' ? undefined : activeClassification,
        is_new_only: isNewOnly,
        search: debouncedSearch || undefined,
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
  }, [activeClassification, isNewOnly, debouncedSearch, photoFilterId, selectedProject, page]);

  // Handle classification click
  const handleClassify = async (matchId: number, classification: ClassificationType) => {
    // If we are currently reviewing under the UNREVIEWED filter and classification is non-UNREVIEWED,
    // immediately remove it from the visible list and decrement total count for responsive review queue.
    if (activeClassification === 'UNREVIEWED' && classification !== 'UNREVIEWED') {
      setMatches((prev) => prev.filter((m) => m.id !== matchId));
      setTotalMatches((prev) => Math.max(0, prev - 1));
    } else {
      // Optimistic UI update
      setMatches((prev) =>
        prev.map((m) =>
          m.id === matchId
            ? { ...m, classification, auto_classified_by_rule_id: null }
            : m
        )
      );
    }
    setInspectingMatch((m) =>
      m && m.id === matchId ? { ...m, classification, auto_classified_by_rule_id: null } : m
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
    const cleanNote = noteText.trim();
    const existing = matches.find((m) => m.id === matchId);
    if (existing && (existing.notes || '') === cleanNote) return;

    setNoteSaveStates((prev) => ({ ...prev, [matchId]: 'saving' }));
    try {
      await updateMatch(matchId, { notes: cleanNote === '' ? null : cleanNote });
      setMatches((prev) =>
        prev.map((m) => (m.id === matchId ? { ...m, notes: cleanNote === '' ? null : cleanNote } : m))
      );
      setNoteSaveStates((prev) => ({ ...prev, [matchId]: 'saved' }));
      setTimeout(() => {
        setNoteSaveStates((prev) => {
          const next = { ...prev };
          if (next[matchId] === 'saved') delete next[matchId];
          return next;
        });
      }, 2000);
    } catch (err) {
      console.error('Failed saving note', err);
      setNoteSaveStates((prev) => ({ ...prev, [matchId]: 'error' }));
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
      <ReviewFilterBar
        activeClassification={activeClassification}
        onClassificationChange={(key) => {
          setActiveClassification(key);
          setPage(1);
        }}
        projects={projects}
        selectedProject={selectedProject}
        onProjectChange={(proj) => {
          setSelectedProject(proj);
          setPage(1);
        }}
        searchQuery={searchQuery}
        onSearchChange={(query) => {
          setSearchQuery(query);
          setPage(1);
        }}
        isNewOnly={isNewOnly}
        onNewOnlyChange={(newOnly) => {
          setIsNewOnly(newOnly);
          setPage(1);
        }}
      />

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
          {matches.map((m) => (
            <MatchCard
              key={m.id}
              match={m}
              editingNote={editingNotes[m.id]}
              noteSaveState={noteSaveStates[m.id]}
              onNoteChange={(text) => setEditingNotes((prev) => ({ ...prev, [m.id]: text }))}
              onSaveNotes={() => handleSaveNotes(m.id)}
              onClassify={(c) => handleClassify(m.id, c)}
              onInspect={() => setInspectingMatch(m)}
              onRequestRuleModal={(domain) => setRuleModalDomain(domain)}
            />
          ))}
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
      {(() => {
        const inspectIdx = inspectingMatch ? matches.findIndex((m) => m.id === inspectingMatch.id) : -1;
        return (
          <MatchInspectModal
            match={inspectingMatch}
            onClose={() => setInspectingMatch(null)}
            onClassify={handleClassify}
            hasPrev={inspectIdx > 0}
            hasNext={inspectIdx >= 0 && inspectIdx < matches.length - 1}
            onPrev={inspectIdx > 0 ? () => setInspectingMatch(matches[inspectIdx - 1]) : undefined}
            onNext={
              inspectIdx >= 0 && inspectIdx < matches.length - 1
                ? () => setInspectingMatch(matches[inspectIdx + 1])
                : undefined
            }
          />
        );
      })()}
    </div>
  );
};
