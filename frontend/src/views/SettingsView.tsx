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
} from 'lucide-react';
import { Library, AppSettings } from '../types';
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
} from '../api/client';
import { MonitoredFolderCard } from '../engines/settings/MonitoredFolderCard';
import { AddFolderSection } from '../engines/settings/AddFolderSection';

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
      onRefreshData();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Failed to stop monitoring folder: ${msg}`);
    }
  };

  const handleUnarchiveLibrary = async (libId: number) => {
    try {
      await unarchiveLibrary(libId);
      onRefreshData();
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
                  <span className="font-semibold text-white">Guide d'Aide : Configuration de l'API Google Cloud Vision</span>
                </span>
                <span className="flex items-center gap-1 text-[11px] text-accent-400 font-mono">
                  <span>{showApiGuide ? 'Masquer le guide' : 'Afficher le guide pas-à-pas'}</span>
                  {showApiGuide ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                </span>
              </button>

              {showApiGuide && (
                <div className="p-3.5 pt-1 space-y-3 border-t border-carbon-800 text-[11px] text-carbon-300">
                  <p className="text-carbon-300 leading-relaxed text-[11px]">
                    Photo Privateer utilise l'API officielle <strong>Google Cloud Vision (Web Detection)</strong> pour identifier les réutilisations de vos photographies sur le web public. Suivez ces étapes simples pour configurer votre accès :
                  </p>

                  <div className="space-y-2.5">
                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">1</span>
                        <span>Créer un compte et un projet Google Cloud</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5">
                        Rendez-vous sur la <a href="https://console.cloud.google.com/" target="_blank" rel="noreferrer" className="text-accent-400 underline inline-flex items-center gap-0.5">Google Cloud Console <ExternalLink className="w-2.5 h-2.5" /></a> et connectez-vous avec votre compte Google. Créez ensuite un nouveau projet (par ex. <em>photo-privateer</em>).
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">2</span>
                        <span>Activer l'API Cloud Vision</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5">
                        Dans le menu de gauche, naviguez vers <strong>APIs &amp; Services &gt; Library</strong>. Recherchez <code>Cloud Vision API</code>, cliquez dessus puis cliquez sur <strong>Enable</strong> (Activer).
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">3</span>
                        <span>Créer un Compte de Service (Service Account)</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5">
                        Allez dans <strong>IAM &amp; Admin &gt; Service Accounts</strong>. Cliquez sur <strong>Create Service Account</strong> (nommez-le par ex. <em>photo-privateer-app</em>). À l'étape des autorisations, attribuez-lui le rôle <strong>Cloud Vision User</strong>.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">4</span>
                        <span>Télécharger la clé privée JSON &amp; la stocker localement</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5 leading-relaxed">
                        Cliquez sur le compte de service créé, ouvrez l'onglet <strong>Keys</strong> (Clés) &gt; <strong>Add Key</strong> &gt; <strong>Create new key</strong> &gt; choisissez le format <strong>JSON</strong>. Téléchargez le fichier et conservez-le dans un dossier privé et sécurisé sur votre machine (ex: <code>C:\Users\VotreNom\.secrets\vision-key.json</code>). Copiez ensuite son chemin absolu dans le champ ci-dessus.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-emerald-500/20 text-emerald-300 flex items-center justify-center text-[10px] font-mono">5</span>
                        <span>Alternative sans fichier : Application Default Credentials (ADC)</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5 leading-relaxed">
                        Si vous avez installé le Google Cloud SDK (<code>gcloud</code>), exécutez simplement <code>gcloud auth application-default login</code> dans votre terminal. Photo Privateer détectera automatiquement votre session ADC sans nécessiter de fichier clé JSON.
                      </p>
                    </div>

                    <div className="bg-carbon-950 p-2.5 rounded border border-carbon-800/80">
                      <div className="flex items-center gap-1.5 font-semibold text-white mb-1">
                        <span className="w-4 h-4 rounded-full bg-accent-500/20 text-accent-300 flex items-center justify-center text-[10px] font-mono">6</span>
                        <span>Tester la connexion sans frais (0 Quota)</span>
                      </div>
                      <p className="text-carbon-400 text-[10px] pl-5 leading-relaxed">
                        Cliquez sur le bouton <strong>Test Authentication (0 Units)</strong> ci-dessus. L'application vérifie instantanément la validité de la clé et l'obtention d'un jeton d'accès sans effectuer aucun appel Vision payant.
                      </p>
                    </div>

                    <div className="p-2.5 rounded bg-accent-500/10 border border-accent-500/20 text-[10px] text-accent-200">
                      <span className="font-semibold text-white block mb-0.5">💰 Tarifs et Quota Gratuit :</span>
                      Google offre chaque mois civil <strong>1 000 requêtes gratuites ($0.00)</strong> sur l'API Web Detection. Au-delà, le tarif est de $3.50 par tranche de 1 000 requêtes (~0.0035 $ / photo). Le garde-fou local intégré de Photo Privateer bloque automatiquement tout scan qui dépasserait votre quota gratuit sans votre confirmation explicite.
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
    </div>
  );
};
