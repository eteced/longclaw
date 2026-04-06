// Task types
export type TaskStatus = 'planning' | 'running' | 'paused' | 'completed' | 'terminated' | 'error';

export interface SubtaskStats {
  total: number;
  completed: number;
  running: number;
  failed: number;
  pending: number;
}

export interface Task {
  id: string;
  title: string;
  description: string | null;
  status: TaskStatus;
  owner_agent_id: string | null;
  channel_id: string | null;
  original_message: string | null;
  plan: Record<string, unknown> | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  terminated_at: string | null;
  subtask_stats: SubtaskStats;
}

export interface TaskDetail extends Task {
  subtasks: Subtask[];
}

export interface TaskListResponse {
  items: Task[];
  total: number;
  limit: number;
  offset: number;
}

// Subtask types
export type SubtaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export interface Subtask {
  id: string;
  task_id: string;
  parent_subtask_id: string | null;
  title: string;
  description: string | null;
  status: SubtaskStatus;
  worker_agent_id: string | null;
  summary: string | null;
  result: Record<string, unknown> | null;
  order_index: number | null;
  priority: number;
  depends_on: string[] | null;
  created_at: string;
  completed_at: string | null;
}

// Agent types
export type AgentType = 'resident' | 'owner' | 'worker' | 'sub';
export type AgentStatus = 'idle' | 'running' | 'paused' | 'terminated' | 'error';

export interface ModelAssignment {
  provider: string | null;
  model: string | null;
  slot_id: string | null;
  slot_index: number | null;
}

export interface Agent {
  id: string;
  agent_type: AgentType;
  name: string;
  personality: string | null;
  status: AgentStatus;
  error_message: string | null;
  parent_agent_id: string | null;
  task_id: string | null;
  model_config: Record<string, unknown> | null;
  model_assignment: ModelAssignment | null;
  created_at: string;
  updated_at: string;
  terminated_at: string | null;
}

export interface AgentListResponse {
  items: Agent[];
  total: number;
  limit: number;
  offset: number;
}

// Channel types
export type ChannelType = 'qqbot' | 'telegram' | 'web' | 'api';

export interface Channel {
  id: string;
  channel_type: ChannelType;
  config: Record<string, unknown> | null;
  resident_agent_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ChannelListResponse {
  items: Channel[];
  limit: number;
  offset: number;
}

// Message types
export type SenderType = 'channel' | 'resident' | 'owner' | 'worker' | 'system' | 'agent';
export type ReceiverType = 'channel' | 'resident' | 'owner' | 'worker' | 'user' | 'agent';
export type MessageType = 'text' | 'task' | 'report' | 'error' | 'system';

export interface Message {
  id: string;
  conversation_id: string | null;
  sender_type: SenderType;
  sender_id: string | null;
  receiver_type: ReceiverType;
  receiver_id: string | null;
  message_type: MessageType;
  content: string | null;
  metadata: Record<string, unknown> | null;
  task_id: string | null;
  subtask_id: string | null;
  created_at: string;
}

export interface MessageListResponse {
  items: Message[];
  limit: number;
  offset: number;
}

// Dashboard stats
export interface DashboardStats {
  runningTasks: number;
  completedTasks: number;
  terminatedTasks: number;
  activeAgents: number;
}

export interface RecentActivity {
  id: string;
  type: 'task' | 'message' | 'agent';
  content: string;
  created_at: string;
}

// Model Config types
export interface ModelInfo {
  name: string;
  max_context_tokens: number;
  max_parallel_requests: number;
}

export interface ProviderConfig {
  name: string;
  display_name?: string;
  base_url: string;
  api_key?: string;
  max_parallel_requests: number;
  models: ModelInfo[];
}

export interface ModelConfig {
  id: string;
  default_provider: string;
  providers: ProviderConfig[];
  created_at: string;
  updated_at: string;
}

export interface ModelConfigUpdate {
  default_provider?: string;
  providers?: ProviderConfig[];
}

export interface ModelInfoResponse {
  provider: string;
  model: string;
  max_context_tokens: number;
  max_parallel_requests: number;
}

// Provider Scheduler types
export interface SchedulerStatus {
  total_active: number;
  by_provider: Record<string, ProviderSlotAllocation[]>;
  allocations: SlotAllocation[];
  provider_config: {
    total_max: Record<string, number>;
    model_max: Record<string, Record<string, number>>;
  };
}

export interface SlotAllocation {
  id: string;
  agent_id: string;
  provider_name: string;
  model_name: string;
  priority: number;
  priority_reason: string | null;
  allocated_at: string;
  last_heartbeat: string;
  is_active: boolean;
  is_released: boolean;
  slot_index: number;
  operation_type: string | null;
  task_id: string | null;
  subtask_id: string | null;
}

export interface ProviderSlotAllocation {
  slot_id: string;
  agent_id: string;
  model: string;
  slot_index: number;
  priority: number;
  operation: string;
}

export interface SchedulerSummary {
  total_allocated: number;
  by_provider: ProviderSummary[];
}

export interface ProviderSummary {
  provider_name: string;
  allocated: number;
  max: number;
  models: ModelSummary[];
}

export interface ModelSummary {
  model_name: string;
  allocated: number;
  max: number;
  slots: AgentSlotInfo[];
}

export interface AgentSlotInfo {
  slot_index: number;
  agent_id: string;
  agent_name: string;
  operation: string;
  priority: number;
}

// Agent Settings types (replaces Agent Prompt types)
export interface TypeSettings {
  id: string | null;
  agent_type: string;
  system_prompt: string;
  provider_name: string | null;
  model_name: string | null;
  max_context_tokens: number | null;
  is_default?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface InstanceSettings {
  id: string;
  agent_id: string;
  system_prompt: string;
  provider_name: string | null;
  model_name: string | null;
  max_context_tokens: number | null;
  created_at: string;
  updated_at: string;
}

export interface AllSettingsResponse {
  type_settings: Record<string, TypeSettings>;
  instance_settings: Record<string, InstanceSettings>;
}

export interface TypeSettingsUpdate {
  system_prompt?: string;
  provider_name?: string;
  model_name?: string;
  max_context_tokens?: number | null;
}

export interface InstanceSettingsUpdate {
  system_prompt?: string;
  provider_name?: string;
  model_name?: string;
  max_context_tokens?: number | null;
}

export interface ModelAssignmentUpdate {
  provider_name: string;
  model_name: string;
}

// Legacy Agent Prompt types (deprecated, kept for backwards compatibility)
export type PromptType = 'RESIDENT' | 'OWNER' | 'WORKER' | 'SUB';

export interface TypePrompt {
  id: string | null;
  agent_type: PromptType;
  system_prompt: string;
  is_default?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface InstancePrompt {
  id: string;
  agent_id: string;
  system_prompt: string;
  created_at: string;
  updated_at: string;
}

export interface AllPromptsResponse {
  type_prompts: Record<PromptType, TypePrompt>;
  instance_prompts: Record<string, InstancePrompt>;
}

export interface TypePromptUpdate {
  system_prompt: string;
}

export interface InstancePromptUpdate {
  system_prompt: string;
}

// System Config types
export interface SystemConfigItem {
  key: string;
  value: string;
  description: string | null;
  updated_at: string;
  metadata?: ConfigMetadata;
}

export interface SystemConfigUpdate {
  value: string;
}

export interface ConfigMetadata {
  type: string;
  category: string;
  unlimited_value: number | null;
  display_name: string;
  unit: string | null;
  min_value: number;
  max_value: number;
}

export interface ConfigCategories {
  categories: Record<string, string[]>;
  metadata: Record<string, ConfigMetadata>;
  unlimited_value: number;
}

// Config Profile types
export interface ConfigProfile {
  id: string;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
  config_data?: Record<string, string>;
}

export interface ConfigProfileCreate {
  name: string;
  description?: string;
  config_data?: Record<string, string>;
}

export interface ConfigProfileUpdate {
  name?: string;
  description?: string;
  config_data?: Record<string, string>;
}

export interface ConfigExport {
  version: string;
  exported_at: string;
  configs: Record<string, { value: string; description: string | null }>;
}

// Full config export (v2.0) includes agent settings and model config
export interface FullConfigExport {
  version: string;
  exported_at: string;
  unlimited_value: number;
  system_configs: Record<string, { value: string; description: string | null }>;
  agent_settings: Record<string, {
    system_prompt: string;
    provider_name: string | null;
    model_name: string | null;
    max_context_tokens: number | null;
  }>;
  model_config: {
    default_provider: string;
    providers: Array<{
      name: string;
      display_name?: string;
      base_url: string;
      api_key?: string;
      service_mode?: string;
      models: Array<{ name: string; max_context_tokens: number }>;
    }>;
  };
  profiles: Array<{
    name: string;
    description: string;
    config_data: Record<string, string>;
  }>;
}

export interface ConfigImport {
  version: string;
  configs?: Record<string, string | { value: string; description?: string }>;
  // v2.0 format fields
  system_configs?: Record<string, { value: string; description: string | null }>;
  agent_settings?: Record<string, {
    system_prompt: string;
    provider_name: string | null;
    model_name: string | null;
    max_context_tokens: number | null;
  }>;
  model_config?: {
    default_provider: string;
    providers: Array<{
      name: string;
      display_name?: string;
      base_url: string;
      api_key?: string;
      service_mode?: string;
      models: Array<{ name: string; max_context_tokens: number }>;
    }>;
  };
  profiles?: Array<{
    name: string;
    description: string;
    config_data: Record<string, string>;
  }>;
}

export interface ConfigImportResult {
  imported: number;
  skipped: number;
  errors: string[];
  // v2.0 format detailed results
  system_configs?: { imported: number; skipped: number; errors: string[] };
  agent_settings?: { imported: number; skipped: number; errors: string[] };
  model_config?: { imported: boolean; error: string | null };
  profiles?: { imported: number; errors: string[] };
}

export interface ProfileLoadResult {
  profile_name: string;
  applied: number;
  skipped: number;
}

// Skill types
export interface Skill {
  name: string;
  category: string;
  description: string;
  content: string | null;
  is_builtin: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface SkillListItem {
  name: string;
  category: string;
  description: string;
  is_builtin: boolean;
}

export interface SkillListResponse {
  items: SkillListItem[];
  total: number;
}

export interface SkillCreate {
  name: string;
  category: string;
  description: string;
  content: string;
}

export interface SkillUpdate {
  description?: string;
  content?: string;
}

export interface CategoryListResponse {
  categories: string[];
}

export interface SkillSearchResponse {
  items: Skill[];
  total: number;
}
