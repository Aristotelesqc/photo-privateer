import React from 'react';
import { RefreshCw, Trash2 } from 'lucide-react';
import { Library } from '../../types';

export interface MonitoredFolderCardProps {
  library: Library;
  isIndexing: boolean;
  isDetectingProjects: boolean;
  feedback?: string;
  onToggleRecursive: (lib: Library) => void;
  onToggleSubfoldersAsProjects: (lib: Library) => void;
  onIndex: (libId: number) => void;
  onDetectProjects: (libId: number) => void;
  onUnarchive: (libId: number) => void;
  onDelete: (libId: number, isArchived: boolean) => void;
}

export const MonitoredFolderCard: React.FC<MonitoredFolderCardProps> = ({
  library: lib,
  isIndexing,
  isDetectingProjects,
  feedback,
  onToggleRecursive,
  onToggleSubfoldersAsProjects,
  onIndex,
  onDetectProjects,
  onUnarchive,
  onDelete,
}) => {
  return (
    <div
      data-testid="library-item"
      className="bg-carbon-950 border border-carbon-800 rounded-md p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5"
    >
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-white">{lib.name}</span>
          <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-carbon-800 text-carbon-300 tabular-nums">
            {lib.image_count} photos
          </span>
          {lib.is_archived && (
            <span
              data-testid="badge-archived"
              className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30"
            >
              Archived (Monitoring Paused)
            </span>
          )}
        </div>
        <p className="font-mono text-carbon-400 truncate text-[11px]" title={lib.path}>
          {lib.path}
        </p>
        <div className="flex items-center gap-3 text-[10px] text-carbon-500 pt-0.5">
          {!lib.is_archived && (
            <>
              <label className="flex items-center gap-1 cursor-pointer text-carbon-300">
                <input
                  type="checkbox"
                  checked={lib.recursive}
                  onChange={() => onToggleRecursive(lib)}
                  className="rounded bg-carbon-900 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3 h-3"
                />
                <span>Recursive subfolders</span>
              </label>
              <label className="flex items-center gap-1 cursor-pointer text-carbon-300">
                <input
                  type="checkbox"
                  checked={lib.subfolders_as_projects}
                  onChange={() => onToggleSubfoldersAsProjects(lib)}
                  className="rounded bg-carbon-900 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3 h-3"
                />
                <span>Subfolders as projects</span>
              </label>
            </>
          )}
          {lib.last_indexed_at && (
            <span className="tabular-nums">Indexed: {new Date(lib.last_indexed_at).toLocaleDateString()}</span>
          )}
        </div>
        {feedback && (
          <p className="text-[10px] text-accent-400 font-mono pt-0.5">{feedback}</p>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {!lib.is_archived ? (
          <>
            <button
              type="button"
              onClick={() => onIndex(lib.id)}
              disabled={isIndexing}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-carbon-200 hover:text-white transition-colors text-xs"
            >
              <RefreshCw className={`w-3 h-3 ${isIndexing ? 'animate-spin' : ''}`} />
              <span>{isIndexing ? 'Indexing...' : 'Index'}</span>
            </button>
            <button
              type="button"
              onClick={() => onDetectProjects(lib.id)}
              disabled={isDetectingProjects}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-carbon-200 hover:text-white transition-colors text-xs"
              title="Auto-detect immediate subfolders as project names for all photos in this folder"
            >
              <span>{isDetectingProjects ? 'Detecting...' : 'Detect Projects'}</span>
            </button>
            <button
              type="button"
              data-testid="btn-stop-monitoring"
              onClick={() => onDelete(lib.id, false)}
              className="px-2 py-1 rounded text-carbon-400 hover:text-amber-300 hover:bg-carbon-800 border border-carbon-800 transition-colors text-[11px]"
              title="Stop monitoring this folder (preserves all discovered matches)"
            >
              Stop Monitoring
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              data-testid="btn-resume-monitoring"
              onClick={() => onUnarchive(lib.id)}
              className="flex items-center gap-1 px-2.5 py-1 rounded bg-accent-600 hover:bg-accent-500 text-white transition-colors text-xs font-semibold"
            >
              Resume Monitoring
            </button>
            <button
              type="button"
              onClick={() => onDelete(lib.id, true)}
              className="p-1 rounded text-carbon-500 hover:text-rose-400 hover:bg-carbon-800 transition-colors"
              title="Permanently remove from database (original files on disk are never touched)"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </>
        )}
      </div>
    </div>
  );
};
