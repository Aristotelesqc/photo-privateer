import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { LibraryView } from './views/LibraryView';
import { ReviewView } from './views/ReviewView';
import { UsageView } from './views/UsageView';
import { SettingsView } from './views/SettingsView';
import { Library, AppSettings, UsageSummary } from './types';
import { fetchLibraries, fetchSettings, fetchUsageSummary, fetchMatches } from './api/client';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'library' | 'review' | 'usage' | 'settings'>('library');
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [usageSummary, setUsageSummary] = useState<UsageSummary | null>(null);
  const [unreviewedCount, setUnreviewedCount] = useState(0);
  const [reviewPhotoFilterId, setReviewPhotoFilterId] = useState<number | undefined>(undefined);

  const loadGlobalData = async () => {
    try {
      const [libs, sett, usage, unrevMatches] = await Promise.all([
        fetchLibraries(),
        fetchSettings(),
        fetchUsageSummary(),
        fetchMatches({ classification: 'UNREVIEWED', page_size: 1 }),
      ]);
      setLibraries(libs);
      setSettings(sett);
      setUsageSummary(usage);
      setUnreviewedCount(unrevMatches.total);
    } catch (err) {
      console.error('Failed loading initial application data', err);
    }
  };

  useEffect(() => {
    loadGlobalData();
  }, []);

  const handleNavigateToReviewForPhoto = (photoId: number) => {
    setReviewPhotoFilterId(photoId);
    setActiveTab('review');
  };

  return (
    <div className="min-h-screen bg-brand-950 text-brand-100 flex flex-col font-sans">
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        settings={settings}
        usageSummary={usageSummary}
        unreviewedCount={unreviewedCount}
      />

      <main className="flex-1 pb-16">
        {activeTab === 'library' && (
          <LibraryView
            libraries={libraries}
            settings={settings}
            onRefreshData={loadGlobalData}
            onNavigateToSettings={() => setActiveTab('settings')}
            onNavigateToReviewForPhoto={handleNavigateToReviewForPhoto}
          />
        )}

        {activeTab === 'review' && (
          <ReviewView
            initialPhotoId={reviewPhotoFilterId}
            onClearPhotoFilter={() => setReviewPhotoFilterId(undefined)}
            onClassificationChanged={loadGlobalData}
          />
        )}

        {activeTab === 'usage' && (
          <UsageView
            settings={settings}
            onNavigateToSettings={() => setActiveTab('settings')}
          />
        )}

        {activeTab === 'settings' && (
          <SettingsView
            libraries={libraries}
            settings={settings}
            onRefreshData={loadGlobalData}
          />
        )}
      </main>
    </div>
  );
};

export default App;
