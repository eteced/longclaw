import React, { useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, X } from 'lucide-react';
import { api } from '../services/api';
import { Badge, LoadingSpinner } from '../components';
import type { Channel, ChannelType, Agent } from '../types';
import { formatDistanceToNow, format } from 'date-fns';

const channelTypeOptions: ChannelType[] = ['qqbot', 'telegram', 'web', 'api'];

interface ChannelFormData {
  channel_type: ChannelType;
  config: Record<string, unknown>;
  resident_agent_id: string;
  is_active: boolean;
}

const initialFormData: ChannelFormData = {
  channel_type: 'web',
  config: {},
  resident_agent_id: '',
  is_active: true,
};

export const ChannelsPage: React.FC = () => {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [editingChannel, setEditingChannel] = useState<Channel | null>(null);
  const [formData, setFormData] = useState<ChannelFormData>(initialFormData);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [channelsData, agentsData] = await Promise.all([
          api.getChannels({ limit: 100 }),
          api.getAgents({ agent_type: 'resident', limit: 100 }),
        ]);
        setChannels(channelsData.items);
        setAgents(agentsData.items);
      } catch (err) {
        setError('Failed to load channels');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleOpenModal = (channel?: Channel) => {
    if (channel) {
      setEditingChannel(channel);
      setFormData({
        channel_type: channel.channel_type,
        config: channel.config || {},
        resident_agent_id: channel.resident_agent_id || '',
        is_active: channel.is_active,
      });
    } else {
      setEditingChannel(null);
      setFormData(initialFormData);
    }
    setShowModal(true);
  };

  const handleCloseModal = () => {
    setShowModal(false);
    setEditingChannel(null);
    setFormData(initialFormData);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);

    try {
      if (editingChannel) {
        const updated = await api.updateChannel(editingChannel.id, {
          config: formData.config,
          resident_agent_id: formData.resident_agent_id || undefined,
          is_active: formData.is_active,
        });
        setChannels(channels.map((c) => (c.id === updated.id ? updated : c)));
      } else {
        const created = await api.createChannel({
          channel_type: formData.channel_type,
          config: formData.config,
          resident_agent_id: formData.resident_agent_id || undefined,
        });
        setChannels([created, ...channels]);
      }
      handleCloseModal();
    } catch (err) {
      alert('Failed to save channel');
      console.error(err);
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (channelId: string) => {
    if (!confirm('Are you sure you want to delete this channel?')) return;

    try {
      await api.deleteChannel(channelId);
      setChannels(channels.filter((c) => c.id !== channelId));
    } catch (err) {
      alert('Failed to delete channel');
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
        <h2 className="text-2xl font-bold text-gray-900">Channels</h2>
        <button
          onClick={() => handleOpenModal()}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Create Channel
        </button>
      </div>

      {/* Channels Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {channels.length === 0 ? (
          <div className="col-span-full bg-white rounded-lg shadow p-6 text-center text-gray-500">
            No channels yet. Click "Create Channel" to add one.
          </div>
        ) : (
          channels.map((channel) => {
            const residentAgent = agents.find(
              (a) => a.id === channel.resident_agent_id
            );
            return (
              <div key={channel.id} className="bg-white rounded-lg shadow p-6">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Badge status={channel.channel_type} />
                    {channel.is_active ? (
                      <span className="px-2 py-0.5 text-xs bg-green-100 text-green-800 rounded-full">
                        Active
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
                        Inactive
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleOpenModal(channel)}
                      className="p-1 text-gray-400 hover:text-gray-600"
                      title="Edit"
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => handleDelete(channel.id)}
                      className="p-1 text-gray-400 hover:text-red-600"
                      title="Delete"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>

                <div className="space-y-2 text-sm">
                  <div>
                    <span className="text-gray-500">ID:</span>
                    <span className="ml-2 text-gray-900 font-mono text-xs">
                      {channel.id.slice(0, 8)}...
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-500">Resident Agent:</span>
                    {residentAgent ? (
                      <span className="ml-2 text-gray-900">
                        {residentAgent.name}
                      </span>
                    ) : (
                      <span className="ml-2 text-gray-400">None</span>
                    )}
                  </div>
                  <div>
                    <span className="text-gray-500">Created:</span>
                    <span
                      className="ml-2 text-gray-900"
                      title={format(new Date(channel.created_at), 'PPpp')}
                    >
                      {formatDistanceToNow(new Date(channel.created_at), {
                        addSuffix: true,
                      })}
                    </span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="text-lg font-medium">
                {editingChannel ? 'Edit Channel' : 'Create Channel'}
              </h3>
              <button
                onClick={handleCloseModal}
                className="p-1 hover:bg-gray-100 rounded"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSubmit} className="p-4 space-y-4">
              {!editingChannel && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Channel Type
                  </label>
                  <select
                    value={formData.channel_type}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        channel_type: e.target.value as ChannelType,
                      })
                    }
                    className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                  >
                    {channelTypeOptions.map((type) => (
                      <option key={type} value={type}>
                        {type}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Resident Agent
                </label>
                <select
                  value={formData.resident_agent_id}
                  onChange={(e) =>
                    setFormData({ ...formData, resident_agent_id: e.target.value })
                  }
                  className="w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                >
                  <option value="">None</option>
                  {agents.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </div>

              {editingChannel && (
                <div className="flex items-center">
                  <input
                    type="checkbox"
                    id="is_active"
                    checked={formData.is_active}
                    onChange={(e) =>
                      setFormData({ ...formData, is_active: e.target.checked })
                    }
                    className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
                  />
                  <label
                    htmlFor="is_active"
                    className="ml-2 text-sm text-gray-700"
                  >
                    Active
                  </label>
                </div>
              )}

              <div className="flex justify-end gap-2 pt-4">
                <button
                  type="button"
                  onClick={handleCloseModal}
                  className="px-4 py-2 border rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {submitting ? 'Saving...' : editingChannel ? 'Update' : 'Create'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChannelsPage;
