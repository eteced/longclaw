import React from 'react';

interface BadgeProps {
  status: string;
  size?: 'sm' | 'md';
  variant?: 'status' | 'type';
}

const statusColors: Record<string, string> = {
  // Task status
  planning: 'bg-blue-100 text-blue-800',
  running: 'bg-yellow-100 text-yellow-800',
  paused: 'bg-gray-100 text-gray-800',
  completed: 'bg-green-100 text-green-800',
  terminated: 'bg-gray-200 text-gray-600',
  error: 'bg-red-100 text-red-800',
  // Subtask status
  pending: 'bg-gray-100 text-gray-600',
  failed: 'bg-red-100 text-red-800',
  skipped: 'bg-gray-200 text-gray-500',
  // Agent status
  idle: 'bg-gray-100 text-gray-600',
};

const typeColors: Record<string, string> = {
  // Agent types
  resident: 'bg-purple-100 text-purple-800',
  owner: 'bg-blue-100 text-blue-800',
  worker: 'bg-green-100 text-green-800',
  sub: 'bg-gray-100 text-gray-800',
};

const sizeClasses = {
  sm: 'px-2 py-0.5 text-xs',
  md: 'px-2.5 py-1 text-sm',
};

export const Badge: React.FC<BadgeProps> = ({ status, size = 'md', variant = 'status' }) => {
  const colorClass = variant === 'type'
    ? (typeColors[status] || 'bg-gray-100 text-gray-800')
    : (statusColors[status] || 'bg-gray-100 text-gray-800');

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${colorClass} ${sizeClasses[size]}`}
    >
      {status}
    </span>
  );
};

export default Badge;
