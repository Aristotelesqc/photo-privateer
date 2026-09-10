import React, { useState, useEffect } from 'react';
import { Loader2, CheckCircle2, XCircle, AlertTriangle, StopCircle } from 'lucide-react';
import { ScanSession } from '../types';
import { fetchScanSession, cancelScan } from '../api/client';

interface ScanProgressModalProps {
  session: ScanSession | null;
  loading?: boolean;
  onClose: () => void;
  onScanFinished?: (session: ScanSession) => void;
}

export const ScanProgressModal: React.FC<ScanProgressModalProps> = ({
  session: initialSession,
  loading = false,
  onClose,
  onScanFinished,
}) => {
  const [session, setSession] = useState<ScanSession | null>(initialSession);
  const [cancelling, setCancelling] = useState(false);

  useEffect(() => {
    setSession(initialSession);
  }, [initialSession]);

  // Real backend progress polling while scan is RUNNING
  useEffect(() => {
    if (!session || session.status !== 'RUNNING') return;

    let isMounted = true;
    const interval = setInterval(async () => {
      try {
        const updated = await fetchScanSession(session.id);
        if (!isMounted) return;
        setSession(updated);

        if (updated.status !== 'RUNNING') {
          clearInterval(interval);
          setCancelling(false);
          onScanFinished?.(updated);
        }
      } catch (err) {
        console.error('Failed to poll scan status:', err);
      }
    }, 600);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [session?.id, session?.status, onScanFinished]);

  const handleCancelClick = async () => {
    if (!session || session.status !== 'RUNNING' || cancelling) return;
    setCancelling(true);
    try {
      const res = await cancelScan(session.id);
      setSession(res);
    } catch (err) {
      console.error('Failed to request scan cancellation:', err);
      setCancelling(false);
    }
  };

  const isRunning = Boolean(loading || (session && session.status === 'RUNNING'));
  const total = session?.total_images || 0;
  const processed = session?.processed_images || 0;
  const percent = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;
  const isCancelled = session?.status === 'CANCELLED';
  const isInterrupted = session?.status === 'INTERRUPTED';
  const isFailed = session?.status === 'FAILED';
  const isCompleted = session?.status === 'COMPLETED';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
      <div className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-sm shadow-2xl p-5 text-carbon-100 text-center text-xs animate-scale-up">
        {/* Status Icon */}
        <div className="mx-auto w-10 h-10 rounded-full flex items-center justify-center mb-3">
          {isRunning ? (
            <div className="w-10 h-10 rounded-full bg-accent-500/10 flex items-center justify-center text-accent-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : isCompleted ? (
            <div className="w-10 h-10 rounded-full bg-emerald-500/10 flex items-center justify-center text-emerald-400">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          ) : isCancelled ? (
            <div className="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center text-amber-400">
              <StopCircle className="w-5 h-5" />
            </div>
          ) : isInterrupted ? (
            <div className="w-10 h-10 rounded-full bg-amber-500/10 flex items-center justify-center text-amber-400">
              <AlertTriangle className="w-5 h-5" />
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
            ? cancelling || session?.cancel_requested
              ? 'Cancelling Scan...'
              : 'Scanning Batch...'
            : isCompleted
            ? 'Batch Completed'
            : isCancelled
            ? 'Scan Cancelled'
            : isInterrupted
            ? 'Scan Interrupted'
            : 'Scan Failed'}
        </h3>
        <p className="text-[11px] text-carbon-400 mb-4">
          {isRunning
            ? cancelling || session?.cancel_requested
              ? 'Finishing in-flight photo before halting...'
              : `Reverse-searching ${total} selected photograph${total === 1 ? '' : 's'}`
            : isCancelled
            ? `Stopped cooperatively after ${processed} of ${total} images.`
            : isInterrupted
            ? 'Scan was interrupted by application shutdown.'
            : `Processed ${processed} of ${total} images`}
        </p>

        {/* Progress Bar */}
        <div className="space-y-1.5 mb-4">
          <div className="w-full h-1.5 bg-carbon-950 rounded-full overflow-hidden border border-carbon-800">
            <div
              className={`h-full rounded-full transition-all duration-300 ease-out ${
                isCancelled ? 'bg-amber-500' : isFailed ? 'bg-rose-500' : 'bg-accent-500'
              }`}
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

        {/* Notes/Warnings if present */}
        {session?.notes && !isRunning && (
          <div className="mb-3 text-[10px] text-amber-300 bg-amber-950/40 border border-amber-800/60 rounded p-1.5 text-left">
            {session.notes}
          </div>
        )}

        {/* Metrics Box */}
        {session && !isRunning && (
          <div className="grid grid-cols-2 gap-2 mb-4 text-left font-mono">
            <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-2.5">
              <span className="text-[10px] text-carbon-400 font-sans">Successful</span>
              <p className="text-base font-bold text-emerald-400 mt-0.5 tabular-nums">{session.successful_images}</p>
            </div>
            <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-2.5">
              <span className="text-[10px] text-carbon-400 font-sans">{isCancelled ? 'Remaining' : 'Failed'}</span>
              <p className={`text-base font-bold mt-0.5 tabular-nums ${isCancelled ? 'text-amber-400' : 'text-rose-400'}`}>
                {isCancelled ? total - processed : session.failed_images}
              </p>
            </div>
          </div>
        )}

        {/* Actions */}
        {isRunning ? (
          <div className="flex gap-2">
            <button
              onClick={handleCancelClick}
              disabled={cancelling || session?.cancel_requested}
              className={`w-full py-2 rounded-md text-xs font-semibold transition-all border ${
                cancelling || session?.cancel_requested
                  ? 'bg-carbon-900 border-carbon-800 text-carbon-500 cursor-not-allowed'
                  : 'bg-rose-950/40 hover:bg-rose-900/60 border-rose-800/80 text-rose-300 active:scale-98'
              }`}
            >
              {cancelling || session?.cancel_requested ? 'Cancelling...' : 'Cancel Scan'}
            </button>
          </div>
        ) : (
          <button
            onClick={onClose}
            className="w-full py-2 rounded-md text-xs font-semibold transition-all bg-carbon-800 hover:bg-carbon-700 text-white active:scale-98"
          >
            {isCompleted ? 'View Discoveries' : 'Done'}
          </button>
        )}
      </div>
    </div>
  );
};
