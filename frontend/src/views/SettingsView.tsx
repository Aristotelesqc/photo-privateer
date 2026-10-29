import React, { useState } from 'react';
import {
  FolderCheck,
  ShieldCheck,
  Sparkles,
  Key,
  Check,
  AlertCircle,
  Save,
  CheckCircle2,
  HelpCircle,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Filter,
  Trash2,
  Plus,
} from 'lucide-react';
import { Library, AppSettings, DomainRule, ClassificationType } from '../types';
import {
  createLibrary,
  updateLibrary,
  deleteLibrary,
  archiveLibrary,
  unarchiveLibrary,
  indexLibrary,
  detectLibraryProjects,
  updateSettings,
  testGoogleAuth,
  fetchRules,
  createRule,
  deleteRule,
} from '../api/client';
import { MonitoredFolderCard } from '../engines/settings/MonitoredFolderCard';
import { AddFolderSection } from '../engines/settings/AddFolderSection';
import { DomainRuleModal } from '../components/DomainRuleModal';

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
  // Indexing in progress per library
  const [indexingLibId, setIndexingLibId] = useState<number | null>(null);
  const [detectingProjectsLibId, setDetectingProjectsLibId] = useState<number | null>(null);
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
  const [testingAuth, setTestingAuth] = useState(false);
  const [testAuthResult, setTestAuthResult] = useState<{
    success: boolean;
    auth_mode: string;
    message?: string | null;
    error?: string | null;
    project_id?: string | null;
    service_account_email?: string | null;
  } | null>(null);
  const [showApiGuide, setShowApiGuide] = useState(false);

  // Domain rules management state
  const [domainRules, setDomainRules] = useState<DomainRule[]>([]);
  const [ruleModalOpen, setRuleModalOpen] = useState(false);

  const loadRules = async () => {
    try {
      const rules = await fetchRules();
      setDomainRules(rules);
    } catch (err) {
      console.error('Failed loading domain rules', err);
    }
  };

  React.useEffect(() => {
    loadRules();
  }, []);

  React.useEffect(() => {
    if (settings) {
      setActiveProvider(settings.active_provider);
      setCredsPath(settings.google_credentials_path || '');
      setFreeTierUnits(settings.free_tier_monthly_units);
      setBlockOnGuard(settings.block_on_free_tier_exceeded);
      setUnitPrice(settings.unit_price_usd);
    }
  }, [settings]);

  const handleAddLibrary = async (
    path: string,
    name?: string,
    recursive?: boolean,
    subfoldersAsProjects?: boolean
  ) => {
    const lib = await createLibrary(path, name, recursive, subfoldersAsProjects);
    onRefreshData();
    handleIndexLibrary(lib.id);
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
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setIndexFeedback((prev) => ({ ...prev, [libId]: `Error: ${msg}` }));
    } finally {
      setIndexingLibId(null);
    }
  };

  const handleArchiveLibrary = async (libId: number) => {
    try {
      await archiveLibrary(libId);
      await onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to stop monitoring folder: ${msg}`);
    }
  };

  const handleUnarchiveLibrary = async (libId: number) => {
    try {
      await unarchiveLibrary(libId);
      await onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to resume monitoring folder: ${msg}`);
    }
  };

  const handleDeleteLibrary = async (libId: number, isArchived: boolean) => {
    if (!isArchived) {
      // Default to non-destructive archiving
      if (confirm('Stop monitoring this folder? All historical photos, scans, and discovered matches will be safely preserved in your database.')) {
        await handleArchiveLibrary(libId);
      }
      return;
    }

    // Explicit permanent removal from database if already archived
    if (!confirm('Permanently remove this folder and its associated photo records from Photo Privateer? Original files on disk will NOT be touched.')) {
      return;
    }
    try {
      await deleteLibrary(libId, true);
      onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed removing library: ${msg}`);
    }
  };

  const handleTestAuth = async () => {
    setTestingAuth(true);
    setTestAuthResult(null);
    try {
      const res = await testGoogleAuth(credsPath.trim() || undefined);
      setTestAuthResult(res);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setTestAuthResult({
        success: false,
        auth_mode: 'none',
        error: msg,
      });
    } finally {
      setTestingAuth(false);
    }
  };

  const handleToggleRecursive = async (lib: Library) => {
    try {
      await updateLibrary(lib.id, { recursive: !lib.recursive });
      onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Update failed: ${msg}`);
    }
  };

  const handleToggleSubfoldersAsProjects = async (lib: Library) => {
    try {
      await updateLibrary(lib.id, { subfolders_as_projects: !lib.subfolders_as_projects });
      onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Update failed: ${msg}`);
    }
  };

  const handleDetectProjects = async (libId: number) => {
    setDetectingProjectsLibId(libId);
    setIndexFeedback((prev) => ({ ...prev, [libId]: 'Detecting projects...' }));
    try {
      const res = await detectLibraryProjects(libId);
      setIndexFeedback((prev) => ({
        ...prev,
        [libId]: `Projects auto-detected: ${res.updated_count} photo(s) assigned`,
      }));
      onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setIndexFeedback((prev) => ({ ...prev, [libId]: `Error: ${msg}` }));
    } finally {
      setDetectingProjectsLibId(null);
    }
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingSettings(true);
    setSaveSuccess(false);
    try {
      await updateSettings({
        active_provider: activeProvider,
        google_credentials_path: credsPath.trim() === '' ? null : credsPath.trim(),
        free_tier_monthly_units: Number(freeTierUnits),

        block_on_free_tier_exceeded: blockOnGuard,
        unit_price_usd: Number(unitPrice),
      });
      setSaveSuccess(true);
      onRefreshData();
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed updating settings: ${msg}`);
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
              <MonitoredFolderCard
                key={lib.id}
                library={lib}
                isIndexing={indexingLibId === lib.id}
                isDetectingProjects={detectingProjectsLibId === lib.id}
                feedback={indexFeedback[lib.id]}
                onToggleRecursive={handleToggleRecursive}
                onToggleSubfoldersAsProjects={handleToggleSubfoldersAsProjects}
                onIndex={handleIndexLibrary}
                onDetectProjects={handleDetectProjects}
                onUnarchive={handleUnarchiveLibrary}
                onDelete={handleDeleteLibrary}
              />
            ))}
          </div>
        )}

        {/* Add Folder Form */}
        <AddFolderSection onAddLibrary={handleAddLibrary} />
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
          <div className="bg-carbon-950 border border-carbon-800 rounded-md p-3 space-y-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <label className="font-semibold text-white text-xs">Google Cloud Authentication</label>
              <div className="flex items-center gap-2">
                {settings?.auth_mode === 'service_account' ? (
                  <span className="flex items-center gap-1 text-emerald-400 font-mono text-[10px] bg-emerald-500/10 px-1.5 py-0.5 rounded border border-emerald-500/20">
                    <Check className="w-3 h-3" />
                    <span>Key Configured</span>
                  </span>
                ) : settings?.auth_mode === 'adc' ? (
                  <span className="flex items-center gap-1 text-accent-300 font-mono text-[10px] bg-accent-500/10 px-1.5 py-0.5 rounded border border-accent-500/20">
                    <Check className="w-3 h-3" />
                    <span>ADC Active</span>
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-amber-400 font-mono text-[10px] bg-amber-500/10 px-1.5 py-0.5 rounded border border-amber-500/20">
                    <AlertCircle className="w-3 h-3" />
                    <span>No credentials configured</span>
                  </span>
                )}
              </div>
            </div>

            {/* ADC Notification Card if available on environment */}
            {settings?.adc_available && (
              <div className="bg-carbon-900 border border-carbon-800 rounded p-2.5 text-[11px] text-carbon-300 flex items-start gap-2">
                <ShieldCheck className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-white">Application Default Credentials (ADC) detected.</span>
                  {settings.adc_project_id && (
                    <span className="font-mono text-carbon-400"> (project: {settings.adc_project_id})</span>
                  )}
                  <p className="text-carbon-400 text-[10px] mt-0.5">
                    Google Cloud Vision can authenticate via your local gcloud CLI session without entering an explicit service account key path below.
                  </p>
                </div>
              </div>
            )}

            <div className="space-y-1">
              <label className="block text-carbon-400 text-[11px]">Service Account Key File (Optional if ADC is configured)</label>
              <input
                type="text"
                value={credsPath}
                onChange={(e) => setCredsPath(e.target.value)}
                placeholder="C:\Users\Username\.secrets\vision-key.json"
                className="w-full bg-carbon-900 border border-carbon-800 rounded px-2.5 py-1 text-white font-mono text-xs focus:outline-none focus:border-accent-500"
              />
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
              <button
                type="button"
                onClick={handleTestAuth}
                disabled={testingAuth}
                className="px-2.5 py-1 rounded bg-carbon-800 hover:bg-carbon-700 text-carbon-200 text-xs font-medium flex items-center gap-1.5 transition-all active:scale-98"
              >
                <Key className="w-3 h-3 text-accent-400" />
                <span>{testingAuth ? 'Testing Auth Token...' : 'Test Authentication (0 Units)'}</span>
              </button>

              <span className="text-[10px] font-mono text-carbon-500">
                Tests auth token acquisition without making Vision API calls.
              </span>
            </div>

            {/* Test Auth Result Banner */}
            {testAuthResult && (
              <div
                className={`p-2.5 rounded border text-[11px] flex items-start gap-2 ${
                  testAuthResult.success
                    ? 'bg-emerald-950/40 border-emerald-800 text-emerald-300'
                    : 'bg-rose-950/40 border-rose-800 text-rose-300'
                }`}
              >
                {testAuthResult.success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                )}
                <div>
                  <p className="font-semibold">{testAuthResult.success ? 'Authentication Succeeded' : 'Authentication Failed'}</p>
                  <p className="text-[10px] opacity-90 mt-0.5">
                    {testAuthResult.message || testAuthResult.error}
                  </p>
                </div>
              </div>
            )}

            {/* API Setup Help Section */}
            <div className="bg-carbon-900 rounded-md border border-carbon-800 overflow-hidden" data-testid="api-setup-guide">
              <button
                type="button"
                data-testid="btn-toggle-api-guide"
                onClick={() => setShowApiGuide(!showApiGuide)}
                className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-carbon-850 transition-colors text-xs font-medium text-carbon-200"
              >
                <span className="flex items-center gap-2">
                  <HelpCircle className="w-4 h-4 text-accent-400 shrink-0" />
                  <span className="font-semibold text-white">Setup Guide: Configuring Google Cloud Vision API</span>
                </span>
                <span className="flex items-center gap-1 text-[11px] text-accent-400 font-mono">
                  <span>{showApiGuide ? 'Hide guide' : 'Show step-by-step guide'}</span>
                  {showApiGuide ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </span>
              </button>

              {showApiGuide && (
                <div className="p-3.5 pt-1 space-y-3 border-t border-carbon-800 text-[11px] text-carbon-300">
                  <p className="text-carbon-300 leading-relaxed text-[11px]">
                    Photo Privateer uses the official <strong>Google Cloud Vision (Web Detection)</strong> API to discover public web reuse of your photographs. Follow these steps to configure access:
                  </p>

                  <div className="space-y-2.5">
                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">1</span>
                        <span>Create a Google Cloud Project</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5">
                        Open the <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer" className="text-accent-400 underline inline-flex items-center gap-0.5">Google Cloud Console <ExternalLink className="w-2.5 h-2.5" /></a>, sign in with your Google account, and create a project (e.g., <em>photo-privateer</em>).
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">2</span>
                        <span>Enable the Cloud Vision API</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5">
                        Navigate to <strong>APIs &amp; Services &gt; Library</strong>, search for <code>Cloud Vision API</code>, and click <strong>Enable</strong>.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">3</span>
                        <span>Create a Service Account</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5">
                        Open <strong>IAM &amp; Admin &gt; Service Accounts</strong>, click <strong>Create Service Account</strong> (e.g., <em>photo-privateer-app</em>), and grant the <strong>Cloud Vision User</strong> role.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">4</span>
                        <span>Download the Private JSON Key &amp; Store Locally</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5 leading-relaxed">
                        Open the service account, go to <strong>Keys &gt; Add Key &gt; Create new key</strong>, and choose <strong>JSON</strong>. Save the file in a private local folder (e.g., <code>C:\Users\YourName\.secrets\vision-key.json</code>) and paste its full path into the field above.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-emerald-500/20 text-emerald-300 flex items-center justify-center text-[10px] font-mono">5</span>
                        <span>Keyless Alternative: Application Default Credentials (ADC)</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5 leading-relaxed">
                        If you have the Google Cloud SDK (<code>gcloud</code>) installed, run <code>gcloud auth application-default login</code> in your terminal. Photo Privateer automatically detects your local ADC session without requiring a JSON key file.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">6</span>
                        <span>Verify Credentials at Zero Cost (0 Quota)</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5 leading-relaxed">
                        Click <strong>Test Authentication (0 Units)</strong> above to verify OAuth2 token acquisition without consuming any paid Cloud Vision API quota.
                      </p>
                    </div>

                    <div className="p-2.5 rounded bg-accent-500/10 border border-accent-500/20 text-[10px] text-accent-200">
                      <span className="font-semibold text-white block mb-0.5">Pricing &amp; Free Tier:</span>
                      Google provides <strong>1,000 free Web Detection units per calendar month ($0.00)</strong>. Beyond the free allowance, pricing is $3.50 per 1,000 units (~$0.0035 / photo). Photo Privateer&apos;s local safety guard blocks any scan that would exceed your monthly free tier unless you explicitly authorize it.
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Cost & Guard Preferences */}
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

      {/* 3. Domain Auto-Classification Rules */}
      <section
        data-testid="domain-rules-section"
        className="bg-carbon-900 border border-carbon-800 rounded-lg p-4 space-y-4"
      >
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="font-semibold text-white flex items-center gap-1.5 text-sm">
              <Filter className="w-4 h-4 text-accent-500" />
              <span>Domain Auto-Classification Rules</span>
            </h3>
            <p className="text-carbon-400 mt-0.5">
              Automatically classify newly discovered matches on authorized client portfolios or known scraper domains.
            </p>
          </div>
          <button
            type="button"
            data-testid="btn-add-domain-rule"
            onClick={() => setRuleModalOpen(true)}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-carbon-800 hover:bg-carbon-700 text-white text-xs font-medium transition-colors shrink-0"
          >
            <Plus className="w-3.5 h-3.5 text-accent-400" />
            <span>Add Rule</span>
          </button>
        </div>

        {domainRules.length === 0 ? (
          <div className="bg-carbon-950/60 border border-carbon-800 rounded-md p-4 text-center text-carbon-400 text-xs">
            No domain rules configured yet. Create a rule here or directly from any match card in the Review Queue.
          </div>
        ) : (
          <div className="space-y-1.5">
            {domainRules.map((rule) => (
              <div
                key={rule.id}
                data-testid={`domain-rule-${rule.domain}`}
                className="flex items-center justify-between gap-3 bg-carbon-950 border border-carbon-800 rounded-md px-3 py-2 text-xs"
              >
                <div className="flex flex-wrap items-center gap-2 min-w-0">
                  <span className="font-mono font-semibold text-white truncate">{rule.domain}</span>
                  <span
                    className={`px-1.5 py-0.2 rounded text-[10px] font-mono uppercase border ${
                      rule.classification === 'APPROVED'
                        ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                        : rule.classification === 'UNAUTHORIZED'
                        ? 'bg-rose-500/15 text-rose-300 border-rose-500/30'
                        : 'bg-carbon-800 text-carbon-300 border-carbon-700'
                    }`}
                  >
                    {rule.classification === 'UNAUTHORIZED' ? 'Infringing' : rule.classification}
                  </span>
                  {rule.notes && <span className="text-carbon-400 truncate text-[11px]">— {rule.notes}</span>}
                </div>
                <button
                  type="button"
                  data-testid={`btn-delete-rule-${rule.domain}`}
                  onClick={async () => {
                    try {
                      await deleteRule(rule.id);
                      await loadRules();
                      onRefreshData();
                    } catch (err) {
                      console.error('Failed deleting domain rule', err);
                    }
                  }}
                  title={`Remove rule for ${rule.domain}`}
                  className="p-1 rounded text-carbon-400 hover:text-rose-400 hover:bg-rose-950/30 transition-colors shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {ruleModalOpen && (
        <DomainRuleModal
          initialDomain=""
          onSave={async (domain: string, classification: ClassificationType, notes?: string) => {
            await createRule(domain, classification, notes);
            await loadRules();
            onRefreshData();
          }}
          onClose={() => setRuleModalOpen(false)}
        />
      )}
    </div>
  );
};
