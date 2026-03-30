import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { StopCircle, ArrowLeft, User, MessageSquare, GitBranch } from 'lucide-react';
import { api } from '../services/api';
import { Badge, ProgressBar, LoadingSpinner } from '../components';
import type { TaskDetail, Message, Agent } from '../types';
import { formatDistanceToNow, format } from 'date-fns';
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

type TabType = 'subtasks' | 'messages' | 'agents';

export const TaskDetailPage: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>('subtasks');

  useEffect(() => {
    const fetchTask = async () => {
      if (!id) return;

      try {
        setLoading(true);
        const [taskData, messagesData, agentsData] = await Promise.all([
          api.getTask(id),
          api.getTaskMessages(id, { limit: 100 }),
          api.getAgents({ task_id: id, limit: 50 }),
        ]);
        setTask(taskData);
        setMessages(messagesData.items);
        setAgents(agentsData.items);
      } catch (err) {
        setError('Failed to load task details');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchTask();
  }, [id]);

  const handleTerminate = async () => {
    if (!id || !confirm('Are you sure you want to terminate this task?')) return;

    try {
      const updatedTask = await api.terminateTask(id);
      setTask({ ...task!, ...updatedTask } as TaskDetail);
    } catch (err) {
      alert('Failed to terminate task');
      console.error(err);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error || !task) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        {error || 'Task not found'}
      </div>
    );
  }

  const completedSubtasks = task.subtasks.filter(s => s.status === 'completed').length;
  const runningSubtasks = task.subtasks.filter(s => s.status === 'running').length;
  const totalSubtasks = task.subtasks.length;
  // Progress includes completed + running (in progress)
  const progressCompleted = completedSubtasks;
  const progressRunning = runningSubtasks;

  // Build agent tree
  const ownerAgent = agents.find(a => a.agent_type === 'owner');
  const workerAgents = agents.filter(a => a.agent_type === 'worker');
  const residentAgent = agents.find(a => a.agent_type === 'resident');

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            to="/tasks"
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h2 className="text-2xl font-bold text-gray-900">{task.title}</h2>
            <p className="text-sm text-gray-500">ID: {task.id}</p>
          </div>
        </div>
        {task.status !== 'terminated' && task.status !== 'completed' && (
          <button
            onClick={handleTerminate}
            className="flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
          >
            <StopCircle className="w-4 h-4" />
            Terminate Task
          </button>
        )}
      </div>

      {/* Task Info Card */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div>
            <label className="block text-sm font-medium text-gray-500">Status</label>
            <div className="mt-1">
              <Badge status={task.status} />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500">Created</label>
            <p className="mt-1 text-sm text-gray-900">
              {format(parseUTCDate(task.created_at), 'PPpp')}
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500">Updated</label>
            <p className="mt-1 text-sm text-gray-900">
              {formatDistanceToNow(parseUTCDate(task.updated_at), { addSuffix: true, locale: zhCN })}
            </p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-500">Progress</label>
            <div className="mt-1">
              <ProgressBar completed={progressCompleted} running={progressRunning} total={totalSubtasks} />
            </div>
          </div>
        </div>

        {task.description && (
          <div className="mt-6">
            <label className="block text-sm font-medium text-gray-500">Description</label>
            <p className="mt-1 text-gray-900">{task.description}</p>
          </div>
        )}

        {task.summary && (
          <div className="mt-6">
            <label className="block text-sm font-medium text-gray-500">Summary</label>
            <p className="mt-1 text-gray-900 bg-gray-50 p-3 rounded-lg">{task.summary}</p>
          </div>
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('subtasks')}
            className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'subtasks'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <GitBranch className="w-4 h-4" />
            Subtasks ({task.subtasks.length})
          </button>
          <button
            onClick={() => setActiveTab('messages')}
            className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'messages'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <MessageSquare className="w-4 h-4" />
            Messages ({messages.length})
          </button>
          <button
            onClick={() => setActiveTab('agents')}
            className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'agents'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <User className="w-4 h-4" />
            Agents ({agents.length})
          </button>
        </nav>
      </div>

      {/* Tab Content */}
      <div className="bg-white rounded-lg shadow">
        {activeTab === 'subtasks' && (
          <div className="divide-y divide-gray-200">
            {task.subtasks.length === 0 ? (
              <div className="p-6 text-center text-gray-500">No subtasks yet</div>
            ) : (
              task.subtasks.map((subtask) => (
                <div key={subtask.id} className="p-6">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-gray-500">
                          #{subtask.order_index ?? '?'}
                        </span>
                        <h4 className="text-sm font-medium text-gray-900">
                          {subtask.title}
                        </h4>
                        <Badge status={subtask.status} size="sm" />
                      </div>
                      {subtask.description && (
                        <p className="mt-1 text-sm text-gray-600">{subtask.description}</p>
                      )}
                      {subtask.summary && (
                        <p className="mt-2 text-sm text-gray-700 bg-gray-50 p-2 rounded">
                          {subtask.summary}
                        </p>
                      )}
                      {subtask.worker_agent_id && (
                        <p className="mt-1 text-xs text-gray-500">
                          Worker: {subtask.worker_agent_id}
                        </p>
                      )}
                    </div>
                    <div className="text-xs text-gray-500">
                      {subtask.completed_at
                        ? formatDistanceToNow(parseUTCDate(subtask.completed_at), { addSuffix: true, locale: zhCN })
                        : formatDistanceToNow(parseUTCDate(subtask.created_at), { addSuffix: true, locale: zhCN })}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'messages' && (
          <div className="divide-y divide-gray-200">
            {messages.length === 0 ? (
              <div className="p-6 text-center text-gray-500">No messages yet</div>
            ) : (
              messages
                .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
                .map((message) => (
                  <div key={message.id} className="p-6">
                    <div className="flex items-start gap-4">
                      <div className="flex-shrink-0">
                        <div className="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center">
                          <MessageSquare className="w-4 h-4 text-gray-500" />
                        </div>
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900 capitalize">
                            {message.sender_type}
                          </span>
                          <span className="text-gray-400">&rarr;</span>
                          <span className="text-sm font-medium text-gray-900 capitalize">
                            {message.receiver_type}
                          </span>
                          <span className="text-xs text-gray-500">
                            {format(parseUTCDate(message.created_at), 'PPpp')}
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-gray-700 whitespace-pre-wrap">
                          {message.content}
                        </p>
                      </div>
                    </div>
                  </div>
                ))
            )}
          </div>
        )}

        {activeTab === 'agents' && (
          <div className="p-6">
            {agents.length === 0 ? (
              <div className="text-center text-gray-500">No agents yet</div>
            ) : (
              <div className="space-y-6">
                {/* Agent Hierarchy Visualization */}
                <div className="mb-4 p-4 bg-gray-50 rounded-lg">
                  <h4 className="text-sm font-medium text-gray-700 mb-2">Agent 调用链路</h4>
                  <div className="text-sm text-gray-600">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">Resident Agent</span>
                      <span className="text-gray-400">→</span>
                      <span className="font-medium">Owner Agent</span>
                      <span className="text-gray-400">→</span>
                      <span className="font-medium">Worker Agents</span>
                    </div>
                  </div>
                </div>

                {/* Resident Agent */}
                {residentAgent && (
                  <div className="border-2 border-purple-200 rounded-lg p-4 bg-purple-50">
                    <div className="flex items-center gap-2 mb-2">
                      <Badge status={residentAgent.agent_type} variant="type" />
                      <span className="font-medium text-gray-900">{residentAgent.name}</span>
                      <Badge status={residentAgent.status} size="sm" />
                    </div>
                    <div className="text-xs text-gray-500 mb-2">
                      ID: {residentAgent.id}
                    </div>
                    {residentAgent.personality && (
                      <p className="text-sm text-gray-600">{residentAgent.personality}</p>
                    )}
                  </div>
                )}

                {/* Owner Agent */}
                {ownerAgent && (
                  <div className="ml-8 border-l-4 border-blue-300 pl-4">
                    <div className="border-2 border-blue-200 rounded-lg p-4 bg-blue-50">
                      <div className="flex items-center gap-2 mb-2">
                        <Badge status={ownerAgent.agent_type} variant="type" />
                        <span className="font-medium text-gray-900">{ownerAgent.name}</span>
                        <Badge status={ownerAgent.status} size="sm" />
                      </div>
                      <div className="text-xs text-gray-500 mb-2">
                        ID: {ownerAgent.id} | Parent: {ownerAgent.parent_agent_id?.slice(0, 8)}...
                      </div>
                      {ownerAgent.personality && (
                        <p className="text-sm text-gray-600">{ownerAgent.personality}</p>
                      )}
                    </div>

                    {/* Worker Agents */}
                    {workerAgents.length > 0 && (
                      <div className="mt-4 space-y-3">
                        <h5 className="text-sm font-medium text-gray-700">
                          Worker Agents ({workerAgents.length})
                        </h5>
                        {workerAgents.map((worker) => (
                          <div key={worker.id} className="ml-4 border-l-4 border-green-300 pl-4">
                            <div className="border-2 border-green-200 rounded-lg p-4 bg-green-50">
                              <div className="flex items-center gap-2 mb-2">
                                <Badge status={worker.agent_type} variant="type" />
                                <span className="font-medium text-gray-900">{worker.name}</span>
                                <Badge status={worker.status} size="sm" />
                              </div>
                              <div className="text-xs text-gray-500">
                                ID: {worker.id.slice(0, 8)}... | Parent: {worker.parent_agent_id?.slice(0, 8)}...
                              </div>
                              {worker.error_message && (
                                <div className="mt-2 text-sm text-red-600 bg-red-50 p-2 rounded">
                                  Error: {worker.error_message}
                                </div>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* No Owner Agent but has workers */}
                {!ownerAgent && workerAgents.length > 0 && (
                  <div className="ml-8 border-l-4 border-gray-300 pl-4">
                    <h5 className="text-sm font-medium text-gray-700 mb-3">
                      Worker Agents ({workerAgents.length})
                    </h5>
                    {workerAgents.map((worker) => (
                      <div key={worker.id} className="mb-3 border-2 border-green-200 rounded-lg p-4 bg-green-50">
                        <div className="flex items-center gap-2 mb-2">
                          <Badge status={worker.agent_type} variant="type" />
                          <span className="font-medium text-gray-900">{worker.name}</span>
                          <Badge status={worker.status} size="sm" />
                        </div>
                        <div className="text-xs text-gray-500">
                          ID: {worker.id.slice(0, 8)}... | Parent: {worker.parent_agent_id?.slice(0, 8)}...
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default TaskDetailPage;
