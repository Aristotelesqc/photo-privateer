import React, { useState, useEffect } from 'react';
import {
  FolderPlus,
  AlertCircle,
  X,
  Tag,
} from 'lucide-react';
import { Library, ImageItem, AppSettings, ScanPrepareResponse, ScanSession, GroupCandidatePair } from '../types';
import {
  fetchPhotos,
  prepareScan,
  startScan,
  fetchScanHistory,
  fetchProjects,
  batchAssignProject,
  fetchGroupCandidates,
  createPhotoGroup,
  addImageToGroup,
  dismissGroupCandidate,
} from '../api/client';
import { ScanConfirmModal } from '../components/ScanConfirmModal';
import { ScanProgressModal } from '../components/ScanProgressModal';
import { CandidateGroupModal } from '../components/CandidateGroupModal';
import { LibraryFilterBar, StatusFilterType } from '../engines/library/LibraryFilterBar';
import { PhotoCard } from '../engines/library/PhotoCard';
import { ProjectAssignModal } from '../engines/library/ProjectAssignModal';
import { CandidateBanner } from '../engines/library/CandidateBanner';
import { PhotoGroupActionsModal } from '../engines/library/PhotoGroupActionsModal';

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
  const [statusFilter, setStatusFilter] = useState<StatusFilterType>('all');
  const [projects, setProjects] = useState<string[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const pageSize = density === 'compact' ? 60 : 40;

  // Project modal state
  const [projectModalOpen, setProjectModalOpen] = useState(false);

  // Candidate variants state
  const [candidates, setCandidates] = useState<GroupCandidatePair[]>([]);
  const [candidateModalOpen, setCandidateModalOpen] = useState(false);
  const [managingGroupPhoto, setManagingGroupPhoto] = useState<ImageItem | null>(null);

  // Scan workflow state
  const [scanProjection, setScanProjection] = useState<ScanPrepareResponse | null>(null);
  const [preparingScan, setPreparingScan] = useState(false);
  const [scanSession, setScanSession] = useState<ScanSession | null>(null);
  const [scanning, setScanning] = useState(false);
  const [scanModalOpen, setScanModalOpen] = useState(false);

  const loadCandidates = async () => {
    try {
      const pairs = await fetchGroupCandidates(
        selectedLibraryId !== undefined ? { library_id: selectedLibraryId } : undefined
      );
      setCandidates(pairs);
    } catch (err) {
      console.error('Failed loading candidate variants', err);
    }
  };

  const loadProjects = async () => {
    try {
      const projs = await fetchProjects(selectedLibraryId);
      setProjects(projs);
    } catch (err) {
      console.error('Failed loading projects', err);
    }
  };

  const loadPhotos = async () => {
    setLoading(true);
    try {
      const res = await fetchPhotos({
        library_id: selectedLibraryId,
        search: searchQuery.trim() || undefined,
        project: selectedProject,
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

  const handleGroupPair = async (imageAId: number, imageBId: number, preferredId: number) => {
    const candidate = candidates.find(
      (c) => (c.image_a.id === imageAId && c.image_b.id === imageBId) || (c.image_a.id === imageBId && c.image_b.id === imageAId)
    );
    const existingGroup = candidate?.image_a.photo_group_id
      ? { groupId: candidate.image_a.photo_group_id, newImageId: candidate.image_b.id }
      : candidate?.image_b.photo_group_id
      ? { groupId: candidate.image_b.photo_group_id, newImageId: candidate.image_a.id }
      : null;

    if (existingGroup) {
      await addImageToGroup(existingGroup.groupId, existingGroup.newImageId, preferredId === existingGroup.newImageId);
    } else {
      await createPhotoGroup({
        image_ids: [imageAId, imageBId],
        preferred_image_id: preferredId,
      });
    }
    await loadCandidates();
    await loadPhotos();
  };

  const handleDismissPair = async (imageAId: number, imageBId: number) => {
    await dismissGroupCandidate(imageAId, imageBId);
    await loadCandidates();
  };

  useEffect(() => {
    loadProjects();
    loadCandidates();
  }, [selectedLibraryId]);

  useEffect(() => {
    loadPhotos();
  }, [selectedLibraryId, searchQuery, selectedProject, statusFilter, page, density]);

  // Clear hidden selection on context change (library, filter, search, project, page)
  useEffect(() => {
    setSelectedIds(new Set());
  }, [selectedLibraryId, searchQuery, selectedProject, statusFilter, page]);


  // Restore active scan progress modal if a scan is already running
  useEffect(() => {
    fetchScanHistory(1)
      .then((sessions) => {
        if (sessions && sessions.length > 0 && sessions[0].status === 'RUNNING') {
          setScanSession(sessions[0]);
          setScanModalOpen(true);
        }
      })
      .catch(() => {});
  }, []);

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
      if (proj.usable_count === 0) {
        alert(
          'None of the selected photographs are currently available on disk. Please verify that the original storage path or drive is accessible.'
        );
        return;
      }
      setScanProjection(proj);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Error preparing scan: ${msg}`);
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
      deselectAll();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      alert(`Scan failed: ${msg}`);
      setScanModalOpen(false);
    } finally {
      setScanning(false);
    }
  };

  const handleAssignProject = async (projectName: string | null) => {
    await batchAssignProject(Array.from(selectedIds), projectName);
    await loadProjects();
    await loadPhotos();
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
      {/* Candidate Variants Banner */}
      <CandidateBanner
        count={candidates.length}
        onReview={() => setCandidateModalOpen(true)}
      />

      {/* Control Strip Filter Bar */}
      <LibraryFilterBar
        libraries={libraries}
        totalPhotos={totalPhotos}
        selectedLibraryId={selectedLibraryId}
        onSelectLibrary={(id) => {
          setSelectedLibraryId(id);
          setPage(1);
        }}
        projects={projects}
        selectedProject={selectedProject}
        onSelectProject={(proj) => {
          setSelectedProject(proj);
          setPage(1);
        }}
        searchQuery={searchQuery}
        onSearchChange={(query) => {
          setSearchQuery(query);
          setPage(1);
        }}
        statusFilter={statusFilter}
        onStatusFilterChange={(status) => {
          setStatusFilter(status);
          setPage(1);
        }}
        density={density}
        onDensityChange={setDensity}
        selectedCount={selectedIds.size}
        preparingScan={preparingScan}
        activeProvider={settings?.active_provider}
        onScanClicked={handleScanClicked}
      />

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
          {photos.map((photo) => (
            <PhotoCard
              key={photo.id}
              photo={photo}
              isSelected={selectedIds.has(photo.id)}
              onToggleSelect={toggleSelect}
              onNavigateToReview={onNavigateToReviewForPhoto}
              onManageGroup={setManagingGroupPhoto}
            />
          ))}
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
            onClick={() => {
              setProjectModalOpen(true);
            }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-carbon-800 hover:bg-carbon-700 text-carbon-200 hover:text-white font-medium transition-all"
          >
            <Tag className="w-3.5 h-3.5 text-accent-400" />
            <span>Assign Project</span>
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
          onScanFinished={() => {
            onRefreshData();
            loadPhotos();
          }}
          onClose={() => {
            setScanModalOpen(false);
            setScanSession(null);
            onRefreshData();
            loadPhotos();
          }}
        />
      )}

      {/* Project Assignment Modal */}
      <ProjectAssignModal
        isOpen={projectModalOpen}
        selectedCount={selectedIds.size}
        projects={projects}
        onClose={() => setProjectModalOpen(false)}
        onAssign={handleAssignProject}
      />

      {/* Candidate Grouping Modal */}
      {candidateModalOpen && (
        <CandidateGroupModal
          candidates={candidates}
          onGroup={handleGroupPair}
          onDismiss={handleDismissPair}
          onClose={() => {
            setCandidateModalOpen(false);
            loadPhotos();
            loadCandidates();
          }}
        />
      )}

      {/* Photo Group Actions Modal */}
      {managingGroupPhoto && (
        <PhotoGroupActionsModal
          photo={managingGroupPhoto}
          isOpen={Boolean(managingGroupPhoto)}
          onClose={() => setManagingGroupPhoto(null)}
          onGroupUpdated={async () => {
            await loadPhotos();
            await loadCandidates();
          }}
        />
      )}
    </div>
  );
};
