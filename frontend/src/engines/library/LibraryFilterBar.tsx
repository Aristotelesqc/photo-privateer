import React from 'react';
import { Search, Sparkles, ShieldAlert, Grid, LayoutGrid } from 'lucide-react';
import { Library } from '../../types';
import { FilterSelect } from '../../components/blocks/FilterSelect';

export type StatusFilterType = 'all' | 'unscanned' | 'scanned' | 'has_matches' | 'has_unreviewed';

export interface LibraryFilterBarProps {
  libraries: Library[];
  totalPhotos: number;
  selectedLibraryId?: number;
  onSelectLibrary: (libId?: number) => void;
  projects: string[];
  selectedProject?: string;
  onSelectProject: (project?: string) => void;
  searchQuery: string;
  onSearchChange: (search: string) => void;
  statusFilter: StatusFilterType;
  onStatusFilterChange: (status: StatusFilterType) => void;
  density: 'standard' | 'compact';
  onDensityChange: (density: 'standard' | 'compact') => void;
  selectedCount: number;
  preparingScan: boolean;
  activeProvider?: 'mock' | 'google_vision';
  onScanClicked: () => void;
}

export const LibraryFilterBar: React.FC<LibraryFilterBarProps> = ({
  libraries,
  totalPhotos,
  selectedLibraryId,
  onSelectLibrary,
  projects,
  selectedProject,
  onSelectProject,
  searchQuery,
  onSearchChange,
  statusFilter,
  onStatusFilterChange,
  density,
  onDensityChange,
  selectedCount,
  preparingScan,
  activeProvider,
  onScanClicked,
}) => {
  return (
    <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
      {/* Left: Library select, Search, and Status chips */}
      <div className="flex flex-wrap items-center gap-2 flex-1 min-w-[280px]">
        {/* Library Select */}
        <FilterSelect
          value={selectedLibraryId ?? ''}
          onChange={(e) => {
            const val = e.target.value;
            onSelectLibrary(val ? Number(val) : undefined);
          }}
        >
          <option value="">All Libraries ({totalPhotos})</option>
          {libraries.map((lib) => (
            <option key={lib.id} value={lib.id}>
              {lib.name} ({lib.image_count})
            </option>
          ))}
        </FilterSelect>

        {/* Project Select */}
        <FilterSelect
          value={selectedProject ?? ''}
          onChange={(e) => {
            const val = e.target.value;
            onSelectProject(val || undefined);
          }}
        >
          <option value="">All Projects</option>
          <option value="__unassigned__">No Project (Unassigned)</option>
          {projects.map((proj) => (
            <option key={proj} value={proj}>
              📁 {proj}
            </option>
          ))}
        </FilterSelect>

        {/* Search Box */}
        <div className="relative w-44 sm:w-56">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-carbon-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Filter by filename..."
            className="w-full bg-carbon-950 border border-carbon-800 rounded-md pl-8 pr-2.5 py-1.5 text-xs text-white placeholder-carbon-500 focus:outline-none focus:border-accent-500"
          />
        </div>

        {/* Status Filter Segmented Control */}
        <div className="flex items-center gap-0.5 bg-carbon-950 p-0.5 rounded-md border border-carbon-800 overflow-x-auto">
          {(
            [
              ['all', 'All'],
              ['unscanned', 'Unscanned'],
              ['scanned', 'Scanned'],
              ['has_matches', 'Matches'],
              ['has_unreviewed', 'Needs Review'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => onStatusFilterChange(key)}
              className={`px-2.5 py-1 rounded text-xs font-medium whitespace-nowrap transition-all ${
                statusFilter === key
                  ? 'bg-carbon-800 text-white shadow-xs'
                  : 'text-carbon-400 hover:text-carbon-200 hover:bg-carbon-900'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Right: Density toggle & Selection count */}
      <div className="flex items-center gap-3 shrink-0">
        {/* Density Toggle */}
        <div className="flex items-center bg-carbon-950 p-0.5 rounded-md border border-carbon-800 text-carbon-400">
          <button
            onClick={() => onDensityChange('standard')}
            title="Standard Grid"
            className={`p-1 rounded ${density === 'standard' ? 'bg-carbon-800 text-white' : 'hover:text-carbon-200'}`}
          >
            <LayoutGrid className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => onDensityChange('compact')}
            title="Compact Grid"
            className={`p-1 rounded ${density === 'compact' ? 'bg-carbon-800 text-white' : 'hover:text-carbon-200'}`}
          >
            <Grid className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Direct Scan Trigger */}
        <button
          onClick={onScanClicked}
          disabled={selectedCount === 0 || preparingScan}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold shadow-sm transition-all ${
            selectedCount === 0 || preparingScan
              ? 'bg-carbon-800 text-carbon-500 cursor-not-allowed border border-carbon-800'
              : 'bg-accent-600 hover:bg-accent-500 text-white shadow-accent-600/20 active:scale-98'
          }`}
        >
          {activeProvider === 'mock' ? (
            <Sparkles className="w-3.5 h-3.5 text-amber-300" />
          ) : (
            <ShieldAlert className="w-3.5 h-3.5 text-white" />
          )}
          <span>Scan Selected ({selectedCount})</span>
        </button>
      </div>
    </div>
  );
};
