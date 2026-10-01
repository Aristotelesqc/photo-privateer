import React, { useState, useEffect } from 'react';
import { Layers, CheckCircle2, XCircle, ArrowLeft, ArrowRight, X, Sparkles, AlertCircle } from 'lucide-react';
import { GroupCandidatePair } from '../types';
import { dismissGroupCandidate } from '../api/client';
import { CandidateCard } from '../engines/library/CandidateCard';
import { CandidateSide, defaultPreferredSide, groupCandidatePair } from '../engines/library/candidateGrouping';

interface CandidateGroupModalProps {
  candidates: GroupCandidatePair[];
  /** Total number of candidate pairs when `candidates` is only the first page */
  totalCount?: number;
  onGroup?: (imageAId: number, imageBId: number, preferredId: number) => Promise<void>;
  onDismiss?: (imageAId: number, imageBId: number) => Promise<void>;
  onClose: () => void;
}

export const CandidateGroupModal: React.FC<CandidateGroupModalProps> = ({
  candidates,
  totalCount,
  onGroup,
  onDismiss,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedPreferred, setSelectedPreferred] = useState<CandidateSide>('A');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const currentPair = candidates[currentIndex] || candidates[0];

  // Reset preferred selection (keeping an existing group primary selected) and clear error
  // when navigating or advancing pairs
  useEffect(() => {
    setSelectedPreferred(currentPair ? defaultPreferredSide(currentPair) : 'A');
    setError(null);
  }, [currentIndex, currentPair?.image_a?.id, currentPair?.image_b?.id]);

  if (!candidates || candidates.length === 0) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
        <div className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-md shadow-2xl p-6 text-center text-carbon-100">
          <CheckCircle2 className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
          <h3 className="font-semibold text-white text-sm mb-1">All Caught Up</h3>
          <p className="text-xs text-carbon-400 mb-4">No unreviewed candidate photo representations found.</p>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-carbon-800 hover:bg-carbon-700 text-white rounded-lg text-xs font-medium transition-colors cursor-pointer"
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  const { image_a, image_b, hamming_distance, is_exact_duplicate } = currentPair;
  const total = candidates.length;
  const similarityPct = is_exact_duplicate ? 100 : Math.round(((64 - hamming_distance) / 64) * 100);
  const isAlreadyGrouped = Boolean(image_a.photo_group_id || image_b.photo_group_id);

  const handleGroup = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      const preferredId = selectedPreferred === 'A' ? image_a.id : image_b.id;
      if (onGroup) {
        await onGroup(image_a.id, image_b.id, preferredId);
      } else {
        await groupCandidatePair(currentPair, preferredId);
      }
      if (candidates.length <= 1) {
        onClose();
      } else if (currentIndex >= total - 1) {
        setCurrentIndex(Math.max(0, total - 2));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDismiss = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      if (onDismiss) {
        await onDismiss(image_a.id, image_b.id);
      } else {
        await dismissGroupCandidate(image_a.id, image_b.id);
      }
      if (candidates.length <= 1) {
        onClose();
      } else if (currentIndex >= total - 1) {
        setCurrentIndex(Math.max(0, total - 2));
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
      <div className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-2xl shadow-2xl overflow-hidden text-carbon-100 text-xs animate-scale-up flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="px-4 py-3 border-b border-carbon-800 flex items-center justify-between bg-carbon-950/60">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-accent-600/10 text-accent-400">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-xs">Perceptual Source Representations</h3>
              <p className="text-[10px] text-carbon-400">
                Candidate {currentIndex + 1} of {total}
                {totalCount !== undefined && totalCount > total && (
                  <span data-testid="candidate-total-note"> (showing the {total} closest of {totalCount})</span>
                )}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
              disabled={currentIndex === 0 || isSubmitting}
              className="p-1 rounded text-carbon-400 hover:text-white disabled:opacity-30 transition-colors cursor-pointer"
              title="Previous candidate"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setCurrentIndex((prev) => Math.min(total - 1, prev + 1))}
              disabled={currentIndex >= total - 1 || isSubmitting}
              className="p-1 rounded text-carbon-400 hover:text-white disabled:opacity-30 transition-colors cursor-pointer"
              title="Next candidate"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              disabled={isSubmitting}
              data-testid="btn-close-candidate-modal"
              className="p-1 rounded text-carbon-400 hover:text-white hover:bg-carbon-800 disabled:opacity-30 transition-colors ml-2 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Error Alert Banner */}
        {error && (
          <div
            role="alert"
            data-testid="candidate-group-error"
            className="px-4 py-2 bg-red-950/80 border-b border-red-800 text-red-300 text-xs flex items-center justify-between animate-fade-in"
          >
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              type="button"
              onClick={() => setError(null)}
              className="p-0.5 text-red-400 hover:text-white rounded cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Similarity Match Badge */}
        <div className="px-4 py-2 bg-carbon-950 border-b border-carbon-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {is_exact_duplicate ? (
              <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
                <Sparkles className="w-3 h-3" /> Exact Duplicate (100% Match)
              </span>
            ) : (
              <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 flex items-center gap-1">
                <Layers className="w-3 h-3" /> Perceptual Match ({similarityPct}% — {hamming_distance}/64 bits difference)
              </span>
            )}
          </div>
          <span className="text-[11px] text-carbon-400">
            Grouping reduces cloud searches to 1 call per group
          </span>
        </div>

        {/* Side-by-side comparison */}
        <div className="p-4 grid grid-cols-2 gap-4 overflow-y-auto">
          <CandidateCard
            image={image_a}
            label="Candidate A"
            isSelected={selectedPreferred === 'A'}
            onSelect={() => setSelectedPreferred('A')}
          />
          <CandidateCard
            image={image_b}
            label="Candidate B"
            isSelected={selectedPreferred === 'B'}
            onSelect={() => setSelectedPreferred('B')}
          />
        </div>

        {/* Footer Actions */}
        <div className="px-4 py-3 border-t border-carbon-800 bg-carbon-950/60 flex items-center justify-between">
          <button
            onClick={handleDismiss}
            disabled={isSubmitting}
            data-testid="btn-keep-separate"
            className="px-3 py-1.5 rounded-lg border border-carbon-700 bg-carbon-800/50 hover:bg-carbon-800 hover:text-white text-carbon-300 text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
          >
            <XCircle className="w-4 h-4 text-carbon-400" />
            Keep Separate
          </button>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                if (currentIndex < total - 1) {
                  setCurrentIndex((prev) => prev + 1);
                } else {
                  onClose();
                }
              }}
              disabled={isSubmitting}
              className="px-3 py-1.5 rounded-lg text-carbon-400 hover:text-white text-xs transition-colors cursor-pointer"
            >
              Skip
            </button>
            <button
              onClick={handleGroup}
              disabled={isSubmitting}
              data-testid={isAlreadyGrouped ? 'btn-add-to-existing-group' : 'btn-group-representations'}
              className="px-4 py-1.5 rounded-lg bg-accent-600 hover:bg-accent-500 text-white font-medium text-xs shadow-sm flex items-center gap-1.5 transition-colors disabled:opacity-50 cursor-pointer"
            >
              <CheckCircle2 className="w-4 h-4" />
              <span>{isAlreadyGrouped ? 'Add to Existing Group' : 'Group as Representations'}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
