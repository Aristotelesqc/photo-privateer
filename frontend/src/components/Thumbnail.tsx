import React, { useState } from 'react';
import { Image as ImageIcon, ImageOff, Eye } from 'lucide-react';

interface ThumbnailProps {
  src: string;
  alt: string;
  className?: string;
  isRemote?: boolean;
  autoLoadRemote?: boolean;
}

export const Thumbnail: React.FC<ThumbnailProps> = ({
  src,
  alt,
  className = '',
  isRemote = false,
  autoLoadRemote = false,
}) => {
  const [revealed, setRevealed] = useState(!isRemote || autoLoadRemote);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  // Privacy Opt-In: Do not request suspect external URLs until user explicitly clicks
  if (isRemote && !revealed) {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setRevealed(true);
        }}
        title="Suspect remote origin. Click to fetch preview without sending referrer."
        className={`bg-carbon-950 border border-carbon-800 hover:border-accent-500/60 flex flex-col items-center justify-center text-carbon-400 hover:text-carbon-200 text-xs p-1.5 text-center transition-all cursor-pointer group ${className}`}
      >
        <Eye className="w-3.5 h-3.5 mb-1 text-carbon-500 group-hover:text-accent-400 transition-colors" />
        <span className="text-[9px] font-mono text-carbon-400 group-hover:text-carbon-200">Load preview</span>
      </button>
    );
  }

  if (error) {
    return (
      <div
        className={`bg-carbon-900 border border-carbon-800 flex flex-col items-center justify-center text-carbon-500 text-xs p-2 text-center select-none ${className}`}
      >
        <ImageOff className="w-4 h-4 mb-1 text-carbon-600" />
        <span className="text-[10px] text-carbon-500 line-clamp-1">{isRemote ? 'Remote unavailable' : 'Image error'}</span>
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden bg-carbon-900/80 ${className}`}>
      {!loaded && (
        <div className="absolute inset-0 flex items-center justify-center bg-carbon-900/60 animate-pulse">
          <ImageIcon className="w-5 h-5 text-carbon-700" />
        </div>
      )}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        referrerPolicy={isRemote ? 'no-referrer' : undefined}
        onLoad={() => setLoaded(true)}
        onError={() => setError(true)}
        className={`w-full h-full object-cover transition-opacity duration-150 ${
          loaded ? 'opacity-100' : 'opacity-0'
        }`}
      />
    </div>
  );
};
