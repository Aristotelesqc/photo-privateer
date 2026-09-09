import React, { useState, useEffect } from 'react';
import {
  FolderPlus,
  Search,
  Square,
  ShieldAlert,
  Sparkles,
  Grid,
  LayoutGrid,
  Check,
  AlertCircle,
  X,
} from 'lucide-react';
import { Library, ImageItem, AppSettings, ScanPrepareResponse } from '../types';
import { fetchPhotos, prepareScan, startScan } from '../api/client';
import { Thumbnail } from '../components/Thumbnail';
import { ScanConfirmModal } from '../components/ScanConfirmModal';
import { ScanProgressModal } from '../components/ScanProgressModal';

interface LibraryViewProps {
  libraries: Library[];
  settings: AppSettings | null;
  onRefreshData: () => void;
  onNavigateToSettings: () => void;
  onNavigateToReviewForPhoto: (photoId: number) => void;
}

export const LibraryView: React.FC<LibraryViewProps> = ({
  libraries,
  settings,
  onRefreshData,
  onNavigateToSettings,
  onNavigateToReviewForPhoto,
}) => {
  const [photos, setPhotos] = useState<ImageItem[]>([]);
  const [totalPhotos, setTotalPhotos] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());

  // Density toggle: 'standard' (200px) vs 'compact' (145px)
  const [density, setDensity] = useState<'standard' | 'compact'>('standard');

  // Filters & pagination
  const [selectedLibraryId, setSelectedLibraryId] = useState<number | undefined>(undefined);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'unscanned' | 'scanned' | 'has_matches' | 'has_unreviewed'>('all');
  const [page, setPage] = useState(1);
  const pageSize = density === 'compact' ? 60 : 40;

  // Scan workflow state
  const [scanProjection, setScanProjection] = useState<ScanPrepareResponse | null>(null);
  const [preparingScan, setPreparingScan] = useState(false);
  const [scanSession, setScanSession] = useState<any | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanModalOpen, setScanModalOpen] = useState(false);

  const loadPhotos = async () => {
    setLoading(true);
    try {
      const res = await fetchPhotos({
        library_id: selectedLibraryId,
        search: searchQuery.trim() || undefined,
        filter_status: statusFilter,
        page,
        page_size: pageSize,
      });
      setPhotos(res.images);
      setTotalPhotos(res.total);
    } catch (err) {
      console.error('Failed loading photos', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPhotos();
  }, [selectedLibraryId, searchQuery, statusFilter, page, density]);

  // Selection handlers
  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectAllVisible = () => {
    setSelectedIds(new Set(photos.map((p) => p.id)));
  };

  const deselectAll = () => {
    setSelectedIds(new Set());
  };

  // Scan initiation
  const handleScanClicked = async () => {
    if (selectedIds.size === 0) return;
    setPreparingScan(true);
    try {
      const proj = await prepareScan(Array.from(selectedIds));
      setScanProjection(proj);
    } catch (err: any) {
      alert(`Error preparing scan: ${err.message}`);
    } finally {
      setPreparingScan(false);
    }
  };

  const handleConfirmScan = async (forceOverride: boolean) => {
    if (!scanProjection) return;
    const ids = Array.from(selectedIds);
    setScanProjection(null);
    setScanning(true);
    setScanModalOpen(true);
    try {
      const session = await startScan(ids, undefined, forceOverride);
      setScanSession(session);
      onRefreshData();
      loadPhotos();
      deselectAll();
    } catch (err: any) {
      alert(`Scan failed: ${err.message}`);
      setScanModalOpen(false);
    } finally {
      setScanning(false);
    }
  };

  // Empty state: No libraries configured
  if (libraries.length === 0) {
    return (
      <div className="max-w-xl mx-auto py-20 px-6 text-center">
        <div className="w-12 h-12 rounded-lg bg-carbon-900 border border-carbon-800 flex items-center justify-center mx-auto mb-3 text-accent-500 shadow-sm">
          <FolderPlus className="w-6 h-6" />
        </div>
        <h2 className="text-base font-semibold text-carbon-100 mb-1.5">No Local Photo Libraries</h2>
        <p className="text-xs text-carbon-400 max-w-sm mx-auto mb-5 leading-relaxed">
          Configure a local folder on your computer. Photo Privateer indexes photographs in read-only mode without touching your original files.
        </p>
        <button
          onClick={onNavigateToSettings}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-accent-600 hover:bg-accent-500 text-white text-xs font-semibold shadow-sm transition-all active:scale-98"
        >
          <FolderPlus className="w-4 h-4" />
          <span>Configure Photograph Folder</span>
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-4 space-y-4">
      {/* Control Strip */}
      <div className="bg-carbon-900 border border-carbon-800 rounded-lg p-2.5 flex flex-wrap items-center justify-between gap-3 text-xs">
        {/* Left: Library select, Search, and Status chips */}
        <div className="flex flex-wrap items-center gap-2 flex-1 min-w-[280px]">
          {/* Library Select */}
          <select
            value={selectedLibraryId ?? ''}
            onChange={(e) => {
              const val = e.target.value;
              setSelectedLibraryId(val ? Number(val) : undefined);
              setPage(1);
            }}
            className="bg-carbon-950 border border-carbon-800 rounded-md px-2.5 py-1.5 text-xs text-carbon-200 focus:outline-none focus:border-accent-500 shrink-0 font-medium"
          >
            <option value="">All Libraries ({totalPhotos})</option>
            {libraries.map((lib) => (
              <option key={lib.id} value={lib.id}>
                {lib.name} ({lib.image_count})
              </option>
            ))}
          </select>

          {/* Search Box */}
          <div className="relative w-44 sm:w-56">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-carbon-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setPage(1);
              }}
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
                onClick={() => {
                  setStatusFilter(key);
                  setPage(1);
                }}
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
              onClick={() => setDensity('standard')}
              title="Standard Grid"
              className={`p-1 rounded ${density === 'standard' ? 'bg-carbon-800 text-white' : 'hover:text-carbon-200'}`}
            >
              <LayoutGrid className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setDensity('compact')}
              title="Compact Grid"
              className={`p-1 rounded ${density === 'compact' ? 'bg-carbon-800 text-white' : 'hover:text-carbon-200'}`}
            >
              <Grid className="w-3.5 h-3.5" />
            </button>
          </div>

          {/* Direct Scan Trigger */}
          <button
            onClick={handleScanClicked}
            disabled={selectedIds.size === 0 || preparingScan}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold shadow-sm transition-all ${
              selectedIds.size === 0 || preparingScan
                ? 'bg-carbon-800 text-carbon-500 cursor-not-allowed border border-carbon-800'
                : 'bg-accent-600 hover:bg-accent-500 text-white shadow-accent-600/20 active:scale-98'
            }`}
          >
            {settings?.active_provider === 'mock' ? (
              <Sparkles className="w-3.5 h-3.5 text-amber-300" />
            ) : (
              <ShieldAlert className="w-3.5 h-3.5 text-white" />
            )}
            <span>Scan Selected ({selectedIds.size})</span>
          </button>
        </div>
      </div>

      {/* Fluid Responsive Photo Grid */}
      {loading ? (
        <div
          className={`grid gap-2.5 ${
            density === 'compact'
              ? 'grid-cols-[repeat(auto-fill,minmax(140px,1fr))]'
              : 'grid-cols-[repeat(auto-fill,minmax(190px,1fr))]'
          }`}
        >
          {Array.from({ length: 24 }).map((_, i) => (
            <div key={i} className="aspect-square bg-carbon-900 rounded-lg animate-pulse border border-carbon-800" />
          ))}
        </div>
      ) : photos.length === 0 ? (
        <div className="bg-carbon-900/60 border border-carbon-800 rounded-lg py-16 text-center">
          <AlertCircle className="w-7 h-7 mx-auto mb-2 text-carbon-500" />
          <p className="text-xs font-medium text-carbon-200">No photographs match current filter</p>
          <p className="text-[11px] text-carbon-500 mt-0.5">Adjust filter chip or clear filename search.</p>
        </div>
      ) : (
        <div
          className={`grid gap-2.5 ${
            density === 'compact'
              ? 'grid-cols-[repeat(auto-fill,minmax(140px,1fr))]'
              : 'grid-cols-[repeat(auto-fill,minmax(190px,1fr))]'
          }`}
        >
          {photos.map((photo) => {
            const isSelected = selectedIds.has(photo.id);
            const formatStr = photo.format || 'IMG';
            const sizeMb = (photo.file_size / (1024 * 1024)).toFixed(1);

            return (
              <div
                key={photo.id}
                onClick={() => toggleSelect(photo.id)}
                className={`group relative bg-carbon-900 border rounded-lg overflow-hidden cursor-pointer transition-all duration-100 select-none flex flex-col ${
                  isSelected
                    ? 'border-accent-500 ring-1 ring-accent-500 bg-carbon-850 shadow-xs'
                    : 'border-carbon-800 hover:border-carbon-700 hover:bg-carbon-850'
                }`}
              >
                {/* Photo Thumbnail */}
                <div className="aspect-square w-full relative bg-carbon-950">
                  <Thumbnail src={photo.thumbnail_url} alt={photo.filename} className="w-full h-full" />

                  {/* Checkbox indicator */}
                  <div
                    className={`absolute top-1.5 left-1.5 rounded transition-all p-0.5 ${
                      isSelected
                        ? 'bg-accent-600 text-white shadow-xs'
                        : 'bg-black/60 text-white/60 opacity-0 group-hover:opacity-100'
                    }`}
                  >
                    {isSelected ? <Check className="w-3.5 h-3.5 stroke-[2.5]" /> : <Square className="w-3.5 h-3.5" />}
                  </div>

                  {/* Format Pill Overlay */}
                  <span className="absolute top-1.5 right-1.5 text-[9px] font-mono px-1 py-0.2 rounded bg-black/70 text-carbon-300 backdrop-blur-xs">
                    {formatStr}
                  </span>

                  {/* Status Overlay Footer on Image */}
                  <div className="absolute bottom-1.5 left-1.5 right-1.5 flex items-center justify-between pointer-events-none">
                    {photo.match_count > 0 ? (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onNavigateToReviewForPhoto(photo.id);
                        }}
                        className="pointer-events-auto px-1.5 py-0.5 rounded text-[10px] font-bold bg-carbon-950/90 border border-carbon-700 text-white hover:bg-carbon-900 shadow-xs flex items-center gap-1 tabular-nums"
                      >
                        <span>{photo.match_count} matches</span>
                        {photo.unreviewed_count > 0 && (
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
                        )}
                      </button>
                    ) : photo.scan_count > 0 ? (
                      <span className="px-1.5 py-0.2 rounded text-[9px] bg-carbon-950/80 text-carbon-400 font-mono">
                        Clean
                      </span>
                    ) : (
                      <span className="px-1.5 py-0.2 rounded text-[9px] bg-carbon-950/80 text-carbon-500 font-mono">
                        Unscanned
                      </span>
                    )}
                  </div>
                </div>

                {/* Info Footer */}
                <div className="p-2 space-y-0.5 border-t border-carbon-800/80 bg-carbon-900/60">
                  <p className="text-[11px] font-medium text-carbon-200 truncate leading-tight" title={photo.filename}>
                    {photo.filename}
                  </p>
                  <div className="flex items-center justify-between text-[10px] font-mono text-carbon-400 tabular-nums">
                    <span>{photo.width && photo.height ? `${photo.width}×${photo.height}` : '—'}</span>
                    <span>{sizeMb}MB</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination Strip */}
      {totalPhotos > pageSize && (
        <div className="flex items-center justify-between pt-3 text-xs text-carbon-400 border-t border-carbon-800">
          <span className="tabular-nums">
            Showing {(page - 1) * pageSize + 1}–{Math.min(page * pageSize, totalPhotos)} of {totalPhotos}
          </span>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-2.5 py-1 rounded bg-carbon-900 border border-carbon-800 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-carbon-800"
            >
              Prev
            </button>
            <span className="px-2 font-mono text-xs tabular-nums">Page {page}</span>
            <button
              onClick={() => setPage((p) => p + 1)}
              disabled={page * pageSize >= totalPhotos}
              className="px-2.5 py-1 rounded bg-carbon-900 border border-carbon-800 text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-carbon-800"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* Floating Selection Dock */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-40 bg-carbon-900/95 backdrop-blur-md border border-carbon-700 rounded-xl px-4 py-2 shadow-2xl flex items-center gap-4 text-xs animate-scale-up">
          <div className="flex items-center gap-2 text-white font-medium">
            <span className="w-2 h-2 rounded-full bg-accent-500 animate-pulse" />
            <span className="tabular-nums">{selectedIds.size}</span> selected
          </div>

          <div className="h-4 w-px bg-carbon-700" />

          <button
            onClick={selectedIds.size === photos.length ? deselectAll : selectAllVisible}
            className="text-carbon-300 hover:text-white underline underline-offset-2"
          >
            {selectedIds.size === photos.length ? 'Deselect all' : 'Select all visible'}
          </button>

          <button
            onClick={deselectAll}
            className="p-1 rounded text-carbon-400 hover:text-white hover:bg-carbon-800"
            title="Clear selection"
          >
            <X className="w-3.5 h-3.5" />
          </button>

          <button
            onClick={handleScanClicked}
            disabled={preparingScan}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-accent-600 hover:bg-accent-500 text-white font-semibold shadow-sm transition-all active:scale-98"
          >
            <span>Scan Selection</span>
          </button>
        </div>
      )}

      {/* Modals */}
      {scanProjection && (
        <ScanConfirmModal
          projection={scanProjection}
          onConfirm={handleConfirmScan}
          onClose={() => setScanProjection(null)}
        />
      )}

      {scanModalOpen && (
        <ScanProgressModal
          session={scanSession}
          loading={scanning}
          onClose={() => {
            setScanModalOpen(false);
            setScanSession(null);
          }}
        />
      )}
    </div>
  );
};
