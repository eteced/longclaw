-- Migration: Add max_context_tokens column to agent_settings table
-- Date: 2026-03-30
-- Description: Add support for per-agent-type and per-agent-instance context limits

-- Add max_context_tokens column (NULL means use default, 0 means unlimited)
ALTER TABLE agent_settings ADD COLUMN IF NOT EXISTS max_context_tokens INT NULL;

-- Note: For MySQL/MariaDB, use the following instead:
-- ALTER TABLE agent_settings ADD COLUMN max_context_tokens INT NULL;
