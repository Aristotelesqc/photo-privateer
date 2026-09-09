import React, { useState } from 'react';
import {
  FolderPlus,
  Trash2,
  RefreshCw,
  FolderCheck,
  ShieldCheck,
  Sparkles,
  Key,
  Check,
  AlertCircle,
  Save,
  CheckCircle2,
  FolderOpen,
} from 'lucide-react';
import { Library, AppSettings } from '../types';
import {
  createLibrary,
  updateLibrary,
  deleteLibrary,
  indexLibrary,
  updateSettings,
  validateFolder,
  browseFolder,
} from '../api/client';

interface SettingsViewProps {
  libraries: Library[];
  settings: AppSettings | null;
  onRefreshData: () => void;
}

export const SettingsView: React.FC<SettingsViewProps> = ({
  libraries,
  settings,
  onRefreshData,
}) => {
  // Add folder state
  const [newFolderPath, setNewFolderPath] = useState('');
  const [newFolderName, setNewFolderName] = useState('');
  const [isRecursive, setIsRecursive] = useState(true);
  const [validatingPath, setValidatingPath] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    error: string | null;
  } | null>(null);
  const [addingFolder, setAddingFolder] = useState(false);

  // Indexing in progress per library
  const [indexingLibId, setIndexingLibId] = useState<number | null>(null);
  const [indexFeedback, setIndexFeedback] = useState<{ [id: number]: string }>({});

  // Settings form state
  const [activeProvider, setActiveProvider] = useState<'mock' | 'google_vision'>(
    settings?.active_provider || 'mock'
  );
  const [credsPath, setCredsPath] = useState(settings?.google_credentials_path || '');
  const [freeTierUnits, setFreeTierUnits] = useState(settings?.free_tier_monthly_units ?? 1000);
  const [blockOnGuard, setBlockOnGuard] = useState(settings?.block_on_free_tier_exceeded ?? true);
  const [unitPrice, setUnitPrice] = useState(settings?.unit_price_usd ?? 0.0035);
  const [savingSettings, setSavingSettings] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [browsingFolder, setBrowsingFolder] = useState(false);

  React.useEffect(() => {
    if (settings) {
      setActiveProvider(settings.active_provider);
      setCredsPath(settings.google_credentials_path || '');
      setFreeTierUnits(settings.free_tier_monthly_units);
      setBlockOnGuard(settings.block_on_free_tier_exceeded);
      setUnitPrice(settings.unit_price_usd);
    }
  }, [settings]);

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
    } catch (err: any) {
      setValidationResult({ valid: false, error: err.message });
    } finally {
      setValidatingPath(false);
    }
  };

  const handleAddLibrary = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newFolderPath.trim()) return;
    setAddingFolder(true);
    try {
      const lib = await createLibrary(
        newFolderPath.trim(),
        newFolderName.trim() || undefined,
        isRecursive
      );
      setNewFolderPath('');
      setNewFolderName('');
      setValidationResult(null);
      onRefreshData();
      handleIndexLibrary(lib.id);
    } catch (err: any) {
      alert(`Failed adding library: ${err.message}`);
    } finally {
      setAddingFolder(false);
    }
  };

  const handleIndexLibrary = async (libId: number) => {
    setIndexingLibId(libId);
    setIndexFeedback((prev) => ({ ...prev, [libId]: 'Indexing...' }));
    try {
      const res = await indexLibrary(libId);
      setIndexFeedback((prev) => ({
        ...prev,
        [libId]: `Indexed: ${res.results.added_or_updated} updated, ${res.results.unchanged} unchanged`,
      }));
      onRefreshData();
    } catch (err: any) {
      setIndexFeedback((prev) => ({ ...prev, [libId]: `Error: ${err.message}` }));
    } finally {
      setIndexingLibId(null);
    }
  };

  const handleDeleteLibrary = async (libId: number) => {
    if (!confirm('Remove this folder from Photo Privateer? Source files on disk will NOT be touched.')) {
      return;
    }
    try {
      await deleteLibrary(libId);
      onRefreshData();
    } catch (err: any) {
      alert(`Failed removing library: ${err.message}`);
    }
  };

  const handleToggleRecursive = async (lib: Library) => {
    try {
      await updateLibrary(lib.id, { recursive: !lib.recursive });
      onRefreshData();
    } catch (err: any) {
      alert(`Update failed: ${err.message}`);
    }
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingSettings(true);
    setSaveSuccess(false);
    try {
      await updateSettings({
        active_provider: activeProvider,
        google_credentials_path: credsPath.trim() || undefined,
        free_tier_monthly_units: Number(freeTierUnits),
        block_on_free_tier_exceeded: blockOnGuard,
        unit_price_usd: Number(unitPrice),
      });
      setSaveSuccess(true);
      onRefreshData();
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err: any) {
      alert(`Failed updating settings: ${err.message}`);
    } finally {
      setSavingSettings(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-6 text-xs">
      {/* 1. Folder Management */}
      <section className="bg-carbon-900 border border-carbon-800 rounded-lg p-4 space-y-4">
        <div>
          <h3 className="font-semibold text-white flex items-center gap-1.5 text-sm">
            <FolderCheck className="w-4 h-4 text-accent-500" />
            <span>Monitored Photograph Folders</span>
          </h3>
          <p className="text-carbon-400 mt-0.5">
            Filesystem access is strictly read-only. Your photographs are never modified, moved, or deleted.
          </p>
        </div>

        {/* Existing Libraries */}
        {libraries.length > 0 && (
          <div className="space-y-2">
            {libraries.map((lib) => (
              <div
                key={lib.id}
                className="bg-carbon-950 border border-carbon-800 rounded-md p-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5"
              >
                <div className="min-w-0 flex-1 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-white">{lib.name}</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-carbon-800 text-carbon-300 tabular-nums">
                      {lib.image_count} photos
                    </span>
                  </div>
                  <p className="font-mono text-carbon-400 truncate text-[11px]" title={lib.path}>
                    {lib.path}
                  </p>
                  <div className="flex items-center gap-3 text-[10px] text-carbon-500 pt-0.5">
                    <label className="flex items-center gap-1 cursor-pointer text-carbon-300">
                      <input
                        type="checkbox"
                        checked={lib.recursive}
                        onChange={() => handleToggleRecursive(lib)}
                        className="rounded bg-carbon-900 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3 h-3"
                      />
                      <span>Recursive subfolders</span>
                    </label>
                    {lib.last_indexed_at && (
                      <span className="tabular-nums">Indexed: {new Date(lib.last_indexed_at).toLocaleDateString()}</span>
                    )}
                  </div>
                  {indexFeedback[lib.id] && (
                    <p className="text-[10px] text-accent-400 font-mono pt-0.5">{indexFeedback[lib.id]}</p>
                  )}
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => handleIndexLibrary(lib.id)}
                    disabled={indexingLibId === lib.id}
                    className="flex items-center gap-1 px-2.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-carbon-200 hover:text-white transition-colors text-xs"
                  >
                    <RefreshCw className={`w-3 h-3 ${indexingLibId === lib.id ? 'animate-spin' : ''}`} />
                    <span>{indexingLibId === lib.id ? 'Indexing...' : 'Index'}</span>
                  </button>
                  <button
                    onClick={() => handleDeleteLibrary(lib.id)}
                    className="p-1 rounded text-carbon-400 hover:text-rose-400 hover:bg-carbon-800 transition-colors"
                    title="Remove folder"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Add Folder Form */}
        <form onSubmit={handleAddLibrary} className="bg-carbon-950 border border-carbon-800 rounded-md p-3 space-y-2.5">
          <span className="font-semibold text-carbon-200 block text-xs">Add New Local Folder</span>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            <div className="sm:col-span-2 space-y-1">
              <label className="block text-carbon-400 text-[11px]">Folder Path</label>
              <div className="flex gap-1.5">
                <input
                  type="text"
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
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="e.g. Landscapes"
                className="w-full bg-carbon-900 border border-carbon-800 rounded px-2.5 py-1 text-white text-xs focus:outline-none focus:border-accent-500"
              />
            </div>
          </div>

          <div className="flex items-center justify-between gap-2 pt-1">
            <label className="flex items-center gap-1.5 text-carbon-300 cursor-pointer">
              <input
                type="checkbox"
                checked={isRecursive}
                onChange={(e) => setIsRecursive(e.target.checked)}
                className="rounded bg-carbon-900 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
              />
              <span>Include subfolders</span>
            </label>

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
      </section>

      {/* 2. Provider Selection & Google Vision Setup */}
      <section className="bg-carbon-900 border border-carbon-800 rounded-lg p-4 space-y-4">
        <div>
          <h3 className="font-semibold text-white flex items-center gap-1.5 text-sm">
            <Key className="w-4 h-4 text-accent-500" />
            <span>Search Provider & Authentication</span>
          </h3>
          <p className="text-carbon-400 mt-0.5">
            Switch between deterministic offline mock testing and live Google Cloud Vision Web Detection.
          </p>
        </div>

        <form onSubmit={handleSaveSettings} className="space-y-4">
          {/* Provider Radios */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            {/* Mock */}
            <div
              onClick={() => setActiveProvider('mock')}
              className={`p-3 rounded-md border cursor-pointer transition-all ${
                activeProvider === 'mock'
                  ? 'bg-amber-500/10 border-amber-500/40 text-amber-200 ring-1 ring-amber-500/30'
                  : 'bg-carbon-950 border-carbon-800 text-carbon-400 hover:text-white'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-semibold text-white text-xs flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                  Mock / Demo Provider
                </span>
                <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300">
                  Offline
                </span>
              </div>
              <p className="text-[11px] leading-snug">
                Deterministic sample results. Offline, $0 cost, zero Google API quota consumed.
              </p>
            </div>

            {/* Google Vision */}
            <div
              onClick={() => setActiveProvider('google_vision')}
              className={`p-3 rounded-md border cursor-pointer transition-all ${
                activeProvider === 'google_vision'
                  ? 'bg-accent-500/10 border-accent-500/40 text-accent-200 ring-1 ring-accent-500/30'
                  : 'bg-carbon-950 border-carbon-800 text-carbon-400 hover:text-white'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-semibold text-white text-xs flex items-center gap-1.5">
                  <ShieldCheck className="w-3.5 h-3.5 text-accent-400" />
                  Google Cloud Vision
                </span>
                <span className="text-[9px] font-mono px-1.5 py-0.2 rounded bg-accent-500/20 text-accent-300">
                  Production
                </span>
              </div>
              <p className="text-[11px] leading-snug">
                Official Cloud Vision Web Detection API querying public web discoveries.
              </p>
            </div>
          </div>

          {/* Credentials Path Input */}
          <div className="bg-carbon-950 border border-carbon-800 rounded-md p-3 space-y-2">
            <div className="flex items-center justify-between">
              <label className="font-semibold text-white text-xs">Service Account Key (JSON Path)</label>
              {settings?.google_credentials_valid ? (
                <span className="flex items-center gap-1 text-emerald-400 font-mono text-[10px]">
                  <Check className="w-3 h-3" />
                  <span>Valid Key</span>
                </span>
              ) : (
                <span className="flex items-center gap-1 text-amber-400 font-mono text-[10px]">
                  <AlertCircle className="w-3 h-3" />
                  <span>{settings?.google_credentials_error || 'No key configured'}</span>
                </span>
              )}
            </div>

            <input
              type="text"
              value={credsPath}
              onChange={(e) => setCredsPath(e.target.value)}
              placeholder="C:\Users\Username\.secrets\vision-key.json"
              className="w-full bg-carbon-900 border border-carbon-800 rounded px-2.5 py-1 text-white font-mono text-xs focus:outline-none focus:border-accent-500"
            />

            <div className="bg-carbon-900 rounded p-2.5 border border-carbon-800/80 text-[10px] text-carbon-300 space-y-1">
              <span className="font-semibold text-carbon-200">GCP Quick Setup:</span>
              <ol className="list-decimal list-inside space-y-0.5 text-carbon-400 pl-0.5">
                <li>Create GCP project & enable <strong>Cloud Vision API</strong>.</li>
                <li>Under <em>IAM & Service Accounts</em>, create a service account with <em>Cloud Vision User</em>.</li>
                <li>Download JSON key file locally and paste its local absolute path above.</li>
              </ol>
            </div>
          </div>

          {/* Cost & Guard Options */}
          <div className="space-y-3 pt-1 border-t border-carbon-800">
            <span className="font-semibold text-white block text-xs">Usage & Guard Preferences</span>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className="block text-carbon-400 text-[11px] mb-0.5">Free Allowance (Units/mo)</label>
                <input
                  type="number"
                  value={freeTierUnits}
                  onChange={(e) => setFreeTierUnits(Number(e.target.value))}
                  min={0}
                  className="w-full bg-carbon-950 border border-carbon-800 rounded px-2.5 py-1 text-white font-mono text-xs focus:outline-none focus:border-accent-500"
                />
              </div>

              <div>
                <label className="block text-carbon-400 text-[11px] mb-0.5">Price per Unit Beyond Free ($)</label>
                <input
                  type="number"
                  step="0.0001"
                  value={unitPrice}
                  onChange={(e) => setUnitPrice(Number(e.target.value))}
                  min={0}
                  className="w-full bg-carbon-950 border border-carbon-800 rounded px-2.5 py-1 text-white font-mono text-xs focus:outline-none focus:border-accent-500"
                />
              </div>
            </div>

            <label className="flex items-start gap-2 text-carbon-300 cursor-pointer pt-1">
              <input
                type="checkbox"
                checked={blockOnGuard}
                onChange={(e) => setBlockOnGuard(e.target.checked)}
                className="mt-0.5 rounded bg-carbon-950 border-carbon-700 text-accent-600 focus:ring-accent-500 w-3.5 h-3.5"
              />
              <div>
                <span className="font-semibold text-white">Enforce Free-Tier Safety Guard</span>
                <p className="text-[10px] text-carbon-400">
                  Block any scan batch that would exceed your free monthly threshold unless explicitly authorized.
                </p>
              </div>
            </label>
          </div>

          {/* Footer Save */}
          <div className="flex items-center justify-between pt-3 border-t border-carbon-800">
            {saveSuccess ? (
              <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                <CheckCircle2 className="w-3.5 h-3.5" />
                <span>Saved successfully</span>
              </span>
            ) : <span />}

            <button
              type="submit"
              disabled={savingSettings}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded bg-accent-600 hover:bg-accent-500 text-white text-xs font-semibold shadow-xs transition-all active:scale-98"
            >
              <Save className="w-3.5 h-3.5" />
              <span>{savingSettings ? 'Saving...' : 'Save Preferences'}</span>
            </button>
          </div>
        </form>
      </section>
    </div>
  );
};
