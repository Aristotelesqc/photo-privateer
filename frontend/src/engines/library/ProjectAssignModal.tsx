import React, { useState } from 'react';
import { Tag, X } from 'lucide-react';

export interface ProjectAssignModalProps {
  isOpen: boolean;
  selectedCount: number;
  projects: string[];
  onClose: () => void;
  onAssign: (projectName: string | null) => Promise<void>;
}

export const ProjectAssignModal: React.FC<ProjectAssignModalProps> = ({
  isOpen,
  selectedCount,
  projects,
  onClose,
  onAssign,
}) => {
  const [projectInput, setProjectInput] = useState('');
  const [assigningProject, setAssigningProject] = useState(false);

  if (!isOpen) return null;

  const handleClear = async () => {
    setAssigningProject(true);
    try {
      await onAssign(null);
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to clear project: ${msg}`);
    } finally {
      setAssigningProject(false);
    }
  };

  const handleApply = async () => {
    if (!projectInput.trim()) return;
    setAssigningProject(true);
    try {
      await onAssign(projectInput.trim());
      onClose();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to assign project: ${msg}`);
    } finally {
      setAssigningProject(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-xs">
      <div className="bg-carbon-900 border border-carbon-800 rounded-xl max-w-md w-full p-5 shadow-2xl space-y-4">
        <div className="flex items-center justify-between border-b border-carbon-800 pb-3">
          <div className="flex items-center gap-2">
            <Tag className="w-4 h-4 text-accent-400" />
            <h3 className="text-sm font-semibold text-white">
              Assign Project ({selectedCount} photo{selectedCount > 1 ? 's' : ''})
            </h3>
          </div>
          <button
            onClick={onClose}
            className="text-carbon-400 hover:text-white p-1 rounded"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs text-carbon-400">
          Group photos under a project name for filtering and organization. Enter a new name or choose an existing project.
        </p>

        {/* Quick-pick existing projects */}
        {projects.length > 0 && (
          <div className="space-y-1.5">
            <span className="text-[11px] font-medium text-carbon-400">Existing Projects:</span>
            <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto p-1 bg-carbon-950/60 rounded-lg border border-carbon-800/80">
              {projects.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setProjectInput(p)}
                  className={`text-xs px-2 py-0.5 rounded border transition-colors ${
                    projectInput === p
                      ? 'bg-accent-600/30 border-accent-500 text-accent-300 font-semibold'
                      : 'bg-carbon-900 border-carbon-800 text-carbon-300 hover:bg-carbon-800'
                  }`}
                >
                  📁 {p}
                </button>
              ))}
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs font-medium text-carbon-300 mb-1">
            Project Name
          </label>
          <input
            type="text"
            value={projectInput}
            onChange={(e) => setProjectInput(e.target.value)}
            placeholder="e.g. Wedding 2026, Summer Campaign..."
            className="w-full bg-carbon-950 border border-carbon-800 rounded-md px-3 py-2 text-xs text-white placeholder-carbon-500 focus:outline-none focus:border-accent-500 font-medium"
            autoFocus
          />
        </div>

        <div className="flex items-center justify-between pt-2 border-t border-carbon-800">
          <button
            type="button"
            onClick={handleClear}
            disabled={assigningProject}
            className="px-3 py-1.5 rounded-lg border border-carbon-800 text-xs font-medium text-carbon-400 hover:text-red-400 hover:border-red-900/50 hover:bg-red-950/20 transition-all"
          >
            Clear Project
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={assigningProject}
              className="px-3 py-1.5 rounded-lg bg-carbon-800 hover:bg-carbon-750 text-xs font-medium text-carbon-300"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleApply}
              disabled={assigningProject || !projectInput.trim()}
              className="px-4 py-1.5 rounded-lg bg-accent-600 hover:bg-accent-500 disabled:opacity-40 disabled:cursor-not-allowed text-xs font-semibold text-white shadow-sm transition-all"
            >
              {assigningProject ? 'Saving...' : 'Apply Project'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
