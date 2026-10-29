import React from 'react';
import { Camera, Layers, CheckSquare, BarChart3, Settings, Sparkles } from 'lucide-react';
import { AppSettings, UsageSummary } from '../types';
import { APP_VERSION } from '../version';

interface HeaderProps {
  activeTab: 'library' | 'review' | 'usage' | 'settings';
  setActiveTab: (tab: 'library' | 'review' | 'usage' | 'settings') => void;
  settings: AppSettings | null;
  usageSummary: UsageSummary | null;
  unreviewedCount: number;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  settings,
  usageSummary,
  unreviewedCount,
}) => {
  const isMock = settings?.active_provider === 'mock';

  return (
    <header className="sticky top-0 z-30 bg-carbon-950/95 backdrop-blur-md border-b border-carbon-800 px-4 sm:px-6 py-2.5 transition-colors">
      <div className="max-w-[1600px] mx-auto flex items-center justify-between gap-3">
        {/* Brand & Mode Tag */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-md bg-carbon-900 border border-carbon-700 flex items-center justify-center text-accent-500 shadow-xs">
              <Camera className="w-4 h-4" />
            </div>
            <div className="flex items-baseline gap-2">
              <span className="font-semibold text-sm tracking-tight text-carbon-100">Photo Privateer</span>
              <span className="text-[10px] font-mono uppercase text-carbon-400">
                v{APP_VERSION}
              </span>
            </div>
          </div>

          {/* Mode Pill */}
          <div className="hidden sm:block">
            {isMock ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/10 text-amber-300 border border-amber-500/30">
                <Sparkles className="w-3 h-3 text-amber-400" />
                <span>Mock Mode (Offline)</span>
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-accent-500/10 text-accent-300 border border-accent-500/30">
                <span className="w-1.5 h-1.5 rounded-full bg-accent-400 animate-pulse" />
                <span>Google Cloud Vision</span>
              </span>
            )}
          </div>
        </div>

        {/* Precision Navigation Segmented Bar */}
        <nav className="flex items-center gap-1 bg-carbon-900 p-0.5 rounded-lg border border-carbon-800 text-xs">
          <button
            onClick={() => setActiveTab('library')}
            data-testid="nav-library"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium border transition-colors duration-200 ${
              activeTab === 'library'
                ? 'bg-carbon-800 text-white shadow-xs border-carbon-700/60'
                : 'border-transparent text-carbon-400 hover:text-carbon-200 hover:bg-carbon-850'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Library</span>
          </button>

          <button
            onClick={() => setActiveTab('review')}
            data-testid="nav-review"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium border transition-colors duration-200 ${
              activeTab === 'review'
                ? 'bg-carbon-800 text-white shadow-xs border-carbon-700/60'
                : 'border-transparent text-carbon-400 hover:text-carbon-200 hover:bg-carbon-850'
            }`}
          >
            <CheckSquare className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Review Queue</span>
            {unreviewedCount > 0 && (
              <span className="px-1.5 py-0.2 rounded font-mono text-[10px] font-bold bg-amber-500 text-carbon-950 tabular-nums">
                {unreviewedCount}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('usage')}
            data-testid="nav-usage"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium border transition-colors duration-200 ${
              activeTab === 'usage'
                ? 'bg-carbon-800 text-white shadow-xs border-carbon-700/60'
                : 'border-transparent text-carbon-400 hover:text-carbon-200 hover:bg-carbon-850'
            }`}
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Usage & Cost</span>
            {usageSummary && usageSummary.units_used_this_month > 0 && (
              <span className="text-[10px] font-mono text-carbon-400 tabular-nums hidden md:inline">
                {usageSummary.units_used_this_month}u
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('settings')}
            data-testid="nav-settings"
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md font-medium border transition-colors duration-200 ${
              activeTab === 'settings'
                ? 'bg-carbon-800 text-white shadow-xs border-carbon-700/60'
                : 'border-transparent text-carbon-400 hover:text-carbon-200 hover:bg-carbon-850'
            }`}
          >
            <Settings className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Settings</span>
          </button>
        </nav>
      </div>
    </header>
  );
};
