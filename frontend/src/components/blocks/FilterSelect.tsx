import React from 'react';

export interface FilterSelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

export const FilterSelect: React.FC<FilterSelectProps> = ({
  className = '',
  children,
  ...props
}) => {
  return (
    <select
      className={`bg-carbon-950 border border-carbon-800 rounded-md px-2.5 py-1.5 text-xs text-carbon-200 focus:outline-none focus:border-accent-500 shrink-0 font-medium ${className}`}
      {...props}
    >
      {children}
    </select>
  );
};
