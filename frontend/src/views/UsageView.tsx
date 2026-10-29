import React, { useState, useEffect } from 'react';
import {
  ShieldCheck,
  ShieldAlert,
  Coins,
  History,
  Sparkles,
  Info,
  CheckCircle,
  XCircle,
} from 'lucide-react';
import { UsageSummary, ProviderCall, AppSettings } from '../types';
import { fetchUsageSummary, fetchProviderCalls } from '../api/client';

interface UsageViewProps {
  settings: AppSettings | null;
  onNavigateToSettings: () => void;
}

export const UsageView: React.FC<UsageViewProps> = ({ settings, onNavigateToSettings }) => {
  const [summary, setSummary] = useState<UsageSummary | null>(null);
  const [calls, setCalls] = useState<ProviderCall[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);

  const loadUsageData = async () => {
    setLoading(true);
    try {
      const [sum, callList] = await Promise.all([fetchUsageSummary(), fetchProviderCalls(50)]);
      setSummary(sum);
      setCalls(callList);
      setHasLoadedOnce(true);
    } catch (err) {
      console.error('Failed loading usage data', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadUsageData();
  }, []);

  return (
    <div className="max-w-[1400px] mx-auto px-4 sm:px-6 py-4 space-y-4 text-xs">
      {/* Local Estimate Notice */}
      <div className="bg-amber-500/10 border border-amber-500/25 rounded-lg p-3 flex items-start gap-2.5 text-amber-200/90 text-xs">
        <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-0.5">
          <span className="font-semibold text-amber-300">Local Estimated Accounting: </span>
          <span className="text-amber-200/80 leading-normal">
            {summary?.disclaimer ||
              'All usage figures are local estimates computed by Photo Privateer. Official Google Cloud Platform invoices remain authoritative.'}
          </span>
        </div>
      </div>

      {/* KPI Tiles Strip */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Monthly Units */}
        <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-3.5 space-y-1">
          <div className="flex items-center justify-between text-carbon-400 text-[11px]">
            <span>Monthly Units</span>
            <span className="font-mono">{summary?.billing_period}</span>
          </div>
          <p className="text-2xl font-bold text-white font-mono tabular-nums">{summary?.units_used_this_month ?? 0}</p>
          <div className="text-[10px] text-carbon-500">
            Cloud Vision Web Detection units
          </div>
        </div>

        {/* Free Tier Allowance */}
        <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-3.5 space-y-1">
          <div className="flex items-center justify-between text-carbon-400 text-[11px]">
            <span>Free Tier Allowance</span>
            <Sparkles className="w-3.5 h-3.5 text-accent-400" />
          </div>
          <p className="text-2xl font-bold text-white font-mono tabular-nums">{summary?.free_tier_allowance ?? 1000}</p>
          <div className="text-[10px] text-carbon-500">
            Included monthly at $0.00
          </div>
        </div>

        {/* Remaining Free */}
        <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-3.5 space-y-1">
          <div className="flex items-center justify-between text-carbon-400 text-[11px]">
            <span>Remaining Free Units</span>
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
          </div>
          <p className="text-2xl font-bold text-emerald-400 font-mono tabular-nums">
            {summary?.remaining_free_units ?? 1000}
          </p>
          <div className="text-[10px] text-carbon-500">
            Units before incremental charge
          </div>
        </div>

        {/* Estimated Cost */}
        <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-3.5 space-y-1">
          <div className="flex items-center justify-between text-carbon-400 text-[11px]">
            <span>Estimated Cost</span>
            <Coins className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <p className="text-2xl font-bold text-white font-mono tabular-nums">
            ${summary?.estimated_total_cost_usd.toFixed(2) ?? '0.00'}
          </p>
          <div className="text-[10px] text-carbon-500">
            ${(settings?.unit_price_usd ?? 0.0035).toFixed(4)}/unit ($${((settings?.unit_price_usd ?? 0.0035) * 1000).toFixed(2)}/1k) beyond free tier
          </div>
        </div>
      </div>

      {/* Free Tier Guard Status */}
      <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-3.5 flex flex-col sm:flex-row items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <div
            className={`p-1.5 rounded-md ${
              summary?.is_guard_enabled
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30'
                : 'bg-amber-500/10 text-amber-400 border border-amber-500/30'
            }`}
          >
            {summary?.is_guard_enabled ? <ShieldCheck className="w-4 h-4" /> : <ShieldAlert className="w-4 h-4" />}
          </div>
          <div>
            <span className="font-semibold text-white">
              Free-Tier Safety Guard:{' '}
              <span className={summary?.is_guard_enabled ? 'text-emerald-400' : 'text-amber-400'}>
                {summary?.is_guard_enabled ? 'Enforced' : 'Disabled'}
              </span>
            </span>
            <p className="text-[11px] text-carbon-400">
              {summary?.is_guard_enabled
                ? 'Scans that exceed the free monthly allowance are blocked without explicit authorization.'
                : 'Scans proceed automatically into billable usage.'}
            </p>
          </div>
        </div>
        <button
          onClick={onNavigateToSettings}
          className="px-3 py-1.5 rounded-md text-xs font-semibold bg-carbon-800 hover:bg-carbon-700 text-white transition-colors shrink-0"
        >
          Configure Guard
        </button>
      </div>

      {/* Provider Calls Audit Table */}
      <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-3.5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <History className="w-3.5 h-3.5 text-accent-400" />
            <h3 className="font-semibold text-white text-xs">Provider Call Audit Log</h3>
          </div>
          <span className="text-[11px] font-mono text-carbon-400 tabular-nums">
            Lifetime calls: {summary?.total_lifetime_calls ?? 0}
          </span>
        </div>

        {!hasLoadedOnce && loading ? (
          <div className="space-y-1.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-8 bg-carbon-950 rounded animate-pulse" />
            ))}
          </div>
        ) : calls.length === 0 ? (
          <div className="py-8 text-center text-xs text-carbon-500">
            No API calls recorded. Scans will be logged here with timestamps and billing periods.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-carbon-800 text-carbon-400 font-mono text-[10px] uppercase tracking-wider">
                  <th className="pb-2 px-2.5">Timestamp</th>
                  <th className="pb-2 px-2.5">Provider</th>
                  <th className="pb-2 px-2.5">Period</th>
                  <th className="pb-2 px-2.5 text-center">Units</th>
                  <th className="pb-2 px-2.5 text-center">Status</th>
                  <th className="pb-2 px-2.5 text-right">Est. Cost</th>
                  <th className="pb-2 px-2.5">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-carbon-800/60 font-mono text-[11px]">
                {calls.map((call) => (
                  <tr key={call.id} className="hover:bg-carbon-950/40 transition-colors">
                    <td className="py-2 px-2.5 text-carbon-300 tabular-nums">
                      {new Date(call.timestamp).toLocaleString()}
                    </td>
                    <td className="py-2 px-2.5 font-sans">
                      {call.provider === 'mock' ? (
                        <span className="px-1.5 py-0.2 rounded text-[10px] bg-amber-500/15 text-amber-300 border border-amber-500/30 font-mono font-semibold">
                          MOCK (Free)
                        </span>
                      ) : (
                        <span className="px-1.5 py-0.2 rounded text-[10px] bg-accent-500/15 text-accent-300 border border-accent-500/30 font-mono">
                          Google Vision
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-2.5 text-carbon-400">{call.billing_period}</td>
                    <td className="py-2 px-2.5 text-center text-white tabular-nums">{call.attempted_units}</td>
                    <td className="py-2 px-2.5 text-center font-sans">
                      {call.request_status === 'SUCCESS' ? (
                        <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                          <CheckCircle className="w-3 h-3" />
                          <span>Success</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-[11px] text-rose-400">
                          <XCircle className="w-3 h-3" />
                          <span>Failed</span>
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-2.5 text-right text-emerald-400 tabular-nums">
                      ${call.estimated_cost.toFixed(4)}
                    </td>
                    <td className="py-2 px-2.5 text-carbon-400 max-w-xs truncate font-sans text-[11px]">
                      {call.error_message || 'OK'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};
