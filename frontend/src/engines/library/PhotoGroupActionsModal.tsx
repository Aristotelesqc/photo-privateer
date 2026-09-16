import React, { useState, useEffect } from 'react';
import { Layers, Star, UserMinus, Trash2, X, AlertCircle, Loader2 } from 'lucide-react';
import { ImageItem, PhotoGroup } from '../../types';
import { fetchPhotoGroup, setPreferredImage, removeImageFromGroup, deletePhotoGroup } from '../../api/client';
import { Thumbnail } from '../../components/Thumbnail';

export interface PhotoGroupActionsModalProps {
  photo: ImageItem;
  isOpen: boolean;
  onClose: () => void;
  onGroupUpdated: () => void | Promise<void>;
}

export const PhotoGroupActionsModal: React.FC<PhotoGroupActionsModalProps> = ({
  photo,
  isOpen,
  onClose,
  onGroupUpdated,
}) => {
  const [group, setGroup] = useState<PhotoGroup | null>(null);
  const [loadingGroup, setLoadingGroup] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmUngroup, setConfirmUngroup] = useState<boolean>(false);

  const groupId = photo.photo_group_id;

  useEffect(() => {
    if (!isOpen || !groupId) return;
    setLoadingGroup(true);
    setError(null);
    setConfirmUngroup(false);

    fetchPhotoGroup(groupId)
      .then((g) => setGroup(g))
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      })
      .finally(() => setLoadingGroup(false));
  }, [isOpen, groupId]);

  if (!isOpen || !groupId) return null;

  const isPrimary = photo.is_primary_representation === 1;

  const handleSetPrimary = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      await setPreferredImage(groupId, photo.id);
      await onGroupUpdated();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRemoveFromGroup = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      await removeImageFromGroup(groupId, photo.id);
      await onGroupUpdated();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleUngroupAll = async () => {
    setIsSubmitting(true);
    setError(null);
    try {
      await deletePhotoGroup(groupId);
      await onGroupUpdated();
      onClose();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-xs animate-fade-in">
      <div
        data-testid="photo-group-actions-modal"
        className="bg-carbon-900 border border-carbon-800 rounded-xl w-full max-w-lg shadow-2xl overflow-hidden text-carbon-100 text-xs animate-scale-up flex flex-col max-h-[90vh]"
      >
        {/* Header */}
        <div className="px-4 py-3 border-b border-carbon-800 flex items-center justify-between bg-carbon-950/60">
          <div className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-accent-600/10 text-accent-400">
              <Layers className="w-4 h-4" />
            </div>
            <div>
              <h3 className="font-semibold text-white text-xs">Manage Perceptual Group #{groupId}</h3>
              <p className="text-[10px] text-carbon-400">
                Configure primary representation and group membership
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSubmitting}
            data-testid="btn-close-group-actions"
            className="p-1 rounded text-carbon-400 hover:text-white hover:bg-carbon-800 disabled:opacity-30 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Error Alert */}
        {error && (
          <div
            role="alert"
            data-testid="group-actions-error"
            className="px-4 py-2.5 bg-red-950/80 border-b border-red-800 text-red-300 text-xs flex items-center justify-between animate-fade-in"
          >
            <div className="flex items-center gap-2">
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
              <span>{error}</span>
            </div>
            <button
              type="button"
              onClick={() => setError(null)}
              className="p-1 text-red-400 hover:text-white rounded cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}

        {/* Selected Photo Card */}
        <div className="p-4 space-y-4 overflow-y-auto">
          <div className="bg-carbon-950 border border-carbon-800 rounded-lg p-3 flex gap-3 items-center">
            <div className="w-16 h-16 rounded overflow-hidden bg-carbon-900 border border-carbon-800 shrink-0">
              <Thumbnail src={photo.thumbnail_url} alt={photo.filename} className="w-full h-full object-contain" />
            </div>
            <div className="flex-1 min-w-0 space-y-1">
              <div className="flex items-center gap-2">
                <p className="font-mono text-white text-xs truncate" title={photo.filename}>
                  {photo.filename}
                </p>
                <span
                  data-testid={isPrimary ? 'badge-primary' : 'badge-variant'}
                  className={`text-[9px] font-mono px-1.5 py-0.2 rounded ${
                    isPrimary
                      ? 'bg-accent-950/90 text-accent-300 border border-accent-800/80'
                      : 'bg-carbon-800 text-carbon-400 border border-carbon-700/80'
                  }`}
                >
                  {isPrimary ? 'Primary Representation' : 'Variant'}
                </span>
              </div>
              <div className="text-[10px] text-carbon-400 flex flex-wrap gap-x-2">
                <span>{photo.width && photo.height ? `${photo.width}×${photo.height}` : 'Dimensions unknown'}</span>
                <span>•</span>
                <span>{(photo.file_size / 1024).toFixed(1)} KB</span>
                {photo.format && (
                  <>
                    <span>•</span>
                    <span className="uppercase">{photo.format}</span>
                  </>
                )}
              </div>
              {photo.project && (
                <span className="inline-block px-1.5 py-0.2 rounded text-[9px] bg-carbon-800 text-carbon-300 font-mono">
                  {photo.project}
                </span>
              )}
            </div>
          </div>

          {/* Group Overview */}
          {loadingGroup ? (
            <div className="flex items-center justify-center py-4 text-carbon-400 text-xs gap-2">
              <Loader2 className="w-4 h-4 animate-spin text-accent-400" />
              <span>Loading group members...</span>
            </div>
          ) : group && (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[11px] text-carbon-400">
                <span>Group Representations ({group.images?.length || 0} total):</span>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {group.images?.map((img) => (
                  <div
                    key={img.id}
                    className={`relative rounded border p-1 bg-carbon-950 ${
                      img.id === photo.id
                        ? 'border-accent-500 ring-1 ring-accent-500/40'
                        : 'border-carbon-800 opacity-70 hover:opacity-100'
                    }`}
                    title={img.filename}
                  >
                    <div className="aspect-square bg-carbon-900 rounded overflow-hidden mb-1 flex items-center justify-center">
                      <Thumbnail src={img.thumbnail_url} alt={img.filename} className="w-full h-full object-contain" />
                    </div>
                    <p className="font-mono text-[9px] truncate text-white">{img.filename}</p>
                    {img.id === group.preferred_image_id && (
                      <span className="absolute top-1 right-1 p-0.5 rounded-full bg-accent-500 text-white shadow-xs" title="Preferred representation">
                        <Star className="w-2.5 h-2.5 fill-current" />
                      </span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="space-y-2 pt-2 border-t border-carbon-800">
            {/* Set as Primary Representation */}
            {!isPrimary && (
              <button
                onClick={handleSetPrimary}
                disabled={isSubmitting}
                data-testid="btn-set-primary"
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg bg-accent-600 hover:bg-accent-500 text-white text-xs font-semibold shadow-xs transition-colors disabled:opacity-50 cursor-pointer"
              >
                <Star className="w-3.5 h-3.5" />
                <span>Set as Primary Representation</span>
              </button>
            )}

            {/* Remove from Group */}
            <button
              onClick={handleRemoveFromGroup}
              disabled={isSubmitting}
              data-testid="btn-remove-from-group"
              className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-carbon-700 bg-carbon-800/60 hover:bg-carbon-800 text-carbon-200 hover:text-white text-xs font-medium transition-colors disabled:opacity-50 cursor-pointer"
            >
              <UserMinus className="w-3.5 h-3.5 text-carbon-400" />
              <span>Remove from Group</span>
            </button>

            {/* Ungroup Entire Group */}
            {confirmUngroup ? (
              <div className="p-3 bg-red-950/40 border border-red-800/80 rounded-lg space-y-2 animate-fade-in">
                <p className="text-[11px] text-red-200 font-medium">
                  Dissolve this entire group? All sibling photos will become independent ungrouped singletons.
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleUngroupAll}
                    disabled={isSubmitting}
                    data-testid="btn-confirm-ungroup"
                    className="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white rounded text-xs font-semibold transition-colors disabled:opacity-50 cursor-pointer"
                  >
                    Confirm Ungroup All
                  </button>
                  <button
                    onClick={() => setConfirmUngroup(false)}
                    disabled={isSubmitting}
                    className="px-3 py-1.5 border border-carbon-700 hover:bg-carbon-800 text-carbon-300 rounded text-xs transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <button
                onClick={() => setConfirmUngroup(true)}
                disabled={isSubmitting}
                data-testid="btn-ungroup-all"
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-red-900/40 bg-red-950/20 hover:bg-red-950/40 text-red-400 hover:text-red-300 text-xs font-medium transition-colors disabled:opacity-50 cursor-pointer"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>Ungroup Entire Group</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
