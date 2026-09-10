import React, { useState } from 'react';
import { FolderPlus, FolderOpen, Check, AlertCircle } from 'lucide-react';
import { validateFolder, browseFolder } from '../../api/client';

export interface AddFolderSectionProps {
  onAddLibrary: (
    path: string,
    name?: string,
    recursive?: boolean,
    subfoldersAsProjects?: boolean
  ) => Promise<void>;
}

export const AddFolderSection: React.FC<AddFolderSectionProps> = ({ onAddLibrary }) => {
  const [newFolderPath, setNewFolderPath] = useState('');
  const [newFolderName, setNewFolderName] = useState('');
  const [isRecursive, setIsRecursive] = useState(true);
  const [subfoldersAsProjects, setSubfoldersAsProjects] = useState(true);
  const [validatingPath, setValidatingPath] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    error: string | null;
  } | null>(null);
  const [addingFolder, setAddingFolder] = useState(false);
  const [browsingFolder, setBrowsingFolder] = useState(false);

  const handleBrowseFolder = async () => {
    setBrowsingFolder(true);
    try {
      const res = await browseFolder();
      if (res.path) {
        setNewFolderPath(res.path);
        setValidationResult(null);
        const v = await validateFolder(res.path);
        setValidationResult({ valid: v.valid, error: v.error });
        if (v.valid) {
          setNewFolderPath(v.resolved_path);
        }
      }
    } catch (err) {
      console.error('Folder browser error', err);
    } finally {
      setBrowsingFolder(false);
    }
  };

  const handleValidateFolder = async () => {
    if (!newFolderPath.trim()) return;
    setValidatingPath(true);
    setValidationResult(null);
    try {
      const res = await validateFolder(newFolderPath.trim());
      setValidationResult({ valid: res.valid, error: res.error });
      if (res.valid) {
        setNewFolderPath(res.resolved_path);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setValidationResult({ valid: false, error: msg });
    } finally {
      setValidatingPath(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFolderPath.trim()) return;
    setAddingFolder(true);
    try {
      await onAddLibrary(
        newFolderPath.trim(),
        newFolderName.trim() || undefined,
        isRecursive,
        subfoldersAsProjects
      );
      setNewFolderPath('');
      setNewFolderName('');
      setValidationResult(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed adding library: ${msg}`);
    } finally {
      setAddingFolder(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-carbon-950 border border-carbon-800 rounded-md p-3 space-y-2.5">
      <span className="font-semibold text-carbon-200 block text-xs">Add New Local Folder</span>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <div className="sm:col-span-2 space-y-1">
          <label className="block text-carbon-400 text-[11px]">Folder Path</label>
          <div className="flex gap-1.5">
            <input
              type="text"
              data-testid="input-folder-path"
              value={newFolderPath}
              onChange={(e) => {
                setNewFolderPath(e.target.value);
                setValidationResult(null);
              }}
              placeholder="C:\Photos\Portfolio"
              required
              className="flex-1 bg-carbon-900 border border-carbon-800 rounded px-2.5 py-1 text-white font-mono text-xs focus:outline-none focus:border-accent-500"
            />
            <button
              type="button"
              onClick={handleBrowseFolder}
              disabled={browsingFolder}
              className="px-2.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-carbon-200 text-xs shrink-0 font-medium flex items-center gap-1"
              title="Browse local folders on this computer"
            >
              <FolderOpen className="w-3 h-3" />
              <span>{browsingFolder ? 'Browsing...' : 'Browse...'}</span>
            </button>
            <button
              type="button"
              onClick={handleValidateFolder}
              disabled={validatingPath || !newFolderPath.trim()}
              className="px-2.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-carbon-200 text-xs shrink-0 font-medium"
            >
              {validatingPath ? 'Checking...' : 'Check'}
            </button>
          </div>
          {validationResult && (
            <div
              className={`text-[10px] flex items-center gap-1 ${
                validationResult.valid ? 'text-emerald-400' : 'text-rose-400'
              }`}
            >
              {validationResult.valid ? (
                <>
                  <Check className="w-3 h-3" />
                  <span>Valid directory</span>
                </>
              ) : (
                <>
                  <AlertCircle className="w-3 h-3" />
                  <span>{validationResult.error || 'Invalid path'}</span>
                </>
              )}
            </div>
          )}
        </div>

        <div className="space-y-1">
          <label className="block text-carbon-400 text-[11px]">Label (Optional)</label>
          <input
            type="text"
            data-testid="input-folder-name"
            value={newFolderName}
            onChange={(e) => setNewFolderName(e.target.value)}
            placeholder="e.g. Landscapes"
            className="w-full bg-carbon-900 border border-carbon-800 rounded px-2.5 py-1 text-white text-xs focus:outline-none focus:border-accent-500"
          />
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-1.5 text-carbon-300 cursor-pointer">
            <input
              type="checkbox"
              checked={isRecursive}
              onChange={(e) => setIsRecursive(e.target.checked)}
              className="rounded bg-carbon-900 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
            />
            <span>Include subfolders</span>
          </label>
          <label className="flex items-center gap-1.5 text-carbon-300 cursor-pointer">
            <input
              type="checkbox"
              checked={subfoldersAsProjects}
              onChange={(e) => setSubfoldersAsProjects(e.target.checked)}
              className="rounded bg-carbon-900 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
            />
            <span>Subfolders as projects</span>
          </label>
        </div>

        <button
          type="submit"
          disabled={addingFolder || !newFolderPath.trim()}
          className="flex items-center gap-1.5 px-3 py-1 rounded bg-accent-600 hover:bg-accent-500 text-white font-semibold shadow-xs transition-all active:scale-98"
        >
          <FolderPlus className="w-3.5 h-3.5" />
          <span>{addingFolder ? 'Adding...' : 'Add & Index'}</span>
        </button>
      </div>
    </form>
  );
};
