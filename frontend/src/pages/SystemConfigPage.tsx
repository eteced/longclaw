import React, { useEffect, useState } from 'react';
import {
  Save,
  RotateCcw,
  Clock,
  Settings,
  Download,
  Upload,
  Layers,
  CheckCircle,
  AlertCircle,
  Play,
  Trash2,
  Plus,
  Infinity,
  Bookmark,
  Zap,
  Shield,
  Bug,
  RefreshCw,
} from 'lucide-react';
import { api } from '../services/api';
import { LoadingSpinner } from '../components';
import type {
  SystemConfigItem,
  ConfigProfile,
  ConfigCategories,
} from '../types';

// Special value for unlimited
const UNLIMITED_VALUE = -1;

// Preset profile icons mapping
const PROFILE_ICONS: Record<string, React.ReactNode> = {
  'default': <Settings className="w-4 h-4" />,
  'high_performance': <Zap className="w-4 h-4" />,
  'unlimited': <Infinity className="w-4 h-4" />,
  'safe_mode': <Shield className="w-4 h-4" />,
  'debug': <Bug className="w-4 h-4" />,
};

interface EditedConfig {
  [key: string]: string;
}

export const SystemConfigPage: React.FC = () => {
  const [configs, setConfigs] = useState<SystemConfigItem[]>([]);
  const [categories, setCategories] = useState<ConfigCategories | null>(null);
  const [profiles, setProfiles] = useState<ConfigProfile[]>([]);
  const [currentProfile, setCurrentProfile] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [editedConfigs, setEditedConfigs] = useState<EditedConfig>({});
  const [activeTab, setActiveTab] = useState<'configs' | 'profiles'>('configs');
  const [showNewProfile, setShowNewProfile] = useState(false);
  const [newProfileName, setNewProfileName] = useState('');
  const [newProfileDesc, setNewProfileDesc] = useState('');

  useEffect(() => {
    fetchData();
  }, []);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [configsData, categoriesData, profilesData] = await Promise.all([
        api.getSystemConfigs(),
        api.getConfigCategories(),
        api.getConfigProfiles(),
      ]);
      setConfigs(configsData);
      setCategories(categoriesData);
      setProfiles(profilesData);

      // Initialize edited configs
      const initialEdits: EditedConfig = {};
      configsData.forEach((config) => {
        initialEdits[config.key] = config.value;
      });
      setEditedConfigs(initialEdits);
    } catch (err) {
      setError('Failed to load system configurations');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const showMessage = (msg: string, isError: boolean = false) => {
    if (isError) {
      setError(msg);
    } else {
      setSuccess(msg);
    }
    setTimeout(() => {
      setError(null);
      setSuccess(null);
    }, 3000);
  };

  const handleSaveConfig = async (key: string) => {
    const newValue = editedConfigs[key];
    if (newValue === undefined) return;

    try {
      setSaving(true);
      await api.updateSystemConfig(key, { value: newValue });
      showMessage(`${getConfigLabel(key)} saved successfully`);

      // Reload configs
      const data = await api.getSystemConfigs();
      setConfigs(data);
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to save config';
      showMessage(errorMessage, true);
    } finally {
      setSaving(false);
    }
  };

  const handleBatchSave = async () => {
    const modified: Record<string, string> = {};
    configs.forEach((config) => {
      if (editedConfigs[config.key] !== config.value) {
        modified[config.key] = editedConfigs[config.key];
      }
    });

    if (Object.keys(modified).length === 0) {
      showMessage('No changes to save', true);
      return;
    }

    try {
      setSaving(true);
      await api.batchUpdateSystemConfigs(modified);
      showMessage(`${Object.keys(modified).length} configurations saved successfully`);

      const data = await api.getSystemConfigs();
      setConfigs(data);
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to save configs', true);
    } finally {
      setSaving(false);
    }
  };

  const handleResetConfigs = async () => {
    if (!confirm('Reset all configurations to default values?')) {
      return;
    }

    try {
      setSaving(true);
      const data = await api.resetSystemConfigs();
      setConfigs(data);
      showMessage('All configurations reset to defaults');

      const resetEdits: EditedConfig = {};
      data.forEach((config) => {
        resetEdits[config.key] = config.value;
      });
      setEditedConfigs(resetEdits);
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to reset configs', true);
    } finally {
      setSaving(false);
    }
  };

  const handleExport = async () => {
    try {
      const data = await api.exportFullConfig();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `longclaw-config-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      showMessage('Configuration exported successfully');
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to export config', true);
    }
  };

  const handleImport = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const result = await api.importConfig(data, true);

      // Build summary message
      if (result.system_configs) {
        // v2.0 format
        const parts = [];
        if (result.system_configs.imported > 0) {
          parts.push(`${result.system_configs.imported} system configs`);
        }
        if (result.agent_settings?.imported) {
          parts.push(`${result.agent_settings.imported} agent settings`);
        }
        if (result.model_config?.imported) {
          parts.push('model config');
        }
        if (result.profiles?.imported) {
          parts.push(`${result.profiles.imported} profiles`);
        }
        const errors = [
          ...result.system_configs.errors,
          ...(result.agent_settings?.errors || []),
          ...(result.profiles?.errors || []),
        ];
        if (result.model_config?.error) {
          errors.push(`model config: ${result.model_config.error}`);
        }

        let message = `Imported: ${parts.join(', ')}`;
        if (errors.length > 0) {
          message += ` (${errors.length} errors)`;
        }
        showMessage(message);
      } else {
        // v1.0 format
        showMessage(`Imported ${result.imported} configs (${result.skipped} skipped)`);
      }

      // Reload
      await fetchData();
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to import config', true);
    }

    // Reset file input
    event.target.value = '';
  };

  const handleLoadProfile = async (profileId: string) => {
    const profile = profiles.find((p) => p.id === profileId || p.name === profileId);
    if (!profile) return;

    if (!confirm(`Load profile "${profile.name}"? This will replace current configurations.`)) {
      return;
    }

    try {
      setSaving(true);
      const result = await api.loadConfigProfile(profileId);
      showMessage(`Profile "${result.profile_name}" loaded (${result.applied} configs applied)`);
      setCurrentProfile(profile.name);

      // Reload configs
      const configsData = await api.getSystemConfigs();
      setConfigs(configsData);
      const newEdits: EditedConfig = {};
      configsData.forEach((config) => {
        newEdits[config.key] = config.value;
      });
      setEditedConfigs(newEdits);
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to load profile', true);
    } finally {
      setSaving(false);
    }
  };

  const handleCreateProfile = async () => {
    if (!newProfileName.trim()) {
      showMessage('Profile name is required', true);
      return;
    }

    try {
      setSaving(true);
      await api.createConfigProfile({
        name: newProfileName.trim(),
        description: newProfileDesc.trim() || undefined,
      });
      showMessage(`Profile "${newProfileName}" created`);
      setShowNewProfile(false);
      setNewProfileName('');
      setNewProfileDesc('');

      // Reload profiles
      const profilesData = await api.getConfigProfiles();
      setProfiles(profilesData);
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to create profile', true);
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteProfile = async (profileId: string, profileName: string) => {
    if (!confirm(`Delete profile "${profileName}"?`)) {
      return;
    }

    try {
      await api.deleteConfigProfile(profileId);
      showMessage(`Profile "${profileName}" deleted`);

      // Reload profiles
      const profilesData = await api.getConfigProfiles();
      setProfiles(profilesData);
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to delete profile', true);
    }
  };

  const handleSaveToProfile = async (profileId: string) => {
    try {
      setSaving(true);
      await api.saveCurrentToProfile(profileId);
      showMessage('Current configuration saved to profile');

      // Reload profiles
      const profilesData = await api.getConfigProfiles();
      setProfiles(profilesData);
    } catch (err) {
      showMessage(err instanceof Error ? err.message : 'Failed to save to profile', true);
    } finally {
      setSaving(false);
    }
  };

  const handleConfigChange = (key: string, value: string) => {
    setEditedConfigs((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const handleUnlimitedToggle = (key: string) => {
    const currentValue = editedConfigs[key];
    const isCurrentlyUnlimited = parseInt(currentValue) === UNLIMITED_VALUE;

    if (isCurrentlyUnlimited) {
      // Reset to default value
      const defaultValue = categories?.metadata?.[key]?.min_value || 0;
      handleConfigChange(key, defaultValue.toString());
    } else {
      // Set to unlimited
      handleConfigChange(key, UNLIMITED_VALUE.toString());
    }
  };

  const getConfigLabel = (key: string): string => {
    return categories?.metadata?.[key]?.display_name || key;
  };

  const getConfigUnit = (key: string): string | null => {
    return categories?.metadata?.[key]?.unit || null;
  };

  const getConfigCategory = (key: string): string => {
    return categories?.metadata?.[key]?.category || 'Other';
  };

  const isUnlimitedSupported = (key: string): boolean => {
    return categories?.metadata?.[key]?.unlimited_value !== null &&
           categories?.metadata?.[key]?.unlimited_value !== undefined;
  };

  const isUnlimitedValue = (key: string, value: string): boolean => {
    return isUnlimitedSupported(key) && parseInt(value) === UNLIMITED_VALUE;
  };

  // Group configs by category
  const groupedConfigs: Record<string, SystemConfigItem[]> = {};
  configs.forEach((config) => {
    const category = getConfigCategory(config.key);
    if (!groupedConfigs[category]) {
      groupedConfigs[category] = [];
    }
    groupedConfigs[category].push(config);
  });

  // Check if a config has been modified
  const isModified = (key: string) => {
    const original = configs.find((c) => c.key === key);
    return original && editedConfigs[key] !== original.value;
  };

  // Count modified configs
  const modifiedCount = configs.filter((c) => isModified(c.key)).length;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Settings className="w-6 h-6 text-gray-700" />
          <h2 className="text-2xl font-bold text-gray-900">System Configuration</h2>
          {currentProfile && (
            <span className="px-3 py-1 bg-blue-100 text-blue-700 text-sm rounded-full flex items-center gap-1">
              <Bookmark className="w-3 h-3" />
              {currentProfile}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExport}
            className="flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
            title="导出所有配置（包括 System Config、Agent Settings、Model Config、Profiles）"
          >
            <Download className="w-4 h-4" />
            Export
          </button>
          <label
            className="flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 cursor-pointer"
            title="导入配置（包括 System Config、Agent Settings、Model Config、Profiles）"
          >
            <Upload className="w-4 h-4" />
            Import
            <input type="file" accept=".json" onChange={handleImport} className="hidden" />
          </label>
          <button
            onClick={handleResetConfigs}
            disabled={saving}
            className="flex items-center gap-2 px-4 py-2 bg-gray-600 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50"
          >
            <RotateCcw className="w-4 h-4" />
            Reset
          </button>
        </div>
      </div>

      {/* Export/Import Info */}
      <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm text-gray-600">
        <p><strong>导入/导出说明：</strong>将包含 System Config、Agent Settings（Prompts 和 Model 分配）、Model Config（Provider 配置）和自定义 Profiles。</p>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-8">
          <button
            onClick={() => setActiveTab('configs')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'configs'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <Settings className="w-4 h-4" />
              Configurations
            </div>
          </button>
          <button
            onClick={() => setActiveTab('profiles')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'profiles'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4" />
              Profiles
            </div>
          </button>
        </nav>
      </div>

      {error && (
        <div className="bg-red-50 text-red-700 p-4 rounded-lg flex items-center gap-2">
          <AlertCircle className="w-5 h-5" />
          {error}
        </div>
      )}

      {success && (
        <div className="bg-green-50 text-green-700 p-4 rounded-lg flex items-center gap-2">
          <CheckCircle className="w-5 h-5" />
          {success}
        </div>
      )}

      {activeTab === 'configs' && (
        <>
          {/* Info Banner */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div className="flex items-start gap-3">
              <Infinity className="w-5 h-5 text-blue-500 mt-0.5" />
              <div className="text-sm text-blue-700">
                <p className="font-medium">Unlimited Value Support</p>
                <p className="mt-1">
                  For timeout/limit configurations, toggle the ∞ switch to set unlimited.
                  When unlimited, timeouts and limits will be disabled.
                </p>
              </div>
            </div>
          </div>

          {/* Modified Count & Batch Save */}
          {modifiedCount > 0 && (
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 flex items-center justify-between">
              <span className="text-orange-700">
                {modifiedCount} configuration(s) modified
              </span>
              <button
                onClick={handleBatchSave}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700"
              >
                <Save className="w-4 h-4" />
                Save All Changes
              </button>
            </div>
          )}

          {/* Config Groups */}
          <div className="space-y-6">
            {Object.entries(groupedConfigs).map(([category, categoryConfigs]) => (
              <div key={category} className="bg-white rounded-lg shadow">
                <div className="px-6 py-4 border-b border-gray-200">
                  <h3 className="text-lg font-medium text-gray-900 flex items-center gap-2">
                    <Clock className="w-5 h-5 text-gray-500" />
                    {category}
                  </h3>
                </div>
                <div className="divide-y divide-gray-200">
                  {categoryConfigs.map((config) => {
                    const isUnlimited = isUnlimitedValue(config.key, editedConfigs[config.key] || config.value);
                    const supportsUnlimited = isUnlimitedSupported(config.key);
                    const configType = categories?.metadata?.[config.key]?.type;

                    return (
                      <div key={config.key} className="px-6 py-4">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1">
                            <label className="block text-sm font-medium text-gray-900">
                              {getConfigLabel(config.key)}
                            </label>
                            <p className="text-sm text-gray-500 mt-1">{config.description}</p>
                          </div>
                          <div className="flex items-center gap-2">
                            {/* Unlimited toggle switch for supported configs */}
                            {supportsUnlimited && (
                              <div className="flex items-center">
                                <button
                                  onClick={() => handleUnlimitedToggle(config.key)}
                                  className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                                    isUnlimited ? 'bg-blue-600' : 'bg-gray-200'
                                  }`}
                                  title={isUnlimited ? 'Click to set limit' : 'Click to set unlimited'}
                                >
                                  <span
                                    className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                      isUnlimited ? 'translate-x-6' : 'translate-x-1'
                                    }`}
                                  />
                                </button>
                                <span className={`ml-2 text-xs font-medium ${isUnlimited ? 'text-blue-600' : 'text-gray-500'}`}>
                                  ∞
                                </span>
                              </div>
                            )}

                            {/* Value input - disabled when unlimited */}
                            {configType === 'boolean' ? (
                              <select
                                value={editedConfigs[config.key] ?? config.value}
                                onChange={(e) => handleConfigChange(config.key, e.target.value)}
                                className={`w-28 px-3 py-2 border rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 ${
                                  isModified(config.key)
                                    ? 'border-orange-300 bg-orange-50'
                                    : 'border-gray-300'
                                }`}
                              >
                                <option value="true">true</option>
                                <option value="false">false</option>
                              </select>
                            ) : (
                              <input
                                type="text"
                                value={editedConfigs[config.key] ?? config.value}
                                onChange={(e) => handleConfigChange(config.key, e.target.value)}
                                disabled={isUnlimited}
                                className={`w-28 px-3 py-2 border rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 text-right ${
                                  isModified(config.key)
                                    ? 'border-orange-300 bg-orange-50'
                                    : 'border-gray-300'
                                } ${isUnlimited ? 'bg-gray-100 text-gray-400 cursor-not-allowed' : ''}`}
                                placeholder={isUnlimited ? '∞' : ''}
                              />
                            )}

                            {getConfigUnit(config.key) && (
                              <span className="text-sm text-gray-500 w-12">
                                {isUnlimited ? '∞' : getConfigUnit(config.key)}
                              </span>
                            )}
                            <button
                              onClick={() => handleSaveConfig(config.key)}
                              disabled={saving || !isModified(config.key)}
                              className="flex items-center gap-1 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Save className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                        <p className="text-xs text-gray-400 mt-2">
                          Last updated: {new Date(config.updated_at).toLocaleString()}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {activeTab === 'profiles' && (
        <div className="space-y-4">
          {/* Quick Profile Actions */}
          <div className="bg-white rounded-lg shadow p-4">
            <h4 className="text-sm font-medium text-gray-700 mb-3">Quick Profile Actions</h4>
            <div className="flex flex-wrap gap-2">
              {profiles.filter(p => !p.is_default).slice(0, 5).map((profile) => (
                <button
                  key={profile.id}
                  onClick={() => handleLoadProfile(profile.id)}
                  disabled={saving}
                  className="flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                >
                  {PROFILE_ICONS[profile.name] || <Layers className="w-4 h-4" />}
                  <span>{profile.name}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Profile List */}
          <div className="bg-white rounded-lg shadow">
            <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
              <h3 className="text-lg font-medium text-gray-900">Configuration Profiles</h3>
              <button
                onClick={() => setShowNewProfile(true)}
                className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                <Plus className="w-4 h-4" />
                New Profile
              </button>
            </div>

            {/* New Profile Form */}
            {showNewProfile && (
              <div className="px-6 py-4 bg-gray-50 border-b border-gray-200">
                <div className="flex items-end gap-4">
                  <div className="flex-1">
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Profile Name
                    </label>
                    <input
                      type="text"
                      value={newProfileName}
                      onChange={(e) => setNewProfileName(e.target.value)}
                      placeholder="e.g., production, development"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md"
                    />
                  </div>
                  <div className="flex-1">
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      Description (optional)
                    </label>
                    <input
                      type="text"
                      value={newProfileDesc}
                      onChange={(e) => setNewProfileDesc(e.target.value)}
                      placeholder="Brief description"
                      className="w-full px-3 py-2 border border-gray-300 rounded-md"
                    />
                  </div>
                  <button
                    onClick={handleCreateProfile}
                    disabled={saving || !newProfileName.trim()}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                  >
                    Create
                  </button>
                  <button
                    onClick={() => {
                      setShowNewProfile(false);
                      setNewProfileName('');
                      setNewProfileDesc('');
                    }}
                    className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            {/* Profiles List */}
            <div className="divide-y divide-gray-200">
              {profiles.length === 0 ? (
                <div className="px-6 py-8 text-center text-gray-500">
                  No profiles configured. Create one to save and switch between configurations.
                </div>
              ) : (
                profiles.map((profile) => (
                  <div
                    key={profile.id}
                    className={`px-6 py-4 flex items-center justify-between ${
                      currentProfile === profile.name ? 'bg-blue-50' : ''
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-gray-100 flex items-center justify-center">
                        {PROFILE_ICONS[profile.name] || <Layers className="w-5 h-5 text-gray-500" />}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium text-gray-900">{profile.name}</span>
                          {profile.is_default && (
                            <span className="px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded">
                              Default
                            </span>
                          )}
                          {currentProfile === profile.name && (
                            <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-600 rounded">
                              Active
                            </span>
                          )}
                        </div>
                        {profile.description && (
                          <p className="text-sm text-gray-500 mt-1">{profile.description}</p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => handleLoadProfile(profile.id)}
                        disabled={saving}
                        className="flex items-center gap-1 px-3 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                        title="Load this profile"
                      >
                        <Play className="w-4 h-4" />
                        Load
                      </button>
                      <button
                        onClick={() => handleSaveToProfile(profile.id)}
                        disabled={saving}
                        className="flex items-center gap-1 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                        title="Save current config to this profile"
                      >
                        <RefreshCw className="w-4 h-4" />
                        Update
                      </button>
                      {!profile.is_default && (
                        <button
                          onClick={() => handleDeleteProfile(profile.id, profile.name)}
                          className="p-2 text-red-600 hover:bg-red-50 rounded-lg"
                          title="Delete this profile"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Help Text */}
      <div className="bg-gray-50 rounded-lg p-4 text-sm text-gray-600">
        <p className="font-medium mb-2">Tips:</p>
        <ul className="list-disc list-inside space-y-1">
          <li>Toggle the ∞ switch for unlimited timeout/limit values</li>
          <li>Use profiles to quickly switch between different configurations</li>
          <li>Export configurations to backup or share with others</li>
          <li>Import configurations from a JSON file</li>
          <li>Use "Update" button to save current config to an existing profile</li>
        </ul>
      </div>
    </div>
  );
};

export default SystemConfigPage;
