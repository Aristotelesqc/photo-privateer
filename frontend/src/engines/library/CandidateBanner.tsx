import React from 'react';
import { Layers } from 'lucide-react';

export interface CandidateBannerProps {
  /** Total number of candidate pairs (not capped by the review page size) */
  count: number;
  onReview: () => void;
}

export const CandidateBanner: React.FC<CandidateBannerProps> = ({ count, onReview }) => {
  if (count <= 0) return null;

  return (
    <div className="flex items-center justify-between px-3.5 py-2.5 bg-accent-950/40 border border-accent-800/60 rounded-lg text-xs animate-fade-in">
      <div className="flex items-center gap-2 text-carbon-200">
        <Layers className="w-4 h-4 text-accent-400 shrink-0" />
        <span>
          <strong className="text-white font-medium">
            {count} candidate representation {count === 1 ? 'pair' : 'pairs'}
          </strong>{' '}
          detected (exact duplicates or perceptual variants). Grouping saves search credits by scanning 1 representation per photo.
        </span>
      </div>
      <button
        onClick={onReview}
        data-testid="btn-review-candidates"
        className="px-3 py-1 bg-accent-600 hover:bg-accent-500 text-white rounded font-medium text-xs shadow-xs transition-colors shrink-0 flex items-center gap-1.5 cursor-pointer"
      >
        <span>Review Candidates ({count})</span>
      </button>
    </div>
  );
};
