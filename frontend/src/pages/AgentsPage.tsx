import React, { useEffect, useState, useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { MessageSquare, X, ChevronRight, ChevronDown, Users, Cpu, Plus, Edit2, Trash2, StopCircle, Play } from 'lucide-react';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type { Agent, AgentType, AgentStatus, AgentListResponse, Message, Channel } from '../types';
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

const agentTypeOptions: { value: AgentType | ''; label: string }[] = [
  { value: '', label: 'All Types' },
  { value: 'resident', label: 'Resident' },
  { value: 'owner', label: 'Owner' },
  { value: 'worker', label: 'Worker' },
];

const agentStatusOptions: { value: AgentStatus | ''; label: string }[] = [
  { value: '', label: 'All Status' },
  { value: 'idle', label: 'Idle' },
  { value: 'running', label: 'Running' },
  { value: 'paused', label: 'Paused' },
  { value: 'terminated', label: 'Terminated' },
  { value: 'error', label: 'Error' },
];

// Agent type badge colors
const agentTypeColors: Record<AgentType, string> = {
  resident: 'bg-purple-100 text-purple-800',
  owner: 'bg-blue-100 text-blue-800',
  worker: 'bg-green-100 text-green-800',
  sub: 'bg-gray-100 text-gray-800',
};

// Agent status badge colors
const agentStatusColors: Record<AgentStatus, string> = {
  idle: 'bg-gray-100 text-gray-800',
  running: 'bg-blue-100 text-blue-800',
  paused: 'bg-yellow-100 text-yellow-800',
  terminated: 'bg-gray-200 text-gray-600',
  error: 'bg-red-100 text-red-800',
};

interface AgentNode extends Agent {
  children: AgentNode[];
}

export const AgentsPage: React.FC = () => {
  const [searchParams, setSearchParams] = useSearchParams();
  const [agents, setAgents] = useState<AgentListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null);
  const [agentMessages, setAgentMessages] = useState<Message[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [viewMode, setViewMode] = useState<'tree' | 'list'>('tree');

  // Track channels and bound agent IDs
  const [channels, setChannels] = useState<Channel[]>([]);
  const boundAgentIds = useMemo(() => {
    const ids = new Set<string>();
    channels.forEach(ch => {
      if (ch.resident_agent_id) {
        ids.add(ch.resident_agent_id);
      }
    });
    return ids;
  }, [channels]);

  // Create agent dialog state
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createPersonality, setCreatePersonality] = useState('');
  const [creating, setCreating] = useState(false);

  // Rename dialog state
  const [showRenameDialog, setShowRenameDialog] = useState(false);
  const [editingAgent, setEditingAgent] = useState<Agent | null>(null);
  const [renameName, setRenameName] = useState('');
  const [renaming, setRenaming] = useState(false);

  // Auto-expand agents that have children with error status, or have children in general
  useEffect(() => {
    if (agents?.items) {
      const agentsWithChildren = new Set<string>();
      // Build a map to find all parents
      agents.items.forEach(agent => {
        if (agent.parent_agent_id) {
          agentsWithChildren.add(agent.parent_agent_id);
        }
        // Also auto-expand parents of error agents
        if (agent.status === 'error' && agent.parent_agent_id) {
          agentsWithChildren.add(agent.parent_agent_id);
        }
      });
      if (agentsWithChildren.size > 0) {
        setExpandedAgents(prev => new Set([...prev, ...agentsWithChildren]));
      }
    }
  }, [agents?.items]);

  const agentType = searchParams.get('agentType') || '';
  const status = searchParams.get('status') || '';
  const page = parseInt(searchParams.get('page') || '1', 10);
  const pageSize = 100;  // Increased from 50 to ensure all agents are loaded

  useEffect(() => {
    const fetchAgents = async () => {
      try {
        setLoading(true);
        const [data, channelsData] = await Promise.all([
          api.getAgents({
            agent_type: agentType as AgentType || undefined,
            status: status as AgentStatus || undefined,
            limit: pageSize,
            offset: (page - 1) * pageSize,
          }),
          api.getChannels({ limit: 100 }),
        ]);
        setAgents(data);
        setChannels(channelsData.items);
      } catch (err) {
        setError('Failed to load agents');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchAgents();
  }, [agentType, status, page]);

  // Build agent tree structure
  const agentTree = useMemo(() => {
    if (!agents?.items) return [];

    const agentMap = new Map<string, AgentNode>();
    const roots: AgentNode[] = [];

    // First pass: create nodes
    agents.items.forEach(agent => {
      agentMap.set(agent.id, { ...agent, children: [] });
    });

    // Second pass: build tree
    agents.items.forEach(agent => {
      const node = agentMap.get(agent.id)!;
      if (agent.parent_agent_id && agentMap.has(agent.parent_agent_id)) {
        const parent = agentMap.get(agent.parent_agent_id)!;
        parent.children.push(node);
      } else {
        roots.push(node);
      }
    });

    // Sort children by created_at
    const sortChildren = (nodes: AgentNode[]) => {
      nodes.sort((a, b) => parseUTCDate(b.created_at).getTime() - parseUTCDate(a.created_at).getTime());
      nodes.forEach(node => sortChildren(node.children));
    };
    sortChildren(roots);

    return roots;
  }, [agents?.items]);

  const handleViewMessages = async (agent: Agent) => {
    setSelectedAgent(agent);
    setMessagesLoading(true);
    try {
      const messages = await api.getAgentMessages(agent.id, { limit: 50 });
      setAgentMessages(messages);
    } catch (err) {
      console.error(err);
      setAgentMessages([]);
    } finally {
      setMessagesLoading(false);
    }
  };

  const handleCreateAgent = async () => {
    if (!createName.trim()) return;
    setCreating(true);
    try {
      await api.createAgent({
        name: createName.trim(),
        personality: createPersonality.trim() || undefined,
      });
      setShowCreateDialog(false);
      setCreateName('');
      setCreatePersonality('');
      // Refresh agents list
      const data = await api.getAgents({
        agent_type: agentType as AgentType || undefined,
        status: status as AgentStatus || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setAgents(data);
    } catch (err) {
      console.error(err);
      alert('Failed to create agent');
    } finally {
      setCreating(false);
    }
  };

  const handleRenameAgent = async () => {
    if (!editingAgent || !renameName.trim()) return;
    setRenaming(true);
    try {
      await api.updateAgent(editingAgent.id, {
        name: renameName.trim(),
      });
      setShowRenameDialog(false);
      setEditingAgent(null);
      setRenameName('');
      // Refresh agents list
      const data = await api.getAgents({
        agent_type: agentType as AgentType || undefined,
        status: status as AgentStatus || undefined,
        limit: pageSize,
        offset: (page - 1) * pageSize,
      });
      setAgents(data);
    } catch (err) {
      console.error(err);
      alert('Failed to rename agent');
    } finally {
      setRenaming(false);
    }
  };

  const openRenameDialog = (agent: Agent) => {
    setEditingAgent(agent);
    setRenameName(agent.name);
    setShowRenameDialog(true);
  };

  const handleTerminateAgent = async (agent: Agent) => {
    if (!confirm(`Are you sure you want to terminate agent "${agent.name}"?`)) return;
    try {
      await api.terminateAgent(agent.id);
      // Refresh agents list
      const [data, channelsData] = await Promise.all([
        api.getAgents({
          agent_type: agentType as AgentType || undefined,
          status: status as AgentStatus || undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }),
        api.getChannels({ limit: 100 }),
      ]);
      setAgents(data);
      setChannels(channelsData.items);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to terminate agent');
    }
  };

  const handleStartAgent = async (agent: Agent) => {
    try {
      await api.startAgent(agent.id);
      // Refresh agents list
      const [data, channelsData] = await Promise.all([
        api.getAgents({
          agent_type: agentType as AgentType || undefined,
          status: status as AgentStatus || undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }),
        api.getChannels({ limit: 100 }),
      ]);
      setAgents(data);
      setChannels(channelsData.items);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to start agent');
    }
  };

  const handleDeleteAgent = async (agent: Agent) => {
    if (!confirm(`Are you sure you want to delete agent "${agent.name}"? This action cannot be undone.`)) return;
    try {
      await api.deleteAgent(agent.id);
      // Refresh agents list
      const [data, channelsData] = await Promise.all([
        api.getAgents({
          agent_type: agentType as AgentType || undefined,
          status: status as AgentStatus || undefined,
          limit: pageSize,
          offset: (page - 1) * pageSize,
        }),
        api.getChannels({ limit: 100 }),
      ]);
      setAgents(data);
      setChannels(channelsData.items);
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Failed to delete agent');
    }
  };

  const toggleExpand = (agentId: string) => {
    setExpandedAgents(prev => {
      const next = new Set(prev);
      if (next.has(agentId)) {
        next.delete(agentId);
      } else {
        next.add(agentId);
      }
      return next;
    });
  };

  const updateParams = (updates: Record<string, string>) => {
    const newParams = new URLSearchParams(searchParams);
    Object.entries(updates).forEach(([key, value]) => {
      if (value) {
        newParams.set(key, value);
      } else {
        newParams.delete(key);
      }
    });
    setSearchParams(newParams);
  };

  const totalPages = agents ? Math.ceil(agents.total / pageSize) : 0;

  // Render agent tree node
  const renderAgentNode = (agent: AgentNode, depth: number = 0) => {
    const hasChildren = agent.children.length > 0;
    const isExpanded = expandedAgents.has(agent.id);
    const indent = depth * 24;

    return (
      <React.Fragment key={agent.id}>
        <tr className="hover:bg-gray-50 border-b">
          <td className="px-6 py-4" style={{ paddingLeft: `${indent + 16}px` }}>
            <div className="flex items-center gap-2">
              {hasChildren && (
                <button
                  onClick={() => toggleExpand(agent.id)}
                  className="p-0.5 hover:bg-gray-200 rounded"
                >
                  {isExpanded ? (
                    <ChevronDown className="w-4 h-4 text-gray-500" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-gray-500" />
                  )}
                </button>
              )}
              {!hasChildren && <span className="w-5" />}
              <div className="text-sm font-medium text-gray-900">
                {agent.name}
              </div>
            </div>
          </td>
          <td className="px-6 py-4 whitespace-nowrap">
            <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${agentTypeColors[agent.agent_type]}`}>
              {agent.agent_type}
            </span>
          </td>
          <td className="px-6 py-4 whitespace-nowrap">
            <div className="flex flex-col">
              <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${agentStatusColors[agent.status]}`}>
                {agent.status}
              </span>
              {agent.status === 'error' && agent.error_message && (
                <span className="mt-1 text-xs text-red-600 max-w-xs truncate" title={agent.error_message}>
                  {agent.error_message}
                </span>
              )}
            </div>
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
            {agent.parent_agent_id ? (
              <span className="text-gray-400" title={agent.parent_agent_id}>
                Parent: {agent.parent_agent_id.slice(0, 8)}...
              </span>
            ) : (
              <span className="text-gray-300">-</span>
            )}
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
            {agent.task_id ? (
              <Link
                to={`/tasks/${agent.task_id}`}
                className="text-blue-600 hover:text-blue-800"
              >
                View Task
              </Link>
            ) : (
              '-'
            )}
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
            <span title={format(parseUTCDate(agent.created_at), 'PPpp')}>
              {formatDistanceToNow(parseUTCDate(agent.created_at), { addSuffix: true, locale: zhCN })}
            </span>
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-sm">
            {agent.model_assignment ? (
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-800">
                <Cpu className="w-3 h-3 mr-1" />
                {agent.model_assignment.provider}/{agent.model_assignment.model}
                {agent.model_assignment.slot_index !== null && (
                  <span className="ml-1 text-indigo-600">#{agent.model_assignment.slot_index}</span>
                )}
              </span>
            ) : (
              <span className="text-gray-300">-</span>
            )}
          </td>
          <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
            <button
              onClick={() => openRenameDialog(agent)}
              className="text-blue-600 hover:text-blue-800 flex items-center gap-1 mr-3"
            >
              <Edit2 className="w-4 h-4" />
              Rename
            </button>
            {agent.agent_type === 'resident' && (
              <>
                {/* Start button for terminated agents that are bound to a channel */}
                {agent.status === 'terminated' && boundAgentIds.has(agent.id) && (
                  <button
                    onClick={() => handleStartAgent(agent)}
                    className="text-green-600 hover:text-green-800 flex items-center gap-1 mr-3"
                    title="Start this agent"
                  >
                    <Play className="w-4 h-4" />
                    Start
                  </button>
                )}
                {/* Terminate button for non-terminated agents not bound to a channel */}
                {!boundAgentIds.has(agent.id) && agent.status !== 'terminated' && (
                  <button
                    onClick={() => handleTerminateAgent(agent)}
                    className="text-orange-600 hover:text-orange-800 flex items-center gap-1 mr-3"
                    title="Terminate this agent"
                  >
                    <StopCircle className="w-4 h-4" />
                    Terminate
                  </button>
                )}
                {/* Delete button for terminated agents not bound to a channel */}
                {!boundAgentIds.has(agent.id) && agent.status === 'terminated' && (
                  <button
                    onClick={() => handleDeleteAgent(agent)}
                    className="text-red-600 hover:text-red-800 flex items-center gap-1 mr-3"
                    title="Delete this agent"
                  >
                    <Trash2 className="w-4 h-4" />
                    Delete
                  </button>
                )}
              </>
            )}
            <button
              onClick={() => handleViewMessages(agent)}
              className="text-blue-600 hover:text-blue-800 flex items-center gap-1"
            >
              <MessageSquare className="w-4 h-4" />
              Messages
            </button>
          </td>
        </tr>
        {isExpanded && hasChildren && agent.children.map(child => renderAgentNode(child, depth + 1))}
      </React.Fragment>
    );
  };

  if (loading && !agents) {
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
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Agents</h2>
        <div className="flex items-center gap-4">
          <button
            onClick={() => setShowCreateDialog(true)}
            className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            <Plus className="w-4 h-4" />
            Create Resident Agent
          </button>
          <div className="flex items-center gap-2 bg-gray-100 rounded-lg p-1">
            <button
              onClick={() => setViewMode('tree')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md ${
                viewMode === 'tree'
                  ? 'bg-white text-gray-900 shadow'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              <Users className="w-4 h-4 inline mr-1" />
              Tree View
            </button>
            <button
              onClick={() => setViewMode('list')}
              className={`px-3 py-1.5 text-sm font-medium rounded-md ${
                viewMode === 'list'
                  ? 'bg-white text-gray-900 shadow'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              List View
            </button>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Type:</label>
            <select
              value={agentType}
              onChange={(e) => updateParams({ agentType: e.target.value, page: '1' })}
              className="block rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            >
              {agentTypeOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Status:</label>
            <select
              value={status}
              onChange={(e) => updateParams({ status: e.target.value, page: '1' })}
              className="block rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
            >
              {agentStatusOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Agents Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Name
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Type
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Parent Agent
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Task
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Created
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Model
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {agents?.items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-6 py-4 text-center text-gray-500">
                    No agents found
                  </td>
                </tr>
              ) : viewMode === 'tree' ? (
                agentTree.map(agent => renderAgentNode(agent))
              ) : (
                agents?.items.map((agent) => (
                  <tr key={agent.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900">
                        {agent.name}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${agentTypeColors[agent.agent_type]}`}>
                        {agent.agent_type}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex flex-col">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${agentStatusColors[agent.status]}`}>
                          {agent.status}
                        </span>
                        {agent.status === 'error' && agent.error_message && (
                          <span className="mt-1 text-xs text-red-600 max-w-xs truncate" title={agent.error_message}>
                            {agent.error_message}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {agent.parent_agent_id ? (
                        <span className="text-gray-400" title={agent.parent_agent_id}>
                          {agent.parent_agent_id.slice(0, 8)}...
                        </span>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {agent.task_id ? (
                        <Link
                          to={`/tasks/${agent.task_id}`}
                          className="text-blue-600 hover:text-blue-800"
                        >
                          View Task
                        </Link>
                      ) : (
                        '-'
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      <span title={format(parseUTCDate(agent.created_at), 'PPpp')}>
                        {formatDistanceToNow(parseUTCDate(agent.created_at), { addSuffix: true, locale: zhCN })}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {agent.model_assignment ? (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-indigo-100 text-indigo-800">
                          <Cpu className="w-3 h-3 mr-1" />
                          {agent.model_assignment.provider}/{agent.model_assignment.model}
                          {agent.model_assignment.slot_index !== null && (
                            <span className="ml-1 text-indigo-600">#{agent.model_assignment.slot_index}</span>
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-300">-</span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => openRenameDialog(agent)}
                        className="text-blue-600 hover:text-blue-800 flex items-center gap-1 mr-3"
                      >
                        <Edit2 className="w-4 h-4" />
                        Rename
                      </button>
                      <button
                        onClick={() => handleViewMessages(agent)}
                        className="text-blue-600 hover:text-blue-800 flex items-center gap-1"
                      >
                        <MessageSquare className="w-4 h-4" />
                        Messages
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {agents && agents.total > pageSize && (
          <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
            <div className="text-sm text-gray-700">
              Showing{' '}
              <span className="font-medium">{(page - 1) * pageSize + 1}</span>
              {' '}-{' '}
              <span className="font-medium">
                {Math.min(page * pageSize, agents.total)}
              </span>{' '}
              of <span className="font-medium">{agents.total}</span> results
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => updateParams({ page: String(page - 1) })}
                disabled={page === 1}
                className="px-3 py-1 border rounded text-sm disabled:opacity-50"
              >
                Previous
              </button>
              <button
                onClick={() => updateParams({ page: String(page + 1) })}
                disabled={page >= totalPages}
                className="px-3 py-1 border rounded text-sm disabled:opacity-50"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Messages Modal */}
      {selectedAgent && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">
                Messages for {selectedAgent.name}
              </h3>
              <button
                onClick={() => setSelectedAgent(null)}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {messagesLoading ? (
                <LoadingSpinner />
              ) : agentMessages.length === 0 ? (
                <p className="text-center text-gray-500">No messages found</p>
              ) : (
                <div className="space-y-4">
                  {agentMessages.map((msg) => (
                    <div key={msg.id} className="border rounded-lg p-3">
                      <div className="flex items-center justify-between text-sm mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium capitalize">{msg.sender_type}</span>
                          <span className="text-gray-400">&rarr;</span>
                          <span className="font-medium capitalize">{msg.receiver_type}</span>
                        </div>
                        <span className="text-gray-500 text-xs">
                          {format(parseUTCDate(msg.created_at), 'PPpp')}
                        </span>
                      </div>
                      <p className="text-sm text-gray-700 whitespace-pre-wrap">
                        {msg.content}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Create Agent Dialog */}
      {showCreateDialog && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">Create Resident Agent</h3>
              <button
                onClick={() => {
                  setShowCreateDialog(false);
                  setCreateName('');
                  setCreatePersonality('');
                }}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="Enter agent name"
                  autoFocus
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Personality (optional)
                </label>
                <textarea
                  value={createPersonality}
                  onChange={(e) => setCreatePersonality(e.target.value)}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="Enter agent personality description"
                  rows={3}
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 p-4 border-t">
              <button
                onClick={() => {
                  setShowCreateDialog(false);
                  setCreateName('');
                  setCreatePersonality('');
                }}
                className="px-4 py-2 border rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreateAgent}
                disabled={!createName.trim() || creating}
                className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {creating ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rename Agent Dialog */}
      {showRenameDialog && editingAgent && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">Rename Agent</h3>
              <button
                onClick={() => {
                  setShowRenameDialog(false);
                  setEditingAgent(null);
                  setRenameName('');
                }}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-4 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={renameName}
                  onChange={(e) => setRenameName(e.target.value)}
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                  placeholder="Enter new name"
                  autoFocus
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 p-4 border-t">
              <button
                onClick={() => {
                  setShowRenameDialog(false);
                  setEditingAgent(null);
                  setRenameName('');
                }}
                className="px-4 py-2 border rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleRenameAgent}
                disabled={!renameName.trim() || renaming}
                className="px-4 py-2 bg-blue-600 text-white rounded-md text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
              >
                {renaming ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AgentsPage;
