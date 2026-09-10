import React, { useState } from 'react';
import { ShieldAlert, AlertTriangle, Sparkles, X, ArrowRight } from 'lucide-react';
import { ScanPrepareResponse } from '../types';

interface ScanConfirmModalProps {
  projection: ScanPrepareResponse;
  onConfirm: (forceOverride: boolean) => void;
  onClose: () => void;
}

export const ScanConfirmModal: React.FC<ScanConfirmModalProps> = ({
  projection,
  onConfirm,
  onClose,
}) => {
  const [forceOverride, setForceOverride] = useState(false);
  const isMock = projection.provider === 'mock';
  const isBlocked = (projection.blocked_by_guard && !forceOverride) || projection.usable_count === 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
      <div className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-md shadow-2xl overflow-hidden text-carbon-100 text-xs animate-scale-up">
        {/* Header */}
        <div className="px-4 py-3 border-b border-carbon-800 flex items-center justify-between bg-carbon-950/60">
          <div className="flex items-center gap-2">
            <div className={`p-1.5 rounded-md ${isMock ? 'bg-amber-500/10 text-amber-400' : 'bg-accent-600/10 text-accent-400'}`}>
              {isMock ? <Sparkles className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
            </div>
            <div>
              <h3 className="font-semibold text-white text-xs">Confirm Reverse Image Scan</h3>
              <p className="text-[10px] text-carbon-400">
                {isMock ? 'Deterministic Mock Provider' : 'Google Cloud Vision Web Detection'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-carbon-400 hover:text-white hover:bg-carbon-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-3.5">
          {/* Metrics summary */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-2.5">
              <span className="text-[11px] text-carbon-400">Selected Photos</span>
              <p className="text-xl font-bold text-white font-mono mt-0.5 tabular-nums">{projection.selected_count}</p>
              {projection.missing_count > 0 && (
                <p className="text-[10px] text-amber-400 font-mono mt-0.5">
                  {projection.usable_count} available ({projection.missing_count} missing)
                </p>
              )}
            </div>
            <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-2.5">
              <span className="text-[11px] text-carbon-400">Estimated Cost</span>
              <p className="text-xl font-bold text-emerald-400 font-mono mt-0.5 tabular-nums">
                ${projection.estimated_incremental_cost_usd.toFixed(2)}
              </p>
            </div>
          </div>

          {/* Usage Accounting Row */}
          {!isMock ? (
            <div className="bg-carbon-950/70 p-3 rounded-lg border border-carbon-800 space-y-1.5 text-xs">
              <div className="flex justify-between text-carbon-300">
                <span>Month Period:</span>
                <span className="font-mono text-white">{projection.current_month}</span>
              </div>
              <div className="flex justify-between text-carbon-300">
                <span>Current Recorded Units:</span>
                <span className="font-mono text-white tabular-nums">{projection.units_used_this_month} / {projection.free_tier_allowance}</span>
              </div>
              <div className="flex justify-between text-carbon-300">
                <span>Projected Total Units:</span>
                <span className="font-mono font-bold text-accent-400 tabular-nums">{projection.projected_units_total}</span>
              </div>
              <div className="flex justify-between text-carbon-300 border-t border-carbon-800 pt-1.5">
                <span>Remaining Free Units:</span>
                <span className="font-mono font-semibold text-emerald-400 tabular-nums">{projection.remaining_free_units}</span>
              </div>
            </div>
          ) : (
            <div className="bg-amber-500/10 border border-amber-500/25 p-3 rounded-lg flex items-start gap-2.5 text-xs text-amber-200">
              <Sparkles className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
              <p className="text-[11px] leading-relaxed">
                <strong className="text-amber-300">Mock Mode:</strong> Offline deterministic sample results. Zero external network calls and zero Google Vision API units consumed.
              </p>
            </div>
          )}

          {/* Free Tier Guard Warning */}
          {projection.free_tier_exceeded && !isMock && (
            <div className="bg-rose-500/10 border border-rose-500/30 p-3 rounded-lg text-xs space-y-1.5">
              <div className="flex items-center gap-1.5 text-rose-300 font-semibold">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />
                <span>Free Tier Allowance Exceeded</span>
              </div>
              <p className="text-[11px] text-rose-200/90 leading-normal">
                This batch exceeds your free monthly limit ({projection.free_tier_allowance} units).
                Estimated charge: ${projection.estimated_incremental_cost_usd.toFixed(2)} USD.
              </p>
              {projection.blocked_by_guard && (
                <label className="flex items-center gap-2 pt-1 text-white font-medium cursor-pointer">
                  <input
                    type="checkbox"
                    checked={forceOverride}
                    onChange={(e) => setForceOverride(e.target.checked)}
                    className="rounded bg-carbon-950 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
                  />
                  <span className="text-[11px]">Authorize scan beyond free tier</span>
                </label>
              )}
            </div>
          )}

          {/* Local Estimate Footnote */}
          <p className="text-[10px] text-carbon-500 leading-tight">
            * All figures are local estimates. Google Cloud Platform invoices remain authoritative.
          </p>
        </div>

        {/* Footer */}
        <div className="px-4 py-3 bg-carbon-950/80 border-t border-carbon-800 flex items-center justify-end gap-2">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-md text-xs font-medium text-carbon-300 hover:text-white hover:bg-carbon-850 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onConfirm(forceOverride)}
            disabled={isBlocked}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-md text-xs font-semibold shadow-xs transition-all ${
              isBlocked
                ? 'bg-carbon-800 text-carbon-500 cursor-not-allowed'
                : 'bg-accent-600 hover:bg-accent-500 text-white shadow-accent-600/20 active:scale-98'
            }`}
          >
            <span>Start Scan ({projection.usable_count})</span>
            <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
