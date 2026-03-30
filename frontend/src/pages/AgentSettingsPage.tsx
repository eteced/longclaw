import React, { useEffect, useState } from 'react';
import { Save, RotateCcw, ChevronDown, ChevronUp, Users, Cpu, Infinity } from 'lucide-react';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type { AgentType, AllSettingsResponse, Agent, ModelConfig } from '../types';

const AGENT_TYPES: AgentType[] = ['resident', 'owner', 'worker', 'sub'];

const AGENT_TYPE_LABELS: Record<AgentType, string> = {
  resident: 'Resident Agent',
  owner: 'Owner Agent',
  worker: 'Worker Agent',
  sub: 'Sub Agent',
};

const AGENT_TYPE_DESCRIPTIONS: Record<AgentType, string> = {
  resident: '常驻 Agent - 与用户交互的主要入口',
  owner: 'Owner Agent - 任务分解和调度',
  worker: 'Worker Agent - 执行具体子任务',
  sub: 'Sub Agent - 轻量级子任务执行',
};

// Special value for unlimited context (-1 means unlimited, consistent with system config)
const UNLIMITED_CONTEXT = -1;

export const AgentSettingsPage: React.FC = () => {
  const [settings, setSettings] = useState<AllSettingsResponse | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [modelConfig, setModelConfig] = useState<ModelConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<AgentType>('resident');
  const [editedPrompts, setEditedPrompts] = useState<Record<string, string>>({});
  const [editedModels, setEditedModels] = useState<Record<string, { provider: string; model: string }>>({});
  const [editedContextLimits, setEditedContextLimits] = useState<Record<string, number | null>>({});
  const [unlimitedContext, setUnlimitedContext] = useState<Record<string, boolean>>({});
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [agentPromptEdits, setAgentPromptEdits] = useState<Record<string, string>>({});
  const [agentModelEdits, setAgentModelEdits] = useState<Record<string, { provider: string; model: string }>>({});
  const [agentContextEdits, setAgentContextEdits] = useState<Record<string, number | null>>({});
  const [agentUnlimitedContext, setAgentUnlimitedContext] = useState<Record<string, boolean>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [settingsData, agentsData, modelConfigData] = await Promise.all([
          api.getAllSettings(),
          api.getAgents({ limit: 100 }),
          api.getModelConfig(),
        ]);
        setSettings(settingsData);
        setAgents(agentsData.items);
        setModelConfig(modelConfigData);

        // Initialize edited prompts from loaded data
        const initialPrompts: Record<string, string> = {};
        const initialModels: Record<string, { provider: string; model: string }> = {};
        const initialContextLimits: Record<string, number | null> = {};
        const initialUnlimitedContext: Record<string, boolean> = {};

        AGENT_TYPES.forEach((type) => {
          const typeSettings = settingsData.type_settings[type];
          if (typeSettings) {
            initialPrompts[type] = typeSettings.system_prompt || '';
            if (typeSettings.provider_name && typeSettings.model_name) {
              initialModels[type] = {
                provider: typeSettings.provider_name,
                model: typeSettings.model_name,
              };
            }
            // Handle context limit - null means not set, 0 means unlimited
            if (typeSettings.max_context_tokens !== null && typeSettings.max_context_tokens !== undefined) {
              if (typeSettings.max_context_tokens === UNLIMITED_CONTEXT) {
                initialUnlimitedContext[type] = true;
                initialContextLimits[type] = null;
              } else {
                initialUnlimitedContext[type] = false;
                initialContextLimits[type] = typeSettings.max_context_tokens;
              }
            }
          }
        });

        setEditedPrompts(initialPrompts);
        setEditedModels(initialModels);
        setEditedContextLimits(initialContextLimits);
        setUnlimitedContext(initialUnlimitedContext);
      } catch (err) {
        setError('Failed to load agent settings');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleSaveTypeSettings = async () => {
    const newPrompt = editedPrompts[activeTab];
    if (!newPrompt?.trim()) {
      setError('System prompt cannot be empty');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      const updateData: { system_prompt: string; provider_name?: string; model_name?: string; max_context_tokens?: number | null } = {
        system_prompt: newPrompt,
      };

      const modelEdit = editedModels[activeTab];
      if (modelEdit) {
        updateData.provider_name = modelEdit.provider;
        updateData.model_name = modelEdit.model;
      }

      // Handle context limit - if unlimited, set to 0
      if (unlimitedContext[activeTab]) {
        updateData.max_context_tokens = UNLIMITED_CONTEXT;
      } else if (editedContextLimits[activeTab]) {
        updateData.max_context_tokens = editedContextLimits[activeTab];
      }

      await api.updateTypeSettings(activeTab, updateData);
      setSuccess(`${AGENT_TYPE_LABELS[activeTab]} settings saved successfully`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload settings
      const settingsData = await api.getAllSettings();
      setSettings(settingsData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save settings';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleResetTypeSettings = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await api.resetTypeSettings(activeTab);
      setSuccess(`${AGENT_TYPE_LABELS[activeTab]} settings reset to default`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload settings
      const settingsData = await api.getAllSettings();
      setSettings(settingsData);

      // Update local state
      const typeSettings = settingsData.type_settings[activeTab];
      setEditedPrompts((prev) => ({
        ...prev,
        [activeTab]: typeSettings?.system_prompt || '',
      }));
      setEditedModels((prev) => {
        const newModels = { ...prev };
        delete newModels[activeTab];
        return newModels;
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to reset settings';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAgentSettings = async (agentId: string) => {
    const newPrompt = agentPromptEdits[agentId];
    const newModel = agentModelEdits[agentId];
    const newContextLimit = agentContextEdits[agentId];
    const isUnlimited = agentUnlimitedContext[agentId];

    if (!newPrompt?.trim() && !newModel && newContextLimit === undefined && !isUnlimited) {
      setError('Please provide at least one setting to update');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      const updateData: { system_prompt?: string; provider_name?: string; model_name?: string; max_context_tokens?: number | null } = {};

      if (newPrompt?.trim()) {
        updateData.system_prompt = newPrompt;
      }
      if (newModel) {
        updateData.provider_name = newModel.provider;
        updateData.model_name = newModel.model;
      }
      // Handle context limit
      if (isUnlimited) {
        updateData.max_context_tokens = UNLIMITED_CONTEXT;
      } else if (newContextLimit !== undefined && newContextLimit !== null) {
        updateData.max_context_tokens = newContextLimit;
      }

      await api.updateAgentSettings(agentId, updateData);
      setSuccess(`Agent settings saved successfully`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload settings
      const settingsData = await api.getAllSettings();
      setSettings(settingsData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save agent settings';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAgentSettings = async (agentId: string) => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await api.deleteAgentSettings(agentId);
      setSuccess(`Agent settings override removed`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload settings and clear edit
      const settingsData = await api.getAllSettings();
      setSettings(settingsData);
      setAgentPromptEdits((prev) => {
        const newEdits = { ...prev };
        delete newEdits[agentId];
        return newEdits;
      });
      setAgentModelEdits((prev) => {
        const newEdits = { ...prev };
        delete newEdits[agentId];
        return newEdits;
      });
      setAgentContextEdits((prev) => {
        const newEdits = { ...prev };
        delete newEdits[agentId];
        return newEdits;
      });
      setAgentUnlimitedContext((prev) => {
        const newEdits = { ...prev };
        delete newEdits[agentId];
        return newEdits;
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete agent settings';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const toggleAgentExpand = (agentId: string) => {
    setExpandedAgents((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(agentId)) {
        newSet.delete(agentId);
      } else {
        newSet.add(agentId);
      }
      return newSet;
    });
  };

  const getAgentsByType = (type: AgentType): Agent[] => {
    return agents.filter((agent) => agent.agent_type === type);
  };

  const getContextLimitForModel = (providerName: string, modelName: string): number | null => {
    if (!modelConfig) return null;
    const provider = modelConfig.providers.find((p) => p.name === providerName);
    if (!provider) return null;
    const model = provider.models.find((m) => m.name === modelName);
    return model?.max_context_tokens || null;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!settings || !modelConfig) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        Failed to load agent settings
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Agent Settings</h2>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 p-4 rounded-lg">{error}</div>
      )}

      {success && (
        <div className="bg-green-50 text-green-700 p-4 rounded-lg">{success}</div>
      )}

      {/* Tabs for agent types */}
      <div className="bg-white rounded-lg shadow">
        <div className="border-b border-gray-200">
          <nav className="flex -mb-px">
            {AGENT_TYPES.map((type) => (
              <button
                key={type}
                onClick={() => setActiveTab(type)}
                className={`px-6 py-4 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === type
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {AGENT_TYPE_LABELS[type]}
              </button>
            ))}
          </nav>
        </div>

        {/* Settings editor */}
        <div className="p-6 space-y-6">
          <div className="mb-4">
            <p className="text-sm text-gray-500">
              {AGENT_TYPE_DESCRIPTIONS[activeTab]}
            </p>
            {settings.type_settings[activeTab]?.is_default && (
              <span className="inline-block mt-2 px-2 py-1 text-xs bg-gray-100 text-gray-600 rounded">
                Using default settings
              </span>
            )}
          </div>

          {/* Model Assignment Section */}
          <div className="border rounded-lg p-4">
            <h3 className="text-sm font-medium text-gray-900 mb-3 flex items-center gap-2">
              <Cpu className="w-4 h-4" />
              Model Assignment
            </h3>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Provider
                </label>
                <select
                  value={editedModels[activeTab]?.provider || ''}
                  onChange={(e) =>
                    setEditedModels((prev) => ({
                      ...prev,
                      [activeTab]: {
                        provider: e.target.value,
                        model: prev[activeTab]?.model || '',
                      },
                    }))
                  }
                  className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                >
                  <option value="">Use Default</option>
                  {modelConfig.providers.map((provider) => (
                    <option key={provider.name} value={provider.name}>
                      {provider.display_name || provider.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Model
                </label>
                <select
                  value={editedModels[activeTab]?.model || ''}
                  onChange={(e) =>
                    setEditedModels((prev) => ({
                      ...prev,
                      [activeTab]: {
                        provider: prev[activeTab]?.provider || '',
                        model: e.target.value,
                      },
                    }))
                  }
                  className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
                  disabled={!editedModels[activeTab]?.provider}
                >
                  <option value="">Select Model</option>
                  {editedModels[activeTab]?.provider &&
                    modelConfig.providers
                      .find((p) => p.name === editedModels[activeTab]?.provider)
                      ?.models.map((model) => (
                        <option key={model.name} value={model.name}>
                          {model.name}
                        </option>
                      ))}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Context Limit (tokens)
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="number"
                    value={editedContextLimits[activeTab] || ''}
                    onChange={(e) =>
                      setEditedContextLimits((prev) => ({
                        ...prev,
                        [activeTab]: parseInt(e.target.value) || null,
                      }))
                    }
                    placeholder={editedModels[activeTab]?.provider && editedModels[activeTab]?.model
                      ? getContextLimitForModel(editedModels[activeTab].provider, editedModels[activeTab].model)?.toLocaleString()
                      : 'Default'}
                    disabled={unlimitedContext[activeTab]}
                    className="block flex-1 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-400"
                  />
                  <label className="flex items-center gap-1 text-sm text-gray-600 whitespace-nowrap">
                    <input
                      type="checkbox"
                      checked={unlimitedContext[activeTab] || false}
                      onChange={(e) =>
                        setUnlimitedContext((prev) => ({
                          ...prev,
                          [activeTab]: e.target.checked,
                        }))
                      }
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    <Infinity className="w-4 h-4" />
                    无限制
                  </label>
                </div>
              </div>
            </div>
            {editedModels[activeTab]?.provider && editedModels[activeTab]?.model && (
              <div className="mt-3 text-sm text-gray-500">
                Model Default Context: {getContextLimitForModel(editedModels[activeTab].provider, editedModels[activeTab].model)?.toLocaleString() || 'Unknown'} tokens
              </div>
            )}
          </div>

          {/* Prompt Editor Section */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              System Prompt
            </label>
            <textarea
              value={editedPrompts[activeTab] || ''}
              onChange={(e) =>
                setEditedPrompts((prev) => ({
                  ...prev,
                  [activeTab]: e.target.value,
                }))
              }
              className="block w-full h-80 p-4 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 font-mono text-sm"
              placeholder="Enter system prompt..."
            />
          </div>

          <div className="flex gap-2">
            <button
              onClick={handleSaveTypeSettings}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
            <button
              onClick={handleResetTypeSettings}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50"
            >
              <RotateCcw className="w-4 h-4" />
              Reset to Default
            </button>
          </div>
        </div>
      </div>

      {/* Agent instances section */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4 flex items-center gap-2">
          <Users className="w-5 h-5" />
          Agent Instances ({getAgentsByType(activeTab).length})
        </h3>

        {getAgentsByType(activeTab).length === 0 ? (
          <p className="text-gray-500 text-center py-8">
            No agents of this type found.
          </p>
        ) : (
          <div className="space-y-4">
            {getAgentsByType(activeTab).map((agent) => {
              const isExpanded = expandedAgents.has(agent.id);
              const instanceSettings = settings.instance_settings[agent.id];
              const editPromptValue = agentPromptEdits[agent.id] ?? instanceSettings?.system_prompt ?? '';
              const editModelValue = agentModelEdits[agent.id] ??
                (instanceSettings?.provider_name && instanceSettings?.model_name
                  ? { provider: instanceSettings.provider_name, model: instanceSettings.model_name }
                  : null);

              // Initialize context limit state for this agent if not set
              const agentContextLimit = agentContextEdits[agent.id];
              const agentIsUnlimited = agentUnlimitedContext[agent.id];

              // Get effective context limit display
              const modelContextLimit = editModelValue?.provider && editModelValue?.model
                ? getContextLimitForModel(editModelValue.provider, editModelValue.model)
                : null;

              return (
                <div key={agent.id} className="border rounded-lg">
                  <button
                    onClick={() => toggleAgentExpand(agent.id)}
                    className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-medium text-gray-900">{agent.name}</span>
                      <span className="text-sm text-gray-500">{agent.id}</span>
                      {instanceSettings && (
                        <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded">
                          Custom Settings
                        </span>
                      )}
                    </div>
                    {isExpanded ? (
                      <ChevronUp className="w-5 h-5 text-gray-400" />
                    ) : (
                      <ChevronDown className="w-5 h-5 text-gray-400" />
                    )}
                  </button>

                  {isExpanded && (
                    <div className="border-t p-4 space-y-4">
                      <p className="text-sm text-gray-500">
                        Set custom settings for this agent instance. These will override the type-level defaults.
                      </p>

                      {/* Model Assignment for Instance */}
                      <div className="border rounded-lg p-4 bg-gray-50">
                        <h4 className="text-sm font-medium text-gray-900 mb-3 flex items-center gap-2">
                          <Cpu className="w-4 h-4" />
                          Model Assignment
                        </h4>
                        <div className="grid grid-cols-3 gap-4">
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Provider
                            </label>
                            <select
                              value={editModelValue?.provider || ''}
                              onChange={(e) =>
                                setAgentModelEdits((prev) => ({
                                  ...prev,
                                  [agent.id]: {
                                    provider: e.target.value,
                                    model: prev[agent.id]?.model || '',
                                  },
                                }))
                              }
                              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                            >
                              <option value="">Use Type Default</option>
                              {modelConfig.providers.map((provider) => (
                                <option key={provider.name} value={provider.name}>
                                  {provider.display_name || provider.name}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Model
                            </label>
                            <select
                              value={editModelValue?.model || ''}
                              onChange={(e) =>
                                setAgentModelEdits((prev) => ({
                                  ...prev,
                                  [agent.id]: {
                                    provider: prev[agent.id]?.provider || '',
                                    model: e.target.value,
                                  },
                                }))
                              }
                              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              disabled={!editModelValue?.provider}
                            >
                              <option value="">Select Model</option>
                              {editModelValue?.provider &&
                                modelConfig.providers
                                  .find((p) => p.name === editModelValue?.provider)
                                  ?.models.map((model) => (
                                    <option key={model.name} value={model.name}>
                                      {model.name} ({model.max_context_tokens.toLocaleString()} tokens)
                                    </option>
                                  ))}
                            </select>
                          </div>
                          <div>
                            <label className="block text-sm font-medium text-gray-700 mb-1">
                              Context Limit
                            </label>
                            <div className="flex items-center gap-1">
                              <input
                                type="number"
                                value={agentContextLimit ?? ''}
                                onChange={(e) =>
                                  setAgentContextEdits((prev) => ({
                                    ...prev,
                                    [agent.id]: parseInt(e.target.value) || null,
                                  }))
                                }
                                placeholder={modelContextLimit?.toLocaleString() || 'Default'}
                                disabled={agentIsUnlimited}
                                className="block flex-1 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm disabled:bg-gray-100"
                              />
                              <label className="flex items-center gap-0.5 text-xs text-gray-600 whitespace-nowrap">
                                <input
                                  type="checkbox"
                                  checked={agentIsUnlimited || false}
                                  onChange={(e) =>
                                    setAgentUnlimitedContext((prev) => ({
                                      ...prev,
                                      [agent.id]: e.target.checked,
                                    }))
                                  }
                                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                />
                                <Infinity className="w-3 h-3" />
                              </label>
                            </div>
                          </div>
                        </div>
                        {modelContextLimit && (
                          <div className="mt-2 text-xs text-gray-500">
                            Model Default: {modelContextLimit.toLocaleString()} tokens
                            {agentIsUnlimited && ' (Agent: 无限制)'}
                            {agentContextLimit && !agentIsUnlimited && (
                              <> → Effective: {Math.min(agentContextLimit, modelContextLimit).toLocaleString()} tokens</>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Prompt Override for Instance */}
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          System Prompt Override
                        </label>
                        <textarea
                          value={editPromptValue}
                          onChange={(e) =>
                            setAgentPromptEdits((prev) => ({
                              ...prev,
                              [agent.id]: e.target.value,
                            }))
                          }
                          className="block w-full h-40 p-4 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 font-mono text-sm"
                          placeholder="Override prompt (leave empty to use type default)..."
                        />
                      </div>

                      <div className="flex gap-2">
                        <button
                          onClick={() => handleSaveAgentSettings(agent.id)}
                          disabled={saving}
                          className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
                        >
                          <Save className="w-3 h-3" />
                          Save Override
                        </button>
                        {instanceSettings && (
                          <button
                            onClick={() => handleDeleteAgentSettings(agent.id)}
                            disabled={saving}
                            className="flex items-center gap-2 px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 text-sm"
                          >
                            Remove Override
                          </button>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default AgentSettingsPage;
