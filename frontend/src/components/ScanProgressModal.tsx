import React from 'react';
import { Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { ScanSession } from '../types';

interface ScanProgressModalProps {
  session: ScanSession | null;
  loading: boolean;
  onClose: () => void;
}

export const ScanProgressModal: React.FC<ScanProgressModalProps> = ({
  session,
  loading,
  onClose,
}) => {
  const isRunning = Boolean(loading || (session && session.status === 'RUNNING'));
  const total = session?.total_images || 0;
  const processed = session?.processed_images || 0;
  const percent = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
      <div className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-sm shadow-2xl p-5 text-carbon-100 text-center text-xs animate-scale-up">
        {/* Status Icon */}
        <div className="mx-auto w-10 h-10 rounded-full flex items-center justify-center mb-3">
          {isRunning ? (
            <div className="w-10 h-10 rounded-full bg-accent-500/10 flex items-center justify-center text-accent-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : session?.status === 'COMPLETED' ? (
            <div className="w-10 h-10 rounded-full bg-emerald-500/10 flex items-center justify-center text-emerald-400">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          ) : (
            <div className="w-10 h-10 rounded-full bg-rose-500/10 flex items-center justify-center text-rose-400">
              <XCircle className="w-5 h-5" />
            </div>
          )}
        </div>

        {/* Title */}
        <h3 className="text-sm font-semibold text-white mb-0.5">
          {isRunning
            ? 'Scanning Batch...'
            : session?.status === 'COMPLETED'
            ? 'Batch Completed'
            : 'Scan Failed'}
        </h3>
        <p className="text-[11px] text-carbon-400 mb-4">
          {isRunning
            ? `Reverse-searching ${total} selected photographs`
            : `Processed ${processed} of ${total} images`}
        </p>

        {/* Progress Bar */}
        <div className="space-y-1.5 mb-4">
          <div className="w-full h-1.5 bg-carbon-950 rounded-full overflow-hidden border border-carbon-800">
            <div
              className="h-full bg-accent-500 rounded-full transition-all duration-200 ease-out"
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="flex justify-between text-[10px] font-mono text-carbon-400 px-0.5 tabular-nums">
            <span>{percent}%</span>
            <span>
              {processed} / {total} photos
            </span>
          </div>
        </div>

        {/* Metrics Box */}
        {session && !isRunning && (
          <div className="grid grid-cols-2 gap-2 mb-4 text-left font-mono">
            <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-2.5">
              <span className="text-[10px] text-carbon-400 font-sans">Successful</span>
              <p className="text-base font-bold text-emerald-400 mt-0.5 tabular-nums">{session.successful_images}</p>
            </div>
            <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-2.5">
              <span className="text-[10px] text-carbon-400 font-sans">Failed</span>
              <p className="text-base font-bold text-rose-400 mt-0.5 tabular-nums">{session.failed_images}</p>
            </div>
          </div>
        )}

        {/* Actions */}
        <button
          onClick={onClose}
          disabled={Boolean(isRunning)}
          className={`w-full py-2 rounded-md text-xs font-semibold transition-all ${
            isRunning
              ? 'bg-carbon-800 text-carbon-500 cursor-not-allowed'
              : 'bg-carbon-800 hover:bg-carbon-700 text-white active:scale-98'
          }`}
        >
          {isRunning ? 'Processing...' : 'View Discoveries'}
        </button>
      </div>
    </div>
  );
};
