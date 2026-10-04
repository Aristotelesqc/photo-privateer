import React from 'react';
import { Check } from 'lucide-react';
import { ImageItem } from '../../types';

export interface CandidateCardProps {
  image: ImageItem;
  label: string;
  isSelected: boolean;
  onSelect: () => void;
  testId?: string;
}

export const CandidateCard: React.FC<CandidateCardProps> = ({
  image,
  label,
  isSelected,
  onSelect,
  testId,
}) => {
  return (
    <div
      onClick={onSelect}
      data-testid={testId || `candidate-card-${image.filename}`}
      className={`border rounded-lg p-3 bg-carbon-950 cursor-pointer transition-all ${
        isSelected
          ? 'border-accent-500 ring-1 ring-accent-500/30'
          : 'border-carbon-800 hover:border-carbon-700'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-semibold text-carbon-400 uppercase tracking-wider">{label}</span>
        <div
          className={`w-4 h-4 rounded-full flex items-center justify-center border ${
            isSelected
              ? 'border-accent-500 bg-accent-500 text-white'
              : 'border-carbon-600 bg-carbon-800'
          }`}
        >
          {isSelected && <Check className="w-3 h-3 stroke-[3]" />}
        </div>
      </div>
      <div className="aspect-square bg-carbon-900 rounded overflow-hidden mb-2.5 flex items-center justify-center border border-carbon-800">
        <img
          src={image.thumbnail_url}
          alt={image.filename}
          className="w-full h-full object-contain"
          loading="lazy"
        />
      </div>
      <div className="space-y-1">
        <p className="font-mono text-white text-xs truncate" title={image.filename}>
          {image.filename}
        </p>
        <div className="text-[11px] text-carbon-400 flex flex-wrap gap-x-2">
          <span>
            {image.width && image.height ? `${image.width}×${image.height}` : 'Dimensions unknown'}
          </span>
          <span>•</span>
          <span>{(image.file_size / 1024).toFixed(1)} KB</span>
          {image.format && (
            <>
              <span>•</span>
              <span className="uppercase">{image.format}</span>
            </>
          )}
        </div>
        {image.project && (
          <span className="inline-block mt-1 px-1.5 py-0.5 rounded text-[10px] bg-carbon-800 text-carbon-300 font-mono">
            {image.project}
          </span>
        )}
      </div>
      <div className="mt-3 pt-2 border-t border-carbon-800/80 text-[10px] text-carbon-400">
        {isSelected ? (
          <span className="text-accent-400 font-medium">Preferred (Used for Web Reverse Searches)</span>
        ) : (
          <span>Click to set as preferred search representation</span>
        )}
      </div>
    </div>
  );
};
