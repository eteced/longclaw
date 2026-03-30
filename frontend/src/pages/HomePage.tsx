import React, { useEffect, useState } from 'react';
import { Play, CheckCircle, XCircle, Users, Activity } from 'lucide-react';
import { Link } from 'react-router-dom';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type { Task, Agent, DashboardStats } from '../types';
import { formatDistanceToNow } from 'date-fns';
import { zhCN } from 'date-fns/locale';

/**
 * Parse a date string from the backend, treating it as UTC if no timezone info.
 * Backend returns UTC timestamps but may not include timezone marker.
 */
function parseUTCDate(dateStr: string): Date {
  // If the string ends with 'Z' or has timezone info, parse directly
  if (dateStr.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(dateStr)) {
    return new Date(dateStr);
  }
  // Otherwise treat as UTC by appending 'Z'
  return new Date(dateStr + 'Z');
}

interface StatCardProps {
  title: string;
  value: number;
  icon: React.ReactNode;
  color: string;
}

const StatCard: React.FC<StatCardProps> = ({ title, value, icon, color }) => (
  <div className="bg-white rounded-lg shadow p-6">
    <div className="flex items-center justify-between">
      <div>
        <p className="text-sm font-medium text-gray-500">{title}</p>
        <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
      </div>
      <div className={`p-3 rounded-full ${color}`}>{icon}</div>
    </div>
  </div>
);

export const HomePage: React.FC = () => {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [recentTasks, setRecentTasks] = useState<Task[]>([]);
  const [recentAgents, setRecentAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [statsData, tasksData, agentsData] = await Promise.all([
          api.getDashboardStats(),
          api.getTasks({ limit: 5 }),
          api.getAgents({ limit: 5 }),
        ]);
        setStats(statsData);
        setRecentTasks(tasksData.items);
        setRecentAgents(agentsData.items);
      } catch (err) {
        setError('Failed to load dashboard data');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        {error}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <h2 className="text-2xl font-bold text-gray-900">Dashboard Overview</h2>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Running Tasks"
          value={stats?.runningTasks || 0}
          icon={<Play className="w-6 h-6 text-yellow-600" />}
          color="bg-yellow-100"
        />
        <StatCard
          title="Completed Tasks"
          value={stats?.completedTasks || 0}
          icon={<CheckCircle className="w-6 h-6 text-green-600" />}
          color="bg-green-100"
        />
        <StatCard
          title="Terminated Tasks"
          value={stats?.terminatedTasks || 0}
          icon={<XCircle className="w-6 h-6 text-gray-600" />}
          color="bg-gray-100"
        />
        <StatCard
          title="Active Agents"
          value={stats?.activeAgents || 0}
          icon={<Users className="w-6 h-6 text-blue-600" />}
          color="bg-blue-100"
        />
      </div>

      {/* Recent Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Tasks */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-medium text-gray-900">Recent Tasks</h3>
          </div>
          <div className="divide-y divide-gray-200">
            {recentTasks.length === 0 ? (
              <div className="px-6 py-4 text-gray-500">No tasks yet</div>
            ) : (
              recentTasks.map((task) => (
                <Link
                  key={task.id}
                  to={`/tasks/${task.id}`}
                  className="block px-6 py-4 hover:bg-gray-50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {task.title}
                      </p>
                      <p className="text-sm text-gray-500">
                        {formatDistanceToNow(parseUTCDate(task.created_at), { addSuffix: true, locale: zhCN })}
                      </p>
                    </div>
                    <span
                      className={`ml-2 px-2 py-1 text-xs rounded-full ${
                        task.status === 'completed'
                          ? 'bg-green-100 text-green-800'
                          : task.status === 'running'
                          ? 'bg-yellow-100 text-yellow-800'
                          : task.status === 'error'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {task.status}
                    </span>
                  </div>
                </Link>
              ))
            )}
          </div>
          <div className="px-6 py-3 border-t border-gray-200">
            <Link
              to="/tasks"
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              View all tasks &rarr;
            </Link>
          </div>
        </div>

        {/* Recent Agents */}
        <div className="bg-white rounded-lg shadow">
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="text-lg font-medium text-gray-900">Recent Agents</h3>
          </div>
          <div className="divide-y divide-gray-200">
            {recentAgents.length === 0 ? (
              <div className="px-6 py-4 text-gray-500">No agents yet</div>
            ) : (
              recentAgents.map((agent) => (
                <div key={agent.id} className="px-6 py-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      <Activity className="w-4 h-4 text-gray-400 mr-2" />
                      <div>
                        <p className="text-sm font-medium text-gray-900">
                          {agent.name}
                        </p>
                        <p className="text-sm text-gray-500 capitalize">
                          {agent.agent_type}
                        </p>
                      </div>
                    </div>
                    <span
                      className={`px-2 py-1 text-xs rounded-full ${
                        agent.status === 'running'
                          ? 'bg-green-100 text-green-800'
                          : agent.status === 'idle'
                          ? 'bg-gray-100 text-gray-600'
                          : agent.status === 'error'
                          ? 'bg-red-100 text-red-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}
                    >
                      {agent.status}
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="px-6 py-3 border-t border-gray-200">
            <Link
              to="/agents"
              className="text-sm text-blue-600 hover:text-blue-800"
            >
              View all agents &rarr;
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
};

export default HomePage;
