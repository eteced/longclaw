import React from 'react';

interface ProgressBarProps {
  completed: number;
  total: number;
  running?: number;
  showLabel?: boolean;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  completed,
  total,
  running = 0,
  showLabel = true,
}) => {
  const completedPercentage = total > 0 ? Math.round((completed / total) * 100) : 0;
  const runningPercentage = total > 0 ? Math.round((running / total) * 100) : 0;

  return (
    <div className="w-full">
      <div className="flex items-center justify-between mb-1">
        {showLabel && (
          <span className="text-sm text-gray-600">
            {completed}/{total} {running > 0 && `(${running} running)`}
          </span>
        )}
        <span className="text-sm text-gray-500">{completedPercentage}%</span>
      </div>
      <div className="w-full bg-gray-200 rounded-full h-2 flex">
        {/* Completed portion (blue) */}
        <div
          className="bg-blue-600 h-2 rounded-l-full transition-all duration-300"
          style={{ width: `${completedPercentage}%` }}
        />
        {/* Running portion (yellow) */}
        {runningPercentage > 0 && completedPercentage < 100 && (
          <div
            className="bg-yellow-400 h-2 transition-all duration-300"
            style={{ width: `${runningPercentage}%`, marginLeft: completedPercentage === 0 ? '0' : '0' }}
          />
        )}
        {/* Empty portion */}
        <div
          className="bg-gray-200 h-2 rounded-r-full flex-1"
        />
      </div>
    </div>
  );
};

export default ProgressBar;
