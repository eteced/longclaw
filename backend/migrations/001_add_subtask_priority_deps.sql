-- Migration: Add priority and depends_on columns to subtasks table
-- Date: 2026-03-29
-- Description: Add support for subtask priority and dependencies

-- Add priority column (default 0, higher = more important)
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS priority INT NOT NULL DEFAULT 0;

-- Add depends_on column (JSON array of subtask IDs that must complete first)
ALTER TABLE subtasks ADD COLUMN IF NOT EXISTS depends_on JSON DEFAULT NULL;

-- Create index on priority for faster sorting
CREATE INDEX IF NOT EXISTS idx_subtasks_priority ON subtasks(priority);

-- Note: For MySQL/MariaDB, use the following instead:
-- ALTER TABLE subtasks ADD COLUMN priority INT NOT NULL DEFAULT 0;
-- ALTER TABLE subtasks ADD COLUMN depends_on JSON DEFAULT NULL;
-- CREATE INDEX idx_subtasks_priority ON subtasks(priority);
