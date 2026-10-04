import React from 'react';
import { Check, Square } from 'lucide-react';
import { ImageItem } from '../../types';
import { Thumbnail } from '../../components/Thumbnail';
import { ProjectBadge } from '../../components/blocks/ProjectBadge';
import { StatusPill } from '../../components/blocks/StatusPill';

export interface PhotoCardProps {
  photo: ImageItem;
  isSelected: boolean;
  onToggleSelect: (id: number) => void;
  onNavigateToReview: (photoId: number) => void;
  onManageGroup?: (photo: ImageItem) => void;
}

export const PhotoCard: React.FC<PhotoCardProps> = ({
  photo,
  isSelected,
  onToggleSelect,
  onNavigateToReview,
  onManageGroup,
}) => {
  const formatStr = photo.format || 'IMG';
  const sizeMb = (photo.file_size / (1024 * 1024)).toFixed(1);

  return (
    <div
      onClick={() => onToggleSelect(photo.id)}
      data-testid={`photo-card-${photo.filename}`}
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

        {/* Format Pill Overlay & Missing Warning */}
        <div className="absolute top-1.5 right-1.5 flex flex-col items-end gap-1">
          <span className="text-[9px] font-mono px-1 py-0.2 rounded bg-black/70 text-carbon-300 backdrop-blur-xs">
            {formatStr}
          </span>
          {photo.photo_group_id && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onManageGroup?.(photo);
              }}
              data-testid={photo.is_primary_representation === 1 ? 'badge-primary' : 'badge-variant'}
              className={`text-[9px] font-mono px-1 py-0.2 rounded backdrop-blur-xs transition-all hover:scale-105 cursor-pointer ${
                photo.is_primary_representation === 1
                  ? 'bg-accent-950/90 text-accent-300 border border-accent-800/80 hover:bg-accent-900'
                  : 'bg-carbon-950/90 text-carbon-400 border border-carbon-700/80 hover:text-carbon-200 hover:bg-carbon-900'
              }`}
              title={
                photo.is_primary_representation === 1
                  ? 'Primary representation (searched on web) — Click to manage group'
                  : 'Secondary grouped representation — Click to manage group'
              }
            >
              {photo.is_primary_representation === 1 ? 'Primary' : 'Variant'}
            </button>
          )}
          {!photo.is_present_on_disk && (
            <span
              className="text-[9px] font-medium px-1 py-0.2 rounded bg-amber-950/90 text-amber-300 border border-amber-800/80 backdrop-blur-xs shadow-xs"
              title="File missing from original path on disk"
            >
              Missing
            </span>
          )}
        </div>

        {/* Status Overlay Footer on Image */}
        <div className="absolute bottom-1.5 left-1.5 right-1.5 flex items-center justify-between pointer-events-none">
          <StatusPill
            matchCount={photo.group_match_count ?? photo.match_count}
            unreviewedCount={photo.group_unreviewed_count ?? photo.unreviewed_count}
            scanCount={photo.group_scan_count ?? photo.scan_count}
            onMatchClick={() => onNavigateToReview(photo.id)}
          />
        </div>
      </div>

      {/* Info Footer */}
      <div className="p-2 space-y-0.5 border-t border-carbon-800/80 bg-carbon-900/60">
        <div className="flex items-center justify-between gap-1">
          <p className="text-[11px] font-medium text-carbon-200 truncate leading-tight flex-1" title={photo.filename}>
            {photo.filename}
          </p>
          {photo.project && (
            <ProjectBadge
              project={photo.project}
              truncate
              maxWidth="max-w-[85px]"
              className="shrink-0"
            />
          )}
        </div>
        <div className="flex items-center justify-between text-[10px] font-mono text-carbon-400 tabular-nums">
          <span>{photo.width && photo.height ? `${photo.width}×${photo.height}` : '—'}</span>
          <span>{sizeMb}MB</span>
        </div>
      </div>
    </div>
  );
};
