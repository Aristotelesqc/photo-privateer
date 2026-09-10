import React from 'react';

export interface ProjectBadgeProps {
  project: string;
  truncate?: boolean;
  maxWidth?: string;
  className?: string;
  title?: string;
  onClick?: (e: React.MouseEvent) => void;
}

export const ProjectBadge: React.FC<ProjectBadgeProps> = ({
  project,
  truncate = false,
  maxWidth,
  className = '',
  title,
  onClick,
}) => {
  const baseClasses =
    'inline-flex items-center text-[9px] font-medium px-1.5 py-0.2 rounded bg-carbon-800 text-carbon-300 border border-carbon-700/80';
  const truncateClasses = truncate ? `truncate ${maxWidth || 'max-w-[85px]'}` : (maxWidth || '');
  const clickableClasses = onClick ? 'cursor-pointer hover:bg-carbon-700' : '';

  return (
    <span
      className={`${baseClasses} ${truncateClasses} ${clickableClasses} ${className}`}
      title={title ?? `Project: ${project}`}
      onClick={onClick}
    >
      📁 {project}
    </span>
  );
};
