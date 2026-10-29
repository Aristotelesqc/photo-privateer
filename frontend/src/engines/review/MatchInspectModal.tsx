import React, { useState, useEffect } from 'react';
import {
  Globe,
  X,
  ExternalLink,
  Eye,
  ImageOff,
  CheckCircle,
  AlertOctagon,
  EyeOff,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { MatchItem, ClassificationType } from '../../types';
import { ProjectBadge } from '../../components/blocks/ProjectBadge';

export interface MatchInspectModalProps {
  match: MatchItem | null;
  onClose: () => void;
  onClassify: (matchId: number, classification: ClassificationType) => void;
  onPrev?: () => void;
  onNext?: () => void;
  hasPrev?: boolean;
  hasNext?: boolean;
}

export const MatchInspectModal: React.FC<MatchInspectModalProps> = ({
  match: inspectingMatch,
  onClose,
  onClassify,
  onPrev,
  onNext,
  hasPrev = false,
  hasNext = false,
}) => {
  const [inspectRemoteError, setInspectRemoteError] = useState(false);
  const [inspectRemoteRevealed, setInspectRemoteRevealed] = useState(false);
  const [originalError, setOriginalError] = useState(false);

  useEffect(() => {
    setInspectRemoteError(false);
    setInspectRemoteRevealed(false);
    setOriginalError(false);
  }, [inspectingMatch?.id]);

  useEffect(() => {
    if (!inspectingMatch) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowLeft' && hasPrev && onPrev) {
        onPrev();
      } else if (e.key === 'ArrowRight' && hasNext && onNext) {
        onNext();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [inspectingMatch, onClose, hasPrev, hasNext, onPrev, onNext]);

  if (!inspectingMatch) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Inspect Web Match"
      className="fixed inset-0 z-50 bg-black/80 backdrop-blur-xs flex items-center justify-center p-4 animate-fade-in"
    >
      <div className="bg-carbon-900 border border-carbon-700 rounded-xl max-w-5xl w-full max-h-[92vh] flex flex-col overflow-hidden shadow-2xl animate-scale-up">
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
            onClick={onClose}
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
              <div className="flex items-center gap-1.5 font-mono text-[10px] truncate max-w-[240px]">
                {inspectingMatch.image_project && (
                  <ProjectBadge
                    project={inspectingMatch.image_project}
                    truncate
                    className="border-carbon-700"
                  />
                )}
                <span className="text-carbon-500 truncate">{inspectingMatch.image_filename}</span>
              </div>
            </div>
            <div className="flex-1 min-h-[280px] max-h-[50vh] flex items-center justify-center overflow-hidden rounded bg-carbon-900/60 border border-carbon-800/80">
              {originalError ? (
                <div
                  data-testid="original-unavailable"
                  className="flex flex-col items-center gap-2 text-carbon-400 text-xs p-4 text-center"
                >
                  <ImageOff className="w-6 h-6" />
                  <span>The original photo is unavailable (moved, unmounted or in an archived library).</span>
                </div>
              ) : (
                <img
                  src={`/api/photos/${inspectingMatch.display_image_id ?? inspectingMatch.image_id}/file`}
                  alt={inspectingMatch.image_filename || 'Original photo'}
                  className="max-h-[48vh] max-w-full object-contain rounded"
                  onError={() => setOriginalError(true)}
                />
              )}
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
                onClassify(inspectingMatch.id, 'APPROVED');
              }}
              className={`px-3 py-1 rounded text-xs font-medium border flex items-center gap-1.5 transition-colors duration-200 ${
                inspectingMatch.classification === 'APPROVED'
                  ? 'bg-emerald-500 border-emerald-400 text-carbon-950'
                  : 'bg-carbon-900 border-carbon-700 text-carbon-200 hover:border-emerald-500/50'
              }`}
            >
              <CheckCircle className={`w-3.5 h-3.5 ${inspectingMatch.classification === 'APPROVED' ? 'text-carbon-950' : 'text-emerald-400'}`} />
              <span>Approved</span>
            </button>
            <button
              onClick={() => {
                onClassify(inspectingMatch.id, 'UNAUTHORIZED');
              }}
              className={`px-3 py-1 rounded text-xs font-medium border flex items-center gap-1.5 transition-colors duration-200 ${
                inspectingMatch.classification === 'UNAUTHORIZED'
                  ? 'bg-rose-500 border-rose-400 text-white'
                  : 'bg-carbon-900 border-carbon-700 text-carbon-200 hover:border-rose-500/50'
              }`}
            >
              <AlertOctagon className={`w-3.5 h-3.5 ${inspectingMatch.classification === 'UNAUTHORIZED' ? 'text-white' : 'text-rose-400'}`} />
              <span>Infringing</span>
            </button>
            <button
              onClick={() => {
                onClassify(inspectingMatch.id, 'IRRELEVANT');
              }}
              className={`px-3 py-1 rounded text-xs font-medium border flex items-center gap-1.5 transition-colors duration-200 ${
                inspectingMatch.classification === 'IRRELEVANT'
                  ? 'bg-carbon-700 border-carbon-600 text-white'
                  : 'bg-carbon-900 border-carbon-700 text-carbon-200 hover:border-carbon-600'
              }`}
            >
              <EyeOff className={`w-3.5 h-3.5 ${inspectingMatch.classification === 'IRRELEVANT' ? 'text-white' : 'text-carbon-400'}`} />
              <span>Irrelevant</span>
            </button>
            <button
              onClick={() => {
                onClassify(inspectingMatch.id, 'UNREVIEWED');
              }}
              className={`px-2 py-1 rounded text-xs font-medium transition-colors duration-200 text-carbon-400 hover:text-carbon-200 ${
                inspectingMatch.classification === 'UNREVIEWED' ? 'text-amber-400 bg-amber-500/10' : ''
              }`}
            >
              <RotateCcw className="w-3 h-3 inline mr-1" />
              <span>Reset</span>
            </button>
          </div>

          <div className="flex items-center gap-2">
            {(onPrev || onNext) && (
              <div className="flex items-center gap-1 mr-1">
                <button
                  type="button"
                  onClick={onPrev}
                  disabled={!hasPrev}
                  aria-label="Previous match"
                  title="Previous match (Left Arrow)"
                  className="p-1.5 rounded bg-carbon-900 border border-carbon-800 text-carbon-300 hover:text-white hover:bg-carbon-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronLeft className="w-3.5 h-3.5" />
                </button>
                <button
                  type="button"
                  onClick={onNext}
                  disabled={!hasNext}
                  aria-label="Next match"
                  title="Next match (Right Arrow)"
                  className="p-1.5 rounded bg-carbon-900 border border-carbon-800 text-carbon-300 hover:text-white hover:bg-carbon-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>
            )}
            <button
              onClick={onClose}
              className="px-3.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-white text-xs font-medium transition-colors"
            >
              Back to Review Queue
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
