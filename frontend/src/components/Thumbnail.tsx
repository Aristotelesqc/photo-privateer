import React, { useState } from 'react';
import { Image as ImageIcon, ImageOff } from 'lucide-react';

interface ThumbnailProps {
  src: string;
  alt: string;
  className?: string;
  isRemote?: boolean;
}

export const Thumbnail: React.FC<ThumbnailProps> = ({
  src,
  alt,
  className = '',
  isRemote = false,
}) => {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

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
