import React, { useState, useEffect } from 'react';
import {
  Activity,
  Users,
  MessageSquare,
  Send,
  RefreshCw,
  ChevronDown,
  ChevronRight,
  AlertCircle,
  CheckCircle,
  Clock,
  Terminal,
} from 'lucide-react';
import { api } from '../services/api';

interface AgentSummary {
  id: string;
  name: string;
  agent_type: string;
  status: string;
  task_id: string | null;
  parent_agent_id: string | null;
  created_at: string;
  updated_at: string | null;
}

interface ChannelSummary {
  id: string;
  channel_type: string;
  resident_agent_id: string | null;
  target_agent_id: string | null;
  is_active: boolean;
}

interface MessageSummary {
  id: string;
  sender_type: string;
  sender_id: string | null;
  receiver_type: string;
  receiver_id: string | null;
  content: string;
  created_at: string;
}

interface ConsoleOverview {
  total_agents: number;
  running_agents: number;
  total_channels: number;
  active_channels: number;
  total_tasks: number;
  running_tasks: number;
  recent_messages: number;
}

export const ConsolePage: React.FC = () => {
  const [overview, setOverview] = useState<ConsoleOverview | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [channels, setChannels] = useState<ChannelSummary[]>([]);
  const [messages, setMessages] = useState<MessageSummary[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [interventionMessage, setInterventionMessage] = useState('');
  const [interventionTarget, setInterventionTarget] = useState<{ type: string; id: string } | null>(null);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set(['agents', 'channels']));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const apiKey = api.getApiKey();
      const headers = { 'X-API-Key': apiKey || '' };

      const [overviewRes, agentsRes, channelsRes, messagesRes] = await Promise.all([
        fetch('/api/console/overview', { headers }),
        fetch('/api/console/agents', { headers }),
        fetch('/api/console/channels', { headers }),
        fetch('/api/console/messages', { headers }),
      ]);

      if (overviewRes.ok) setOverview(await overviewRes.json());
      if (agentsRes.ok) setAgents(await agentsRes.json());
      if (channelsRes.ok) setChannels(await channelsRes.json());
      if (messagesRes.ok) setMessages(await messagesRes.json());
    } catch (err) {
      setError('Failed to load console data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    // Refresh every 10 seconds
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, []);

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(section)) {
        newSet.delete(section);
      } else {
        newSet.add(section);
      }
      return newSet;
    });
  };

  const sendIntervention = async () => {
    if (!interventionTarget || !interventionMessage.trim()) return;

    try {
      const apiKey = api.getApiKey();
      const response = await fetch('/api/console/intervene', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': apiKey || '',
        },
        body: JSON.stringify({
          message: interventionMessage,
          target_type: interventionTarget.type,
          target_id: interventionTarget.id,
        }),
      });

      if (response.ok) {
        setInterventionMessage('');
        setInterventionTarget(null);
        fetchData();
      } else {
        const data = await response.json();
        setError(data.detail || 'Failed to send intervention');
      }
    } catch (err) {
      setError('Failed to send intervention');
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status.toLowerCase()) {
      case 'running':
        return <Activity className="w-4 h-4 text-green-500" />;
      case 'idle':
        return <Clock className="w-4 h-4 text-yellow-500" />;
      case 'error':
        return <AlertCircle className="w-4 h-4 text-red-500" />;
      default:
        return <CheckCircle className="w-4 h-4 text-gray-500" />;
    }
  };

  const formatTime = (dateStr: string | null | undefined) => {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center">
            <Terminal className="w-6 h-6 text-blue-600 mr-2" />
            <h1 className="text-2xl font-bold text-gray-900">控制台</h1>
          </div>
          <button
            onClick={fetchData}
            disabled={loading}
            className="flex items-center px-3 py-1 text-sm bg-blue-50 text-blue-600 rounded hover:bg-blue-100 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </button>
        </div>

        {/* Overview Stats */}
        {overview && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-blue-50 rounded-lg p-4">
              <div className="flex items-center">
                <Users className="w-5 h-5 text-blue-500 mr-2" />
                <span className="text-sm text-gray-600">Agent</span>
              </div>
              <div className="mt-2">
                <span className="text-2xl font-bold text-blue-600">{overview.running_agents}</span>
                <span className="text-sm text-gray-500"> / {overview.total_agents} 运行中</span>
              </div>
            </div>

            <div className="bg-green-50 rounded-lg p-4">
              <div className="flex items-center">
                <MessageSquare className="w-5 h-5 text-green-500 mr-2" />
                <span className="text-sm text-gray-600">Channel</span>
              </div>
              <div className="mt-2">
                <span className="text-2xl font-bold text-green-600">{overview.active_channels}</span>
                <span className="text-sm text-gray-500"> / {overview.total_channels} 活跃</span>
              </div>
            </div>

            <div className="bg-purple-50 rounded-lg p-4">
              <div className="flex items-center">
                <Activity className="w-5 h-5 text-purple-500 mr-2" />
                <span className="text-sm text-gray-600">任务</span>
              </div>
              <div className="mt-2">
                <span className="text-2xl font-bold text-purple-600">{overview.running_tasks}</span>
                <span className="text-sm text-gray-500"> / {overview.total_tasks} 运行中</span>
              </div>
            </div>

            <div className="bg-orange-50 rounded-lg p-4">
              <div className="flex items-center">
                <Send className="w-5 h-5 text-orange-500 mr-2" />
                <span className="text-sm text-gray-600">消息</span>
              </div>
              <div className="mt-2">
                <span className="text-2xl font-bold text-orange-600">{overview.recent_messages}</span>
                <span className="text-sm text-gray-500"> 最近1小时</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 text-red-600 px-4 py-2 rounded-lg text-sm">
          {error}
        </div>
      )}

      {/* Intervention Panel */}
      {interventionTarget && (
        <div className="bg-yellow-50 rounded-lg shadow p-4">
          <h3 className="text-sm font-medium text-yellow-800 mb-2">
            发送干预消息到 {interventionTarget.type}: {interventionTarget.id.substring(0, 8)}...
          </h3>
          <div className="flex space-x-2">
            <input
              type="text"
              value={interventionMessage}
              onChange={(e) => setInterventionMessage(e.target.value)}
              placeholder="输入干预消息..."
              className="flex-1 border border-yellow-300 rounded px-3 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <button
              onClick={sendIntervention}
              disabled={!interventionMessage.trim()}
              className="px-3 py-1 bg-yellow-500 text-white rounded text-sm hover:bg-yellow-600 disabled:opacity-50"
            >
              发送
            </button>
            <button
              onClick={() => setInterventionTarget(null)}
              className="px-3 py-1 bg-gray-200 text-gray-700 rounded text-sm hover:bg-gray-300"
            >
              取消
            </button>
          </div>
        </div>
      )}

      {/* Agents Section */}
      <div className="bg-white rounded-lg shadow">
        <button
          onClick={() => toggleSection('agents')}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
        >
          <div className="flex items-center">
            {expandedSections.has('agents') ? (
              <ChevronDown className="w-4 h-4 mr-2" />
            ) : (
              <ChevronRight className="w-4 h-4 mr-2" />
            )}
            <Users className="w-5 h-5 text-blue-600 mr-2" />
            <span className="font-medium">Agents ({agents.length})</span>
          </div>
        </button>

        {expandedSections.has('agents') && (
          <div className="border-t divide-y">
            {agents.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400">暂无 Agent</div>
            ) : (
              agents.map((agent) => (
                <div
                  key={agent.id}
                  className="px-4 py-3 hover:bg-gray-50 cursor-pointer"
                  onClick={() => setSelectedAgent(selectedAgent === agent.id ? null : agent.id)}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      {getStatusIcon(agent.status)}
                      <span className="ml-2 font-medium">{agent.name}</span>
                      <span className="ml-2 text-xs text-gray-500">({agent.agent_type})</span>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span className="text-xs text-gray-400">{formatTime(agent.updated_at)}</span>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setInterventionTarget({ type: 'agent', id: agent.id });
                        }}
                        className="text-xs text-blue-500 hover:text-blue-700"
                      >
                        干预
                      </button>
                    </div>
                  </div>
                  {selectedAgent === agent.id && (
                    <div className="mt-2 text-xs text-gray-500 pl-6">
                      <div>ID: {agent.id}</div>
                      <div>Task: {agent.task_id || '-'}</div>
                      <div>Parent: {agent.parent_agent_id || '-'}</div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Channels Section */}
      <div className="bg-white rounded-lg shadow">
        <button
          onClick={() => toggleSection('channels')}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
        >
          <div className="flex items-center">
            {expandedSections.has('channels') ? (
              <ChevronDown className="w-4 h-4 mr-2" />
            ) : (
              <ChevronRight className="w-4 h-4 mr-2" />
            )}
            <MessageSquare className="w-5 h-5 text-green-600 mr-2" />
            <span className="font-medium">Channels ({channels.length})</span>
          </div>
        </button>

        {expandedSections.has('channels') && (
          <div className="border-t divide-y">
            {channels.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400">暂无 Channel</div>
            ) : (
              channels.map((channel) => (
                <div key={channel.id} className="px-4 py-3 hover:bg-gray-50">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center">
                      <span
                        className={`w-2 h-2 rounded-full mr-2 ${
                          channel.is_active ? 'bg-green-500' : 'bg-gray-300'
                        }`}
                      />
                      <span className="font-medium">{channel.channel_type}</span>
                      <span className="ml-2 text-xs text-gray-500">({channel.id.substring(0, 8)})</span>
                    </div>
                    <button
                      onClick={() => setInterventionTarget({ type: 'channel', id: channel.id })}
                      className="text-xs text-blue-500 hover:text-blue-700"
                    >
                      干预
                    </button>
                  </div>
                  <div className="mt-1 text-xs text-gray-500">
                    Resident: {channel.resident_agent_id?.substring(0, 8) || '-'} |
                    Target: {channel.target_agent_id?.substring(0, 8) || '-'}
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Messages Section */}
      <div className="bg-white rounded-lg shadow">
        <button
          onClick={() => toggleSection('messages')}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-50"
        >
          <div className="flex items-center">
            {expandedSections.has('messages') ? (
              <ChevronDown className="w-4 h-4 mr-2" />
            ) : (
              <ChevronRight className="w-4 h-4 mr-2" />
            )}
            <Send className="w-5 h-5 text-orange-600 mr-2" />
            <span className="font-medium">最近消息 ({messages.length})</span>
          </div>
        </button>

        {expandedSections.has('messages') && (
          <div className="border-t divide-y max-h-96 overflow-y-auto">
            {messages.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-400">暂无消息</div>
            ) : (
              messages.map((msg) => (
                <div key={msg.id} className="px-4 py-2 text-sm">
                  <div className="flex items-center justify-between text-xs text-gray-500">
                    <span>
                      {msg.sender_type} → {msg.receiver_type}
                    </span>
                    <span>{formatTime(msg.created_at)}</span>
                  </div>
                  <div className="mt-1 text-gray-700 truncate">{msg.content}</div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ConsolePage;
