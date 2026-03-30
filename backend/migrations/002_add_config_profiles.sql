-- Migration: Add config_profiles table for system configuration scenarios
-- Date: 2026-03-29
-- Description: Support saving and switching between configuration profiles

CREATE TABLE IF NOT EXISTS config_profiles (
    id VARCHAR(36) PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    config_data JSON NOT NULL,
    is_default BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert default profile
INSERT INTO config_profiles (id, name, description, config_data, is_default)
SELECT
    UUID() as id,
    'default' as name,
    '默认配置' as description,
    JSON_OBJECT(
        'resident_chat_timeout', '600',
        'owner_task_timeout', '600',
        'worker_subtask_timeout', '180',
        'llm_request_timeout', '300',
        'llm_connect_timeout', '30',
        'tool_http_timeout', '30',
        'tool_connect_timeout', '10',
        'tool_max_rounds', '6',
        'scheduler_agent_timeout', '300',
        'scheduler_check_interval', '10',
        'memory_token_limit', '4000',
        'memory_keep_recent', '5',
        'memory_compact_threshold', '0.8',
        'agent_max_context_tokens', '8192',
        'resident_agent_max_context', '8192',
        'owner_agent_max_context', '4096',
        'worker_agent_max_context', '2048',
        'context_compact_threshold', '0.8',
        'memory_search_limit', '5'
    ) as config_data,
    TRUE as is_default
WHERE NOT EXISTS (SELECT 1 FROM config_profiles WHERE name = 'default');

-- Insert 'unlimited' profile for long-running tasks
INSERT INTO config_profiles (id, name, description, config_data, is_default)
SELECT
    UUID() as id,
    'unlimited' as name,
    '无限制模式 - 适用于长时间运行的任务' as description,
    JSON_OBJECT(
        'resident_chat_timeout', '-1',
        'owner_task_timeout', '-1',
        'worker_subtask_timeout', '-1',
        'llm_request_timeout', '-1',
        'llm_connect_timeout', '60',
        'tool_http_timeout', '-1',
        'tool_connect_timeout', '30',
        'tool_max_rounds', '-1',
        'scheduler_agent_timeout', '-1',
        'scheduler_check_interval', '30',
        'memory_token_limit', '-1',
        'memory_keep_recent', '10',
        'memory_compact_threshold', '0.9',
        'agent_max_context_tokens', '-1',
        'resident_agent_max_context', '-1',
        'owner_agent_max_context', '-1',
        'worker_agent_max_context', '-1',
        'context_compact_threshold', '0.9',
        'memory_search_limit', '10'
    ) as config_data,
    FALSE as is_default
WHERE NOT EXISTS (SELECT 1 FROM config_profiles WHERE name = 'unlimited');

-- Insert 'fast' profile for quick responses
INSERT INTO config_profiles (id, name, description, config_data, is_default)
SELECT
    UUID() as id,
    'fast' as name,
    '快速模式 - 适用于简单任务，快速响应' as description,
    JSON_OBJECT(
        'resident_chat_timeout', '120',
        'owner_task_timeout', '180',
        'worker_subtask_timeout', '60',
        'llm_request_timeout', '60',
        'llm_connect_timeout', '10',
        'tool_http_timeout', '15',
        'tool_connect_timeout', '5',
        'tool_max_rounds', '3',
        'scheduler_agent_timeout', '120',
        'scheduler_check_interval', '5',
        'memory_token_limit', '2000',
        'memory_keep_recent', '3',
        'memory_compact_threshold', '0.7',
        'agent_max_context_tokens', '4096',
        'resident_agent_max_context', '4096',
        'owner_agent_max_context', '2048',
        'worker_agent_max_context', '1024',
        'context_compact_threshold', '0.7',
        'memory_search_limit', '3'
    ) as config_data,
    FALSE as is_default
WHERE NOT EXISTS (SELECT 1 FROM config_profiles WHERE name = 'fast');
