import React, { useState, useEffect } from 'react';
import { Layers, CheckCircle2, XCircle, ArrowLeft, ArrowRight, X, Sparkles, Check } from 'lucide-react';
import { GroupCandidatePair } from '../types';

interface CandidateGroupModalProps {
  candidates: GroupCandidatePair[];
  onGroup: (imageAId: number, imageBId: number, preferredId: number) => Promise<void>;
  onDismiss: (imageAId: number, imageBId: number) => Promise<void>;
  onClose: () => void;
}

export const CandidateGroupModal: React.FC<CandidateGroupModalProps> = ({
  candidates,
  onGroup,
  onDismiss,
  onClose,
}) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedPreferred, setSelectedPreferred] = useState<'A' | 'B'>('A');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const currentPair = candidates[currentIndex] || candidates[0];

  // Reset preferred selection to Candidate A when navigating or advancing pairs
  useEffect(() => {
    setSelectedPreferred('A');
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
            className="px-4 py-1.5 bg-carbon-800 hover:bg-carbon-700 text-white rounded-lg text-xs font-medium transition-colors"
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

  const handleGroup = async () => {
    setIsSubmitting(true);
    try {
      const preferredId = selectedPreferred === 'A' ? image_a.id : image_b.id;
      await onGroup(image_a.id, image_b.id, preferredId);
      if (candidates.length <= 1) {
        onClose();
      } else if (currentIndex >= total - 1) {
        setCurrentIndex(Math.max(0, total - 2));
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDismiss = async () => {
    setIsSubmitting(true);
    try {
      await onDismiss(image_a.id, image_b.id);
      if (candidates.length <= 1) {
        onClose();
      } else if (currentIndex >= total - 1) {
        setCurrentIndex(Math.max(0, total - 2));
      }
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
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentIndex((prev) => Math.max(0, prev - 1))}
              disabled={currentIndex === 0 || isSubmitting}
              className="p-1 rounded text-carbon-400 hover:text-white disabled:opacity-30 transition-colors"
              title="Previous candidate"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setCurrentIndex((prev) => Math.min(total - 1, prev + 1))}
              disabled={currentIndex >= total - 1 || isSubmitting}
              className="p-1 rounded text-carbon-400 hover:text-white disabled:opacity-30 transition-colors"
              title="Next candidate"
            >
              <ArrowRight className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              disabled={isSubmitting}
              data-testid="btn-close-candidate-modal"
              className="p-1 rounded text-carbon-400 hover:text-white hover:bg-carbon-800 disabled:opacity-30 transition-colors ml-2"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

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
          {/* Card A */}
          <div
            onClick={() => setSelectedPreferred('A')}
            data-testid={`candidate-card-${image_a.filename}`}
            className={`border rounded-lg p-3 bg-carbon-950 cursor-pointer transition-all ${
              selectedPreferred === 'A'
                ? 'border-accent-500 ring-1 ring-accent-500/30'
                : 'border-carbon-800 hover:border-carbon-700'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold text-carbon-400 uppercase tracking-wider">Candidate A</span>
              <div
                className={`w-4 h-4 rounded-full flex items-center justify-center border ${
                  selectedPreferred === 'A'
                    ? 'border-accent-500 bg-accent-500 text-white'
                    : 'border-carbon-600 bg-carbon-800'
                }`}
              >
                {selectedPreferred === 'A' && <Check className="w-3 h-3 stroke-[3]" />}
              </div>
            </div>
            <div className="aspect-square bg-carbon-900 rounded overflow-hidden mb-2.5 flex items-center justify-center border border-carbon-800">
              <img
                src={image_a.thumbnail_url}
                alt={image_a.filename}
                className="w-full h-full object-contain"
                loading="lazy"
              />
            </div>
            <div className="space-y-1">
              <p className="font-mono text-white text-xs truncate" title={image_a.filename}>
                {image_a.filename}
              </p>
              <div className="text-[11px] text-carbon-400 flex flex-wrap gap-x-2">
                <span>
                  {image_a.width && image_a.height ? `${image_a.width}×${image_a.height}` : 'Dimensions unknown'}
                </span>
                <span>•</span>
                <span>{(image_a.file_size / 1024).toFixed(1)} KB</span>
                {image_a.format && (
                  <>
                    <span>•</span>
                    <span className="uppercase">{image_a.format}</span>
                  </>
                )}
              </div>
              {image_a.project && (
                <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] bg-carbon-800 text-carbon-300 font-mono">
                  {image_a.project}
                </span>
              )}
            </div>
            <div className="mt-3 pt-2 border-t border-carbon-800/80 text-[10px] text-carbon-400">
              {selectedPreferred === 'A' ? (
                <span className="text-accent-400 font-medium">Preferred (Used for Web Reverse Searches)</span>
              ) : (
                <span>Click to set as preferred search representation</span>
              )}
            </div>
          </div>

          {/* Card B */}
          <div
            onClick={() => setSelectedPreferred('B')}
            data-testid={`candidate-card-${image_b.filename}`}
            className={`border rounded-lg p-3 bg-carbon-950 cursor-pointer transition-all ${
              selectedPreferred === 'B'
                ? 'border-accent-500 ring-1 ring-accent-500/30'
                : 'border-carbon-800 hover:border-carbon-700'
            }`}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-semibold text-carbon-400 uppercase tracking-wider">Candidate B</span>
              <div
                className={`w-4 h-4 rounded-full flex items-center justify-center border ${
                  selectedPreferred === 'B'
                    ? 'border-accent-500 bg-accent-500 text-white'
                    : 'border-carbon-600 bg-carbon-800'
                }`}
              >
                {selectedPreferred === 'B' && <Check className="w-3 h-3 stroke-[3]" />}
              </div>
            </div>
            <div className="aspect-square bg-carbon-900 rounded overflow-hidden mb-2.5 flex items-center justify-center border border-carbon-800">
              <img
                src={image_b.thumbnail_url}
                alt={image_b.filename}
                className="w-full h-full object-contain"
                loading="lazy"
              />
            </div>
            <div className="space-y-1">
              <p className="font-mono text-white text-xs truncate" title={image_b.filename}>
                {image_b.filename}
              </p>
              <div className="text-[11px] text-carbon-400 flex flex-wrap gap-x-2">
                <span>
                  {image_b.width && image_b.height ? `${image_b.width}×${image_b.height}` : 'Dimensions unknown'}
                </span>
                <span>•</span>
                <span>{(image_b.file_size / 1024).toFixed(1)} KB</span>
                {image_b.format && (
                  <>
                    <span>•</span>
                    <span className="uppercase">{image_b.format}</span>
                  </>
                )}
              </div>
              {image_b.project && (
                <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] bg-carbon-800 text-carbon-300 font-mono">
                  {image_b.project}
                </span>
              )}
            </div>
            <div className="mt-3 pt-2 border-t border-carbon-800/80 text-[10px] text-carbon-400">
              {selectedPreferred === 'B' ? (
                <span className="text-accent-400 font-medium">Preferred (Used for Web Reverse Searches)</span>
              ) : (
                <span>Click to set as preferred search representation</span>
              )}
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="px-4 py-3 border-t border-carbon-800 bg-carbon-950/60 flex items-center justify-between">
          <button
            onClick={handleDismiss}
            disabled={isSubmitting}
            data-testid="btn-keep-separate"
            className="px-3 py-1.5 rounded-lg border border-carbon-700 bg-carbon-800/50 hover:bg-carbon-800 hover:text-white text-carbon-300 text-xs font-medium flex items-center gap-1.5 transition-colors disabled:opacity-50"
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
              className="px-3 py-1.5 rounded-lg text-carbon-400 hover:text-white text-xs transition-colors"
            >
              Skip
            </button>
            <button
              onClick={handleGroup}
              disabled={isSubmitting}
              data-testid="btn-group-representations"
              className="px-4 py-1.5 rounded-lg bg-accent-600 hover:bg-accent-500 text-white font-medium text-xs shadow-sm flex items-center gap-1.5 transition-colors disabled:opacity-50"
            >
              <CheckCircle2 className="w-4 h-4" />
              Group as Representations
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
