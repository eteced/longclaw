import React, { useEffect, useState } from 'react';
import { Plus, Trash2, Save, Eye, EyeOff, RefreshCw, Zap, Clock, AlertCircle, CheckCircle, Radio, Loader2, Infinity, Cpu, Users } from 'lucide-react';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type { ModelConfig, ProviderConfig, ModelInfo } from '../types';

// Special value for unlimited context (-1 means unlimited, consistent with system config)
const UNLIMITED_CONTEXT = -1;

interface SpeedTestResult {
  provider: string;
  model: string;
  is_success: boolean;
  connection_time_ms?: number;
  prefill_time_ms?: number;
  generation_time_ms?: number;
  total_time_ms?: number;
  tokens_generated?: number;
  tokens_per_second?: number;
  ms_per_token?: number;
  recommended_timeouts?: Record<string, number>;
  error?: string;
}

interface SchedulerSummary {
  total_allocated: number;
  by_provider: Array<{
    provider_name: string;
    allocated: number;
    max: number;
    models: Array<{
      model_name: string;
      allocated: number;
      max: number;
      slots: Array<{
        slot_index: number;
        agent_id: string;
        agent_name: string;
        operation: string;
        priority: number;
      }>;
    }>;
  }>;
}

export const ModelConfigPage: React.FC = () => {
  const [config, setConfig] = useState<ModelConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [showApiKeys, setShowApiKeys] = useState<Record<string, boolean>>({});
  const [speedTestLoading, setSpeedTestLoading] = useState(false);
  const [speedTestResult, setSpeedTestResult] = useState<SpeedTestResult | null>(null);
  const [testProviderIndex, setTestProviderIndex] = useState<number | null>(null);
  const [schedulerSummary, setSchedulerSummary] = useState<SchedulerSummary | null>(null);
  

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        setLoading(true);
        const data = await api.getModelConfig();
        setConfig(data);
      } catch (err) {
        setError('Failed to load model configuration');
        console.error(err);
      } finally {
        setLoading(false);
      }
    };

    fetchConfig();
    // Fetch scheduler summary periodically
    const fetchSchedulerSummary = async () => {
      try {
        const summary = await api.getSchedulerSummary();
        setSchedulerSummary(summary);
      } catch (err) {
        console.error('Failed to fetch scheduler summary:', err);
      }
    };

    fetchSchedulerSummary();
    const interval = setInterval(fetchSchedulerSummary, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleSave = async () => {
    if (!config) {
      console.error('[ModelConfigPage] No config to save');
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      console.log('[ModelConfigPage] Saving config:', {
        default_provider: config.default_provider,
        providers: config.providers,
      });

      const updatedConfig = await api.updateModelConfig({
        default_provider: config.default_provider,
        providers: config.providers,
      });

      console.log('[ModelConfigPage] Save successful:', updatedConfig);

      // Update local state with the response from server
      setConfig(updatedConfig);
      setSuccess('Configuration saved successfully');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error('[ModelConfigPage] Save failed:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to save configuration';
      setError(errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleRefresh = async () => {
    try {
      setRefreshing(true);
      setError(null);
      setSuccess(null);

      console.log('[ModelConfigPage] Refreshing config from .env');

      const updatedConfig = await api.refreshModelConfig();

      console.log('[ModelConfigPage] Refresh successful:', updatedConfig);

      // Update local state with the response from server
      setConfig(updatedConfig);
      setSuccess('Configuration refreshed from .env file');
      setTimeout(() => setSuccess(null), 3000);
    } catch (err) {
      console.error('[ModelConfigPage] Refresh failed:', err);
      const errorMessage = err instanceof Error ? err.message : 'Failed to refresh configuration';
      setError(errorMessage);
    } finally {
      setRefreshing(false);
    }
  };

  const handleSpeedTest = async () => {
    try {
      setSpeedTestLoading(true);
      setSpeedTestResult(null);
      setError(null);

      const response = await fetch('/api/model-config/speed-test', {
        headers: {
          'X-API-Key': api.getApiKey() || '',
        },
      });

      const result = await response.json();
      setSpeedTestResult(result);

      if (!result.is_success) {
        setError(`Speed test failed: ${result.error}`);
      }
    } catch (err) {
      console.error('[ModelConfigPage] Speed test failed:', err);
      setError(err instanceof Error ? err.message : 'Speed test failed');
    } finally {
      setSpeedTestLoading(false);
    }
  };

  const handleApplyTimeouts = async (timeouts: Record<string, number>) => {
    try {
      const response = await fetch('/api/model-config/apply-timeouts', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': api.getApiKey() || '',
        },
        body: JSON.stringify(timeouts),
      });

      if (response.ok) {
        setSuccess('Timeout configurations applied successfully');
        setTimeout(() => setSuccess(null), 3000);
      } else {
        const data = await response.json();
        setError(`Failed to apply timeouts: ${data.detail || 'Unknown error'}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to apply timeouts');
    }
  };

  const updateDefaultProvider = (provider: string) => {
    if (!config) return;
    setConfig({ ...config, default_provider: provider });
  };

  const updateProvider = (index: number, updates: Partial<ProviderConfig>) => {
    if (!config) return;
    const newProviders = [...config.providers];
    newProviders[index] = { ...newProviders[index], ...updates };
    setConfig({ ...config, providers: newProviders });
  };

  const addProvider = () => {
    if (!config) return;
    const newProvider: ProviderConfig = {
      name: `provider_${Date.now()}`,
      display_name: 'New Provider',
      base_url: '',
      api_key: '',
      max_parallel_requests: 10,
      models: [],
    };
    setConfig({ ...config, providers: [...config.providers, newProvider] });
  };

  const removeProvider = (index: number) => {
    if (!config) return;
    const newProviders = config.providers.filter((_, i) => i !== index);
    setConfig({ ...config, providers: newProviders });
  };

  const toggleApiKeyVisibility = (providerName: string) => {
    setShowApiKeys((prev) => ({ ...prev, [providerName]: !prev[providerName] }));
  };

  const handleTestProvider = async (index: number) => {
    if (!config) return;

    const provider = config.providers[index];
    if (!provider.base_url) {
      setError('Please enter a base URL first');
      return;
    }

    try {
      setTestProviderIndex(index);
      setError(null);

      const response = await fetch('/api/model-config/test-provider', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': api.getApiKey() || '',
        },
        body: JSON.stringify({
          base_url: provider.base_url,
          api_key: provider.api_key,
        }),
      });

      const result = await response.json();

      if (result.success && result.models && result.models.length > 0) {
        // Auto-populate models if provider has no models or user wants to replace
        if (provider.models.length === 0) {
          const newModels: ModelInfo[] = result.models.map((name: string) => ({
            name,
            max_context_tokens: 8192,
            max_parallel_requests: 10,
          }));
          updateProvider(index, { models: newModels });
        }
        setSuccess(`Found ${result.models.length} models (latency: ${result.latency_ms?.toFixed(0)}ms)`);
        setTimeout(() => setSuccess(null), 3000);
      } else if (!result.success) {
        setError(`Connection failed: ${result.error}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to test provider');
    } finally {
      setTestProviderIndex(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (!config) {
    return (
      <div className="bg-red-50 text-red-700 p-4 rounded-lg">
        Failed to load configuration
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold text-gray-900">Model Configuration</h2>
        <div className="flex gap-2">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing...' : 'Refresh from .env'}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            <Save className="w-4 h-4" />
            {saving ? 'Saving...' : 'Save Changes'}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 p-4 rounded-lg">{error}</div>
      )}

      {success && (
        <div className="bg-green-50 text-green-700 p-4 rounded-lg">{success}</div>
      )}

      {/* Default Provider Selection */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-medium text-gray-900 mb-4">Default Provider</h3>
        <select
          value={config.default_provider}
          onChange={(e) => updateDefaultProvider(e.target.value)}
          className="block w-full max-w-xs rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500"
        >
          {config.providers.map((provider) => (
            <option key={provider.name} value={provider.name}>
              {provider.display_name || provider.name}
            </option>
          ))}
        </select>
      </div>

      {/* Provider Scheduler Status */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-600" />
            <h3 className="text-lg font-medium text-gray-900">Provider Scheduler</h3>
          </div>
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <span className="flex items-center gap-1">
              <Users className="w-4 h-4" />
              {schedulerSummary?.total_allocated || 0} slots allocated
            </span>
          </div>
        </div>

        <p className="text-sm text-gray-500 mb-4">
          Shows how model inference slots are distributed among agents. Higher priority agents get slots first.
        </p>

        {schedulerSummary && schedulerSummary.total_allocated > 0 ? (
          <div className="space-y-4">
            {schedulerSummary.by_provider.map((provider) => (
              <div key={provider.provider_name} className="border rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-medium text-gray-800">
                    {provider.provider_name}
                  </h4>
                  <span className="text-sm text-gray-500">
                    {provider.allocated} / {provider.max} slots used
                  </span>
                </div>
                <div className="space-y-2">
                  {provider.models.map((model) => (
                    <div key={model.model_name} className="bg-gray-50 rounded-lg p-3">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-sm font-medium text-gray-700">
                          {model.model_name}
                        </span>
                        <span className="text-xs text-gray-500">
                          {model.allocated} / {model.max}
                        </span>
                      </div>
                      {model.slots.length > 0 && (
                        <div className="space-y-1">
                          {model.slots.map((slot, idx) => (
                            <div key={idx} className="flex items-center justify-between text-xs">
                              <span className="text-gray-600">
                                Slot {slot.slot_index}: <span className="font-medium">{slot.agent_name}</span>
                              </span>
                              <span className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded">
                                {slot.operation}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center text-gray-500 py-8">
            No active model allocations. Slots will be assigned when agents make LLM requests.
          </div>
        )}
      </div>

      {/* LLM Speed Test */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-gray-900">LLM Speed Test</h3>
          <button
            onClick={handleSpeedTest}
            disabled={speedTestLoading}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
          >
            <Zap className={`w-4 h-4 ${speedTestLoading ? 'animate-pulse' : ''}`} />
            {speedTestLoading ? 'Testing...' : 'Run Speed Test'}
          </button>
        </div>

        <p className="text-sm text-gray-500 mb-4">
          Test LLM response speed to measure prefill time, generation speed, and recommend optimal timeout configurations.
        </p>

        {speedTestResult && (
          <div className="space-y-4">
            {/* Test Status */}
            <div className={`p-4 rounded-lg ${speedTestResult.is_success ? 'bg-green-50' : 'bg-red-50'}`}>
              <div className="flex items-center gap-2">
                {speedTestResult.is_success ? (
                  <CheckCircle className="w-5 h-5 text-green-600" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-red-600" />
                )}
                <span className={`font-medium ${speedTestResult.is_success ? 'text-green-800' : 'text-red-800'}`}>
                  {speedTestResult.is_success ? 'Speed Test Completed' : 'Speed Test Failed'}
                </span>
              </div>
              {speedTestResult.error && (
                <p className="mt-2 text-sm text-red-700">{speedTestResult.error}</p>
              )}
            </div>

            {/* Speed Metrics */}
            {speedTestResult.is_success && (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                  <div className="bg-gray-50 rounded-lg p-4">
                    <div className="flex items-center gap-2 text-gray-500 text-sm">
                      <Clock className="w-4 h-4" />
                      Prefill Time
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-1">
                      {speedTestResult.prefill_time_ms?.toFixed(0) || '-'}ms
                    </p>
                    <p className="text-xs text-gray-400">Time to first token</p>
                  </div>

                  <div className="bg-gray-50 rounded-lg p-4">
                    <div className="flex items-center gap-2 text-gray-500 text-sm">
                      <Zap className="w-4 h-4" />
                      Generation Speed
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-1">
                      {speedTestResult.tokens_per_second?.toFixed(2) || '-'}
                    </p>
                    <p className="text-xs text-gray-400">Tokens per second</p>
                  </div>

                  <div className="bg-gray-50 rounded-lg p-4">
                    <div className="flex items-center gap-2 text-gray-500 text-sm">
                      <Clock className="w-4 h-4" />
                      Total Time
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-1">
                      {(speedTestResult.total_time_ms || 0) / 1000}s
                    </p>
                    <p className="text-xs text-gray-400">For {speedTestResult.tokens_generated || 0} tokens</p>
                  </div>

                  <div className="bg-gray-50 rounded-lg p-4">
                    <div className="flex items-center gap-2 text-gray-500 text-sm">
                      <Clock className="w-4 h-4" />
                      Per Token
                    </div>
                    <p className="text-2xl font-bold text-gray-900 mt-1">
                      {speedTestResult.ms_per_token?.toFixed(0) || '-'}ms
                    </p>
                    <p className="text-xs text-gray-400">Average generation time</p>
                  </div>
                </div>

                {/* Recommended Timeouts */}
                {speedTestResult.recommended_timeouts && (
                  <div className="border rounded-lg p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="font-medium text-gray-900">Recommended Timeout Configuration</h4>
                      <button
                        onClick={() => handleApplyTimeouts(speedTestResult.recommended_timeouts!)}
                        className="px-3 py-1.5 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
                      >
                        Apply All
                      </button>
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                      {Object.entries(speedTestResult.recommended_timeouts).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between bg-gray-50 rounded px-3 py-2">
                          <span className="text-sm text-gray-600">{key}</span>
                          <span className="text-sm font-medium text-gray-900">{value}s</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      {/* Providers List */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-gray-900">Providers</h3>
          <button
            onClick={addProvider}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
          >
            <Plus className="w-4 h-4" />
            Add Provider
          </button>
        </div>

        <div className="space-y-6">
          {config.providers.map((provider, index) => (
            <div
              key={`provider-${index}`}
              className="border rounded-lg p-4 space-y-4"
            >
              <div className="flex items-center justify-between">
                <h4 className="font-medium text-gray-800">
                  {provider.display_name || provider.name}
                </h4>
                <button
                  onClick={() => removeProvider(index)}
                  className="p-1 text-red-600 hover:bg-red-50 rounded"
                  title="Remove provider"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Name (identifier)
                  </label>
                  <input
                    type="text"
                    value={provider.name}
                    onChange={(e) =>
                      updateProvider(index, { name: e.target.value })
                    }
                    className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    placeholder="e.g., openai"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Display Name
                  </label>
                  <input
                    type="text"
                    value={provider.display_name || ''}
                    onChange={(e) =>
                      updateProvider(index, { display_name: e.target.value })
                    }
                    className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    placeholder="e.g., OpenAI"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Base URL
                  </label>
                  <input
                    type="text"
                    value={provider.base_url}
                    onChange={(e) =>
                      updateProvider(index, { base_url: e.target.value })
                    }
                    className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    placeholder="https://api.example.com/v1"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    API Key
                  </label>
                  <div className="flex gap-2">
                    <input
                      type={showApiKeys[provider.name] ? 'text' : 'password'}
                      value={provider.api_key || ''}
                      onChange={(e) =>
                        updateProvider(index, { api_key: e.target.value })
                      }
                      className="block flex-1 rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                      placeholder="sk-..."
                    />
                    <button
                      type="button"
                      onClick={() => toggleApiKeyVisibility(provider.name)}
                      className="p-2 text-gray-500 hover:text-gray-700"
                    >
                      {showApiKeys[provider.name] ? (
                        <EyeOff className="w-4 h-4" />
                      ) : (
                        <Eye className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Max Parallel Requests
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      type="number"
                      min="1"
                      max="100"
                      value={provider.max_parallel_requests || 10}
                      onChange={(e) =>
                        updateProvider(index, { max_parallel_requests: parseInt(e.target.value) || 10 })
                      }
                      className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                      placeholder="10"
                    />
                    <span className="text-xs text-gray-500 whitespace-nowrap">
                      concurrent requests
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-1">
                    Maximum number of agents that can use this provider simultaneously
                  </p>
                </div>

                <div className="flex items-end">
                  <button
                    onClick={() => handleTestProvider(index)}
                    disabled={testProviderIndex === index || !provider.base_url}
                    className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {testProviderIndex === index ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Radio className="w-4 h-4" />
                    )}
                    {testProviderIndex === index ? 'Testing...' : 'Test Provider'}
                  </button>
                </div>

                <div className="md:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Available Models
                  </label>
                  <p className="text-xs text-gray-500 mb-2">
                    Click "Test Provider" to auto-detect models, or manually add models below.
                  </p>
                  <div className="space-y-2">
                    {provider.models.map((model, modelIndex) => (
                      <div key={`${model.name}-${modelIndex}`} className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg">
                        <div className="flex-1">
                          <input
                            type="text"
                            value={model.name}
                            onChange={(e) => {
                              const newModels = [...provider.models];
                              newModels[modelIndex] = {
                                ...model,
                                name: e.target.value,
                              };
                              updateProvider(index, { models: newModels });
                            }}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                            placeholder="Model name (e.g., gpt-4o)"
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <label className="text-xs text-gray-500 whitespace-nowrap">Context:</label>
                          <input
                            type="number"
                            value={model.max_context_tokens === UNLIMITED_CONTEXT ? '' : model.max_context_tokens}
                            onChange={(e) => {
                              const newModels = [...provider.models];
                              newModels[modelIndex] = {
                                ...model,
                                max_context_tokens: parseInt(e.target.value) || 8192,
                              };
                              updateProvider(index, { models: newModels });
                            }}
                            disabled={model.max_context_tokens === UNLIMITED_CONTEXT}
                            className="w-28 px-2 py-1 text-sm rounded border-gray-300 focus:border-blue-500 focus:ring-blue-500 disabled:bg-gray-200 disabled:text-gray-400"
                            placeholder="8192"
                          />
                          <label className="flex items-center gap-0.5 text-xs text-gray-500 whitespace-nowrap cursor-pointer">
                            <input
                              type="checkbox"
                              checked={model.max_context_tokens === UNLIMITED_CONTEXT}
                              onChange={(e) => {
                                const newModels = [...provider.models];
                                newModels[modelIndex] = {
                                  ...model,
                                  max_context_tokens: e.target.checked ? UNLIMITED_CONTEXT : 8192,
                                };
                                updateProvider(index, { models: newModels });
                              }}
                              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                            />
                            <Infinity className="w-3 h-3" />
                          </label>
                        </div>
                        <div className="flex items-center gap-2">
                          <label className="text-xs text-gray-500 whitespace-nowrap">Max:</label>
                          <input
                            type="number"
                            min="1"
                            max="100"
                            value={model.max_parallel_requests || 10}
                            onChange={(e) => {
                              const newModels = [...provider.models];
                              newModels[modelIndex] = {
                                ...model,
                                max_parallel_requests: parseInt(e.target.value) || 10,
                              };
                              updateProvider(index, { models: newModels });
                            }}
                            className="w-16 px-2 py-1 text-sm rounded border-gray-300 focus:border-blue-500 focus:ring-blue-500"
                          />
                        </div>
                        <button
                          onClick={() => {
                            const newModels = provider.models.filter((_, i) => i !== modelIndex);
                            updateProvider(index, { models: newModels });
                          }}
                          className="p-1 text-red-600 hover:bg-red-50 rounded"
                          title="Remove model"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ))}
                    <button
                      onClick={() => {
                        const newModel: ModelInfo = {
                          name: '',
                          max_context_tokens: 8192,
                          max_parallel_requests: 10,
                        };
                        updateProvider(index, { models: [...provider.models, newModel] });
                      }}
                      className="flex items-center gap-1 px-3 py-2 text-sm text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg"
                    >
                      <Plus className="w-4 h-4" />
                      Add Model
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}

          {config.providers.length === 0 && (
            <p className="text-center text-gray-500 py-8">
              No providers configured. Click "Add Provider" to add one.
            </p>
          )}
        </div>
      </div>
    </div>
  );
};

export default ModelConfigPage;