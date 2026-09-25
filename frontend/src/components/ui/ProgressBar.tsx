import React from 'react';
import { NO_DATA_LABEL } from '../../utils/helpers';

interface ProgressBarProps {
  /**
   * `null` means the source never reported progress. It renders an explicitly
   * empty bar labelled "Not reported" rather than a 0%-filled one, because a
   * full-width empty track is indistinguishable from 0% and would fabricate a
   * measurement the data does not contain.
   */
  value: number | null;
  max?: number;
  color?: 'blue' | 'green' | 'yellow' | 'red' | 'gray';
  size?: 'sm' | 'md';
  showLabel?: boolean;
  label?: string;
}

const colorMap = {
  blue: 'bg-blue-600',
  green: 'bg-green-600',
  yellow: 'bg-yellow-500',
  red: 'bg-red-600',
  gray: 'bg-gray-500',
};

const sizeMap = {
  sm: 'h-2',
  md: 'h-3',
};

export function ProgressBar({
  value,
  max = 100,
  color = 'blue',
  size = 'sm',
  showLabel = false,
  label,
}: ProgressBarProps) {
  const unknown = value === null || value === undefined;
  const percentage = unknown ? 0 : Math.min(Math.round((value / max) * 100), 100);

  return (
    <div className="flex items-center gap-3">
      <div
        className={`w-full overflow-hidden rounded-full bg-gray-200 ${sizeMap[size]}`}
        title={unknown ? NO_DATA_LABEL : undefined}
      >
        {unknown ? null : (
          <div
            className={`transition-all duration-500 ${colorMap[color]} ${sizeMap[size]} rounded-full`}
            style={{ width: `${percentage}%` }}
          />
        )}
      </div>
      {showLabel && (
        <span className="text-sm font-medium text-gray-700 whitespace-nowrap">
          {unknown
            ? NO_DATA_LABEL
            : label
              ? `${label} ${percentage}%`
              : `${percentage}%`}
        </span>
      )}
    </div>
  );
}
