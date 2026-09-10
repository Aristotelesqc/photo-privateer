import React from 'react';
import { Search } from 'lucide-react';
import { ClassificationType } from '../../types';
import { FilterSelect } from '../../components/blocks/FilterSelect';

export interface ReviewFilterBarProps {
  activeClassification: ClassificationType | 'ALL';
  onClassificationChange: (classification: ClassificationType | 'ALL') => void;
  projects: string[];
  selectedProject?: string;
  onProjectChange: (project?: string) => void;
  searchQuery: string;
  onSearchChange: (search: string) => void;
  isNewOnly: boolean;
  onNewOnlyChange: (newOnly: boolean) => void;
}

export const ReviewFilterBar: React.FC<ReviewFilterBarProps> = ({
  activeClassification,
  onClassificationChange,
  projects,
  selectedProject,
  onProjectChange,
  searchQuery,
  onSearchChange,
  isNewOnly,
  onNewOnlyChange,
}) => {
  return (
    <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
      {/* Classification Tabs */}
      <div className="flex items-center gap-0.5 bg-carbon-950 p-0.5 rounded-md border border-carbon-800 overflow-x-auto">
        {(
          [
            ['UNREVIEWED', 'Needs Review'],
            ['ALL', 'All'],
            ['APPROVED', 'Approved'],
            ['UNAUTHORIZED', 'Infringing'],
            ['IRRELEVANT', 'Irrelevant'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => onClassificationChange(key)}
            className={`px-3 py-1 rounded text-xs font-medium whitespace-nowrap transition-all ${
              activeClassification === key
                ? 'bg-carbon-800 text-white shadow-xs'
                : 'text-carbon-400 hover:text-carbon-200 hover:bg-carbon-900'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Search & Filters */}
      <div className="flex flex-wrap items-center gap-2.5">
        {/* Project Select */}
        <FilterSelect
          value={selectedProject ?? ''}
          onChange={(e) => onProjectChange(e.target.value || undefined)}
          className="py-1"
        >
          <option value="">All Projects</option>
          <option value="__unassigned__">No Project (Unassigned)</option>
          {projects.map((proj) => (
            <option key={proj} value={proj}>
              📁 {proj}
            </option>
          ))}
        </FilterSelect>

        <div className="relative w-44 sm:w-56">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-carbon-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search domain or title..."
            className="w-full bg-carbon-950 border border-carbon-800 rounded-md pl-8 pr-2.5 py-1 text-xs text-white placeholder-carbon-500 focus:outline-none focus:border-accent-500"
          />
        </div>

        <label className="flex items-center gap-1.5 text-xs text-carbon-300 font-medium cursor-pointer shrink-0">
          <input
            type="checkbox"
            checked={isNewOnly}
            onChange={(e) => onNewOnlyChange(e.target.checked)}
            className="rounded bg-carbon-950 border-carbon-800 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
          />
          <span>New Only</span>
        </label>
      </div>
    </div>
  );
};
