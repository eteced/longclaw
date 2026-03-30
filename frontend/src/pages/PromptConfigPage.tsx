import React, { useEffect, useState } from 'react';
import { Save, RotateCcw, ChevronDown, ChevronUp, Users } from 'lucide-react';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type { PromptType, AllPromptsResponse, Agent } from '../types';

const PROMPT_TYPES: PromptType[] = ['RESIDENT', 'OWNER', 'WORKER', 'SUB'];

const PROMPT_TYPE_LABELS: Record<PromptType, string> = {
  RESIDENT: 'Resident Agent',
  OWNER: 'Owner Agent',
  WORKER: 'Worker Agent',
  SUB: 'Sub Agent',
};

const PROMPT_TYPE_DESCRIPTIONS: Record<PromptType, string> = {
  RESIDENT: '常驻 Agent - 与用户交互的主要入口',
  OWNER: 'Owner Agent - 任务分解和调度',
  WORKER: 'Worker Agent - 执行具体子任务',
  SUB: 'Sub Agent - 轻量级子任务执行',
};

export const PromptConfigPage: React.FC = () => {
  const [prompts, setPrompts] = useState<AllPromptsResponse | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<PromptType>('RESIDENT');
  const [editedPrompts, setEditedPrompts] = useState<Record<PromptType, string>>({} as Record<PromptType, string>);
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [agentPromptEdits, setAgentPromptEdits] = useState<Record<string, string>>({});

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [promptsData, agentsData] = await Promise.all([
          api.getAllPrompts(),
          api.getAgents({ limit: 100 }),
        ]);
        setPrompts(promptsData);
        setAgents(agentsData.items);

        // Initialize edited prompts from loaded data
        const initialEdits: Record<PromptType, string> = {} as Record<PromptType, string>;
        PROMPT_TYPES.forEach((type) => {
          initialEdits[type] = promptsData.type_prompts[type]?.system_prompt || '';
        });
        setEditedPrompts(initialEdits);
      } catch (err) {
        setError('Failed to load prompt configurations');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  const handleSaveTypePrompt = async () => {
    const newPrompt = editedPrompts[activeTab];
    if (!newPrompt.trim()) {
      setError('System prompt cannot be empty');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await api.updateTypePrompt(activeTab, { system_prompt: newPrompt });
      setSuccess(`${PROMPT_TYPE_LABELS[activeTab]} prompt saved successfully`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload prompts
      const promptsData = await api.getAllPrompts();
      setPrompts(promptsData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save prompt';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleResetTypePrompt = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await api.resetTypePrompt(activeTab);
      setSuccess(`${PROMPT_TYPE_LABELS[activeTab]} prompt reset to default`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload prompts
      const promptsData = await api.getAllPrompts();
      setPrompts(promptsData);
      setEditedPrompts((prev) => ({
        ...prev,
        [activeTab]: promptsData.type_prompts[activeTab]?.system_prompt || '',
      }));
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to reset prompt';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleSaveAgentPrompt = async (agentId: string) => {
    const newPrompt = agentPromptEdits[agentId];
    if (!newPrompt?.trim()) {
      setError('System prompt cannot be empty');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await api.setAgentPrompt(agentId, { system_prompt: newPrompt });
      setSuccess(`Agent prompt saved successfully`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload prompts
      const promptsData = await api.getAllPrompts();
      setPrompts(promptsData);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save agent prompt';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteAgentPrompt = async (agentId: string) => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await api.deleteAgentPrompt(agentId);
      setSuccess(`Agent prompt override removed`);
      setTimeout(() => setSuccess(null), 3000);

      // Reload prompts and clear edit
      const promptsData = await api.getAllPrompts();
      setPrompts(promptsData);
      setAgentPromptEdits((prev) => {
        const newEdits = { ...prev };
        delete newEdits[agentId];
        return newEdits;
      });
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to delete agent prompt';
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

  const getAgentsByType = (type: PromptType): Agent[] => {
    // Map PromptType to AgentType
    const typeMap: Record<PromptType, string> = {
      RESIDENT: 'resident',
      OWNER: 'owner',
      WORKER: 'worker',
      SUB: 'sub',
    };
    return agents.filter((agent) => agent.agent_type === typeMap[type]);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!prompts) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        Failed to load prompt configurations
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Agent Prompts</h2>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 p-4 rounded-lg">{error}</div>
      )}

      {success && (
        <div className="bg-green-50 text-green-700 p-4 rounded-lg">{success}</div>
      )}

      {/* Tabs for prompt types */}
      <div className="bg-white rounded-lg shadow">
        <div className="border-b border-gray-200">
          <nav className="flex -mb-px">
            {PROMPT_TYPES.map((type) => (
              <button
                key={type}
                onClick={() => setActiveTab(type)}
                className={`px-6 py-4 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === type
                    ? 'border-blue-500 text-blue-600'
                    : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
              >
                {PROMPT_TYPE_LABELS[type]}
              </button>
            ))}
          </nav>
        </div>

        {/* Prompt editor */}
        <div className="p-6">
          <div className="mb-4">
            <p className="text-sm text-gray-500">
              {PROMPT_TYPE_DESCRIPTIONS[activeTab]}
            </p>
            {prompts.type_prompts[activeTab]?.is_default && (
              <span className="inline-block mt-2 px-2 py-1 text-xs bg-gray-100 text-gray-600 rounded">
                Using default prompt
              </span>
            )}
          </div>

          <textarea
            value={editedPrompts[activeTab] || ''}
            onChange={(e) =>
              setEditedPrompts((prev) => ({
                ...prev,
                [activeTab]: e.target.value,
              }))
            }
            className="block w-full h-96 p-4 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 font-mono text-sm"
            placeholder="Enter system prompt..."
          />

          <div className="mt-4 flex gap-2">
            <button
              onClick={handleSaveTypePrompt}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
            <button
              onClick={handleResetTypePrompt}
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
              const instancePrompt = prompts.instance_prompts[agent.id];
              const editValue = agentPromptEdits[agent.id] ?? instancePrompt?.system_prompt ?? '';

              return (
                <div key={agent.id} className="border rounded-lg">
                  <button
                    onClick={() => toggleAgentExpand(agent.id)}
                    className="w-full flex items-center justify-between p-4 hover:bg-gray-50"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-medium text-gray-900">{agent.name}</span>
                      <span className="text-sm text-gray-500">{agent.id}</span>
                      {instancePrompt && (
                        <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded">
                          Custom Prompt
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
                        Set a custom prompt override for this agent instance. Leave empty to use the type default.
                      </p>
                      <textarea
                        value={editValue}
                        onChange={(e) =>
                          setAgentPromptEdits((prev) => ({
                            ...prev,
                            [agent.id]: e.target.value,
                          }))
                        }
                        className="block w-full h-48 p-4 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 font-mono text-sm"
                        placeholder="Override prompt (leave empty to use type default)..."
                      />
                      <div className="flex gap-2">
                        <button
                          onClick={() => handleSaveAgentPrompt(agent.id)}
                          disabled={saving || !editValue.trim()}
                          className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
                        >
                          <Save className="w-3 h-3" />
                          Save Override
                        </button>
                        {instancePrompt && (
                          <button
                            onClick={() => handleDeleteAgentPrompt(agent.id)}
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

export default PromptConfigPage;
