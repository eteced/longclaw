import axios, { AxiosInstance } from 'axios';
import type {
  Task,
  TaskDetail,
  TaskListResponse,
  Subtask,
  Agent,
  AgentListResponse,
  Channel,
  ChannelListResponse,
  Message,
  MessageListResponse,
  TaskStatus,
  AgentType,
  AgentStatus,
  ChannelType,
  ModelConfig,
  ModelConfigUpdate,
  ModelInfoResponse,
  AllSettingsResponse,
  TypeSettings,
  TypeSettingsUpdate,
  InstanceSettings,
  InstanceSettingsUpdate,
  AllPromptsResponse,
  TypePrompt,
  TypePromptUpdate,
  InstancePrompt,
  InstancePromptUpdate,
  PromptType,
  SystemConfigItem,
  SystemConfigUpdate,
  ConfigCategories,
  ConfigProfile,
  ConfigProfileCreate,
  ConfigProfileUpdate,
  ConfigExport,
  FullConfigExport,
  ConfigImport,
  ConfigImportResult,
  ProfileLoadResult,
} from '../types';

const API_URL = import.meta.env.VITE_API_URL || '';
const API_KEY_STORAGE_KEY = 'longclaw_api_key';

class ApiService {
  private client: AxiosInstance;
  private apiKey: string | null = null;

  constructor() {
    // Load API key from localStorage
    this.apiKey = localStorage.getItem(API_KEY_STORAGE_KEY);

    this.client = axios.create({
      baseURL: API_URL ? `${API_URL}/api` : '/api',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    // Add request interceptor to include API key
    this.client.interceptors.request.use((config) => {
      if (this.apiKey) {
        config.headers['X-API-Key'] = this.apiKey;
      }
      return config;
    });

    // Add response interceptor to handle 401 errors
    this.client.interceptors.response.use(
      (response) => response,
      (error) => {
        if (error.response?.status === 401) {
          // Clear invalid API key
          this.setApiKey(null);
          // Dispatch event for auth state change
          window.dispatchEvent(new CustomEvent('auth:unauthorized'));
        }
        return Promise.reject(error);
      }
    );
  }

  setApiKey(key: string | null): void {
    this.apiKey = key;
    if (key) {
      localStorage.setItem(API_KEY_STORAGE_KEY, key);
    } else {
      localStorage.removeItem(API_KEY_STORAGE_KEY);
    }
  }

  getApiKey(): string | null {
    return this.apiKey;
  }

  async verifyApiKey(): Promise<boolean> {
    if (!this.apiKey) {
      return false;
    }
    try {
      await this.client.get('/verify');
      return true;
    } catch {
      return false;
    }
  }

  // ==================== Tasks ====================

  async getTasks(params?: {
    status?: TaskStatus;
    channel_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<TaskListResponse> {
    const response = await this.client.get<TaskListResponse>('/tasks', { params });
    return response.data;
  }

  async getTask(taskId: string): Promise<TaskDetail> {
    const response = await this.client.get<TaskDetail>(`/tasks/${taskId}`);
    return response.data;
  }

  async createTask(data: {
    title: string;
    description?: string;
    channel_id?: string;
    original_message?: string;
  }): Promise<Task> {
    const response = await this.client.post<Task>('/tasks', data);
    return response.data;
  }

  async updateTask(taskId: string, data: Partial<Task>): Promise<Task> {
    const response = await this.client.patch<Task>(`/tasks/${taskId}`, data);
    return response.data;
  }

  async terminateTask(taskId: string): Promise<Task> {
    const response = await this.client.post<Task>(`/tasks/${taskId}/terminate`);
    return response.data;
  }

  async getSubtasks(taskId: string): Promise<Subtask[]> {
    const response = await this.client.get<Subtask[]>(`/tasks/${taskId}/subtasks`);
    return response.data;
  }

  // ==================== Agents ====================

  async getAgents(params?: {
    agent_type?: AgentType;
    status?: AgentStatus;
    task_id?: string;
    limit?: number;
    offset?: number;
  }): Promise<AgentListResponse> {
    const response = await this.client.get<AgentListResponse>('/agents', { params });
    return response.data;
  }

  async getAgent(agentId: string): Promise<Agent> {
    const response = await this.client.get<Agent>(`/agents/${agentId}`);
    return response.data;
  }

  async getAgentMessages(agentId: string, params?: {
    limit?: number;
    offset?: number;
  }): Promise<Message[]> {
    const response = await this.client.get<Message[]>(`/agents/${agentId}/messages`, { params });
    return response.data;
  }

  async getAgentSummary(agentId: string): Promise<{ agent_id: string; summary: string }> {
    const response = await this.client.get<{ agent_id: string; summary: string }>(`/agents/${agentId}/summary`);
    return response.data;
  }

  // ==================== Channels ====================

  async getChannels(params?: {
    channel_type?: ChannelType;
    is_active?: boolean;
    limit?: number;
    offset?: number;
  }): Promise<ChannelListResponse> {
    const response = await this.client.get<ChannelListResponse>('/channels', { params });
    return response.data;
  }

  async getChannel(channelId: string): Promise<Channel> {
    const response = await this.client.get<Channel>(`/channels/${channelId}`);
    return response.data;
  }

  async createChannel(data: {
    channel_type: ChannelType;
    config?: Record<string, unknown>;
    resident_agent_id?: string;
  }): Promise<Channel> {
    const response = await this.client.post<Channel>('/channels', data);
    return response.data;
  }

  async updateChannel(channelId: string, data: {
    config?: Record<string, unknown>;
    resident_agent_id?: string;
    is_active?: boolean;
  }): Promise<Channel> {
    const response = await this.client.put<Channel>(`/channels/${channelId}`, data);
    return response.data;
  }

  async deleteChannel(channelId: string): Promise<void> {
    await this.client.delete(`/channels/${channelId}`);
  }

  // ==================== Messages ====================

  async getTaskMessages(taskId: string, params?: {
    limit?: number;
    offset?: number;
  }): Promise<MessageListResponse> {
    const response = await this.client.get<MessageListResponse>(`/messages/task/${taskId}`, { params });
    return response.data;
  }

  async getConversationMessages(conversationId: string, params?: {
    limit?: number;
    offset?: number;
  }): Promise<MessageListResponse> {
    const response = await this.client.get<MessageListResponse>(`/messages/conversation/${conversationId}`, { params });
    return response.data;
  }

  // ==================== Dashboard Stats ====================

  async getDashboardStats(): Promise<{
    runningTasks: number;
    completedTasks: number;
    terminatedTasks: number;
    activeAgents: number;
  }> {
    const [tasks, agents] = await Promise.all([
      this.getTasks({ limit: 100 }),
      this.getAgents({ limit: 100 }),
    ]);

    return {
      runningTasks: tasks.items.filter(t => t.status === 'running').length,
      completedTasks: tasks.items.filter(t => t.status === 'completed').length,
      terminatedTasks: tasks.items.filter(t => t.status === 'terminated').length,
      activeAgents: agents.items.filter(a => a.status === 'running' || a.status === 'idle').length,
    };
  }

  async getRecentActivities(limit: number = 10): Promise<Message[]> {
    const response = await this.client.get<MessageListResponse>('/messages/task/any', {
      params: { limit },
    }).catch(() => ({ data: { items: [], limit, offset: 0 } }));
    return response.data.items;
  }

  // ==================== Model Config ====================

  async getModelConfig(): Promise<ModelConfig> {
    const response = await this.client.get<ModelConfig>('/model-config');
    return response.data;
  }

  async updateModelConfig(data: ModelConfigUpdate): Promise<ModelConfig> {
    const response = await this.client.put<ModelConfig>('/model-config', data);
    return response.data;
  }

  async refreshModelConfig(): Promise<ModelConfig> {
    const response = await this.client.post<ModelConfig>('/model-config/refresh');
    return response.data;
  }

  async getModelInfo(provider: string, model: string): Promise<ModelInfoResponse> {
    const response = await this.client.get<ModelInfoResponse>(`/model-config/models/${provider}/${model}`);
    return response.data;
  }

  async setModelContextLimit(provider: string, model: string, maxContextTokens: number): Promise<ModelInfoResponse> {
    const response = await this.client.put<ModelInfoResponse>(
      `/model-config/models/${provider}/${model}/context-limit`,
      { max_context_tokens: maxContextTokens }
    );
    return response.data;
  }

  async setModelServiceMode(provider: string, model: string, serviceMode: 'parallel' | 'serial'): Promise<ModelInfoResponse> {
    const response = await this.client.put<ModelInfoResponse>(
      `/model-config/models/${provider}/${model}/service-mode`,
      { service_mode: serviceMode }
    );
    return response.data;
  }

  async getAllContextLimits(): Promise<Record<string, number>> {
    const response = await this.client.get<Record<string, number>>('/model-config/context-limits');
    return response.data;
  }

  // ==================== Agent Settings ====================

  async getAllSettings(): Promise<AllSettingsResponse> {
    const response = await this.client.get<AllSettingsResponse>('/agent-settings');
    return response.data;
  }

  async getTypeSettings(agentType: string): Promise<TypeSettings> {
    const response = await this.client.get<TypeSettings>(`/agent-settings/type/${agentType}`);
    return response.data;
  }

  async updateTypeSettings(agentType: string, data: TypeSettingsUpdate): Promise<TypeSettings> {
    const response = await this.client.put<TypeSettings>(`/agent-settings/type/${agentType}`, data);
    return response.data;
  }

  async resetTypeSettings(agentType: string): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/agent-settings/type/${agentType}`);
    return response.data;
  }

  async getAgentSettings(agentId: string): Promise<InstanceSettings> {
    const response = await this.client.get<InstanceSettings>(`/agent-settings/agent/${agentId}`);
    return response.data;
  }

  async updateAgentSettings(agentId: string, data: InstanceSettingsUpdate): Promise<InstanceSettings> {
    const response = await this.client.put<InstanceSettings>(`/agent-settings/agent/${agentId}`, data);
    return response.data;
  }

  async deleteAgentSettings(agentId: string): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/agent-settings/agent/${agentId}`);
    return response.data;
  }

  async setTypeModel(agentType: string, providerName: string, modelName: string): Promise<TypeSettings> {
    const response = await this.client.put<TypeSettings>(
      `/agent-settings/type/${agentType}/model`,
      { provider_name: providerName, model_name: modelName }
    );
    return response.data;
  }

  async setAgentModel(agentId: string, providerName: string, modelName: string): Promise<InstanceSettings> {
    const response = await this.client.put<InstanceSettings>(
      `/agent-settings/agent/${agentId}/model`,
      { provider_name: providerName, model_name: modelName }
    );
    return response.data;
  }

  // ==================== Agent Prompts (Legacy - deprecated) ====================

  async getAllPrompts(): Promise<AllPromptsResponse> {
    const response = await this.client.get<AllPromptsResponse>('/prompts');
    return response.data;
  }

  async getTypePrompt(promptType: PromptType): Promise<TypePrompt> {
    const response = await this.client.get<TypePrompt>(`/prompts/type/${promptType}`);
    return response.data;
  }

  async updateTypePrompt(promptType: PromptType, data: TypePromptUpdate): Promise<TypePrompt> {
    const response = await this.client.put<TypePrompt>(`/prompts/type/${promptType}`, data);
    return response.data;
  }

  async resetTypePrompt(promptType: PromptType): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/prompts/type/${promptType}`);
    return response.data;
  }

  async setAgentPrompt(agentId: string, data: InstancePromptUpdate): Promise<InstancePrompt> {
    const response = await this.client.put<InstancePrompt>(`/prompts/agent/${agentId}`, data);
    return response.data;
  }

  async deleteAgentPrompt(agentId: string): Promise<{ message: string }> {
    const response = await this.client.delete<{ message: string }>(`/prompts/agent/${agentId}`);
    return response.data;
  }

  // ==================== System Config ====================

  async getSystemConfigs(): Promise<SystemConfigItem[]> {
    const response = await this.client.get<SystemConfigItem[]>('/system-config');
    return response.data;
  }

  async getSystemConfig(key: string): Promise<SystemConfigItem> {
    const response = await this.client.get<SystemConfigItem>(`/system-config/${key}`);
    return response.data;
  }

  async getConfigCategories(): Promise<ConfigCategories> {
    const response = await this.client.get<ConfigCategories>('/system-config/categories');
    return response.data;
  }

  async updateSystemConfig(key: string, data: SystemConfigUpdate): Promise<SystemConfigItem> {
    const response = await this.client.put<SystemConfigItem>(`/system-config/${key}`, data);
    return response.data;
  }

  async batchUpdateSystemConfigs(configs: Record<string, string>): Promise<{ updated: number; keys: string[] }> {
    const response = await this.client.put<{ updated: number; keys: string[] }>('/system-config', { configs });
    return response.data;
  }

  async resetSystemConfigs(): Promise<SystemConfigItem[]> {
    const response = await this.client.post<SystemConfigItem[]>('/system-config/reset');
    return response.data;
  }

  // ==================== Config Export/Import ====================

  async exportConfig(): Promise<ConfigExport> {
    const response = await this.client.get<ConfigExport>('/system-config/export/json');
    return response.data;
  }

  async exportFullConfig(): Promise<FullConfigExport> {
    const response = await this.client.get<FullConfigExport>('/system-config/export/full');
    return response.data;
  }

  async importConfig(data: ConfigImport, merge: boolean = true): Promise<ConfigImportResult> {
    const response = await this.client.post<ConfigImportResult>('/system-config/import', data, {
      params: { merge },
    });
    return response.data;
  }

  // ==================== Config Profiles ====================

  async getConfigProfiles(): Promise<ConfigProfile[]> {
    const response = await this.client.get<ConfigProfile[]>('/system-config/profiles');
    return response.data;
  }

  async getConfigProfile(profileId: string): Promise<ConfigProfile> {
    const response = await this.client.get<ConfigProfile>(`/system-config/profiles/${profileId}`);
    return response.data;
  }

  async createConfigProfile(data: ConfigProfileCreate): Promise<ConfigProfile> {
    const response = await this.client.post<ConfigProfile>('/system-config/profiles', data);
    return response.data;
  }

  async updateConfigProfile(profileId: string, data: ConfigProfileUpdate): Promise<ConfigProfile> {
    const response = await this.client.put<ConfigProfile>(`/system-config/profiles/${profileId}`, data);
    return response.data;
  }

  async deleteConfigProfile(profileId: string): Promise<{ deleted: boolean; profile_id: string }> {
    const response = await this.client.delete<{ deleted: boolean; profile_id: string }>(`/system-config/profiles/${profileId}`);
    return response.data;
  }

  async loadConfigProfile(profileId: string): Promise<ProfileLoadResult> {
    const response = await this.client.post<ProfileLoadResult>(`/system-config/profiles/${profileId}/load`);
    return response.data;
  }

  async saveCurrentToProfile(profileId: string): Promise<ConfigProfile> {
    const response = await this.client.post<ConfigProfile>(`/system-config/profiles/${profileId}/save`);
    return response.data;
  }
}

export const api = new ApiService();
export default api;
