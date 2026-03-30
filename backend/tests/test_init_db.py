"""
Tests for database initialization script.
Tests init_db.py functionality.
"""
import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.models.agent import Agent, AgentType, AgentStatus
from backend.models.channel import Channel, ChannelType
from backend.models.system_config import SystemConfig


class TestInitDBFunctions:
    """Tests for init_db.py functions."""

    @pytest.mark.asyncio
    async def test_default_configs_completeness(self):
        """Test that DEFAULT_CONFIGS has all required keys."""
        from scripts.init_db import DEFAULT_CONFIGS

        required_keys = [
            "resident_chat_timeout",
            "owner_task_timeout",
            "worker_subtask_timeout",
            "llm_request_timeout",
            "llm_connect_timeout",
            "tool_http_timeout",
            "tool_connect_timeout",
            "tool_max_rounds",
            "scheduler_agent_timeout",
            "scheduler_check_interval",
            "command_blacklist",
            "command_timeout",
            "memory_token_limit",
            "memory_keep_recent",
            "memory_compact_threshold",
            "reflect_check_interval",
            "reflect_stuck_threshold",
            "agent_max_context_tokens",
            "context_compact_threshold",
            "memory_search_limit",
        ]

        for key in required_keys:
            assert key in DEFAULT_CONFIGS, f"Missing required config key: {key}"
            assert "value" in DEFAULT_CONFIGS[key], f"Missing 'value' for config: {key}"
            assert "description" in DEFAULT_CONFIGS[key], f"Missing 'description' for config: {key}"

    @pytest.mark.asyncio
    async def test_default_configs_values_are_valid(self):
        """Test that DEFAULT_CONFIGS values are valid."""
        from scripts.init_db import DEFAULT_CONFIGS

        # Numeric configs should be valid numbers
        numeric_configs = [
            "resident_chat_timeout",
            "owner_task_timeout",
            "worker_subtask_timeout",
            "llm_request_timeout",
            "llm_connect_timeout",
            "tool_http_timeout",
            "tool_connect_timeout",
            "tool_max_rounds",
            "scheduler_agent_timeout",
            "scheduler_check_interval",
            "command_timeout",
            "memory_token_limit",
            "memory_keep_recent",
            "reflect_check_interval",
            "reflect_stuck_threshold",
            "agent_max_context_tokens",
            "memory_search_limit",
        ]

        for key in numeric_configs:
            value = DEFAULT_CONFIGS[key]["value"]
            # Allow -1 for unlimited
            if value == "-1":
                continue
            assert value.isdigit() or (value.startswith("-") and value[1:].isdigit()), \
                f"Config {key} should be numeric, got: {value}"

    @pytest.mark.asyncio
    async def test_init_system_config(self, db_session):
        """Test system configuration initialization."""
        from scripts.init_db import DEFAULT_CONFIGS, init_system_config

        # Run init_system_config (uses db_manager internally)
        await init_system_config()

        # Verify configs were created using the test session
        result = await db_session.execute(
            select(func.count(SystemConfig.config_key))
        )
        count = result.scalar_one()
        # Check that at least the expected number of configs exist
        # (config_service may have added more configs)
        assert count >= len(DEFAULT_CONFIGS), f"Expected at least {len(DEFAULT_CONFIGS)} configs, got {count}"

        # Verify a specific config
        result = await db_session.execute(
            select(SystemConfig).where(SystemConfig.config_key == "scheduler_agent_timeout")
        )
        config = result.scalar_one_or_none()
        assert config is not None
        assert config.config_value == "300"

    @pytest.mark.asyncio
    async def test_create_resident_agent(self, db_session):
        """Test resident agent creation."""
        from scripts.init_db import create_resident_agent

        # Create resident agent (uses db_manager internally)
        agent_id = await create_resident_agent()

        # Verify agent was created
        result = await db_session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()

        assert agent is not None
        assert agent.agent_type == AgentType.RESIDENT
        assert agent.name == "老六"
        assert agent.status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_create_web_channel(self, db_session):
        """Test web channel creation."""
        from scripts.init_db import create_resident_agent, create_web_channel

        # Create resident agent first
        agent_id = await create_resident_agent()

        # Create web channel
        channel_id = await create_web_channel(agent_id)

        # Verify channel was created
        result = await db_session.execute(
            select(Channel).where(Channel.id == channel_id)
        )
        channel = result.scalar_one_or_none()

        assert channel is not None
        assert channel.channel_type == ChannelType.WEB
        assert channel.resident_agent_id == agent_id
        assert channel.is_active == True

    @pytest.mark.asyncio
    async def test_verify_initialization(self, db_session):
        """Test initialization verification."""
        from scripts.init_db import (
            init_system_config,
            create_resident_agent,
            create_web_channel,
            verify_initialization,
        )

        # Run initialization steps
        await init_system_config()
        agent_id = await create_resident_agent()
        channel_id = await create_web_channel(agent_id)

        # Verify
        results = await verify_initialization()

        assert results["success"] == True
        assert results["resident_agent_count"] >= 1
        assert results["web_channel_count"] >= 1
        # Verify that agent_id and channel_id are present (exact match not guaranteed due to db_manager vs test session)
        assert "agent_id" in results
        assert "channel_id" in results


class TestConfigDefaults:
    """Tests for configuration default values."""

    @pytest.mark.asyncio
    async def test_scheduler_timeout_greater_than_check_interval(self):
        """Test that scheduler_agent_timeout is greater than check_interval."""
        from scripts.init_db import DEFAULT_CONFIGS

        timeout = int(DEFAULT_CONFIGS["scheduler_agent_timeout"]["value"])
        interval = int(DEFAULT_CONFIGS["scheduler_check_interval"]["value"])

        assert timeout > interval, \
            f"scheduler_agent_timeout ({timeout}) should be greater than scheduler_check_interval ({interval})"

    @pytest.mark.asyncio
    async def test_context_limits_are_positive(self):
        """Test that context limit config is positive."""
        from scripts.init_db import DEFAULT_CONFIGS

        total = int(DEFAULT_CONFIGS["agent_max_context_tokens"]["value"])

        # Total should be positive
        assert total > 0, \
            f"agent_max_context_tokens ({total}) should be positive"

    @pytest.mark.asyncio
    async def test_compact_threshold_in_valid_range(self):
        """Test that compact threshold is between 0 and 1."""
        from scripts.init_db import DEFAULT_CONFIGS

        threshold = float(DEFAULT_CONFIGS["context_compact_threshold"]["value"])
        assert 0 < threshold <= 1, \
            f"context_compact_threshold ({threshold}) should be between 0 and 1"


# Run tests with: pytest -v backend/tests/test_init_db.py
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
