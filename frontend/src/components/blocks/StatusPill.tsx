import React from 'react';

export interface StatusPillProps {
  matchCount?: number;
  unreviewedCount?: number;
  scanCount?: number;
  onMatchClick?: () => void;
  className?: string;
}

export const StatusPill: React.FC<StatusPillProps> = ({
  matchCount = 0,
  unreviewedCount = 0,
  scanCount = 0,
  onMatchClick,
  className = '',
}) => {
  if (matchCount > 0) {
    const content = (
      <>
        <span>{matchCount} matches</span>
        {unreviewedCount > 0 && (
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        )}
      </>
    );

    if (onMatchClick) {
      return (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onMatchClick();
          }}
          className={`pointer-events-auto px-1.5 py-0.5 rounded text-[10px] font-bold bg-carbon-950/90 border border-carbon-700 text-white hover:bg-carbon-900 shadow-xs flex items-center gap-1 tabular-nums ${className}`}
        >
          {content}
        </button>
      );
    }

    return (
      <span
        className={`px-1.5 py-0.5 rounded text-[10px] font-bold bg-carbon-950/90 border border-carbon-700 text-white shadow-xs flex items-center gap-1 tabular-nums ${className}`}
      >
        {content}
      </span>
    );
  }

  if (scanCount > 0) {
    return (
      <span className={`px-1.5 py-0.2 rounded text-[9px] bg-carbon-950/80 text-carbon-400 font-mono ${className}`}>
        Clean
      </span>
    );
  }

  return (
    <span className={`px-1.5 py-0.2 rounded text-[9px] bg-carbon-950/80 text-carbon-500 font-mono ${className}`}>
      Unscanned
    </span>
  );
};
