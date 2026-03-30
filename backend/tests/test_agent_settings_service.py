"""Tests for AgentSettingsService."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models.agent import AgentType
from backend.services.agent_settings_service import agent_settings_service


class TestAgentSettingsService:
    """Tests for AgentSettingsService methods."""

    @pytest.mark.asyncio
    async def test_get_type_settings_default(self):
        """Test getting type-level settings with default values."""
        # Create a mock session
        mock_session = AsyncMock()

        # Mock the database query to return None (no existing settings)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        # Call the service
        with patch('backend.services.agent_settings_service.agent_settings_service.get_type_settings') as mock_get:
            mock_get.return_value = None
            result = await agent_settings_service.get_type_settings(mock_session, AgentType.RESIDENT)

        # Result should be None if no settings exist
        assert result is None

    @pytest.mark.asyncio
    async def test_set_type_prompt(self):
        """Test setting type-level prompt."""
        mock_session = AsyncMock()

        # Mock existing settings query
        mock_result = MagicMock()
        mock_existing = MagicMock()
        mock_existing.system_prompt = "Old prompt"
        mock_existing.agent_type = AgentType.RESIDENT  # Set the agent_type attribute
        mock_result.scalar_one_or_none.return_value = mock_existing
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        # Call the service
        new_prompt = "New system prompt for resident agent"
        result = await agent_settings_service.set_type_prompt(
            mock_session, AgentType.RESIDENT, new_prompt
        )

        # Verify the prompt was updated
        assert result.system_prompt == new_prompt
        assert result.agent_type == AgentType.RESIDENT

    @pytest.mark.asyncio
    async def test_set_type_model(self):
        """Test setting type-level model assignment."""
        mock_session = AsyncMock()

        # Mock existing settings query
        mock_result = MagicMock()
        mock_existing = MagicMock()
        mock_existing.provider_name = None
        mock_existing.model_name = None
        mock_result.scalar_one_or_none.return_value = mock_existing
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        # Call the service
        result = await agent_settings_service.set_type_model(
            mock_session, AgentType.RESIDENT, "openai", "gpt-4o"
        )

        # Verify the model was set
        assert result.provider_name == "openai"
        assert result.model_name == "gpt-4o"

    @pytest.mark.asyncio
    async def test_instance_override_prompt(self):
        """Test that instance-level settings override type-level."""
        mock_session = AsyncMock()

        # Mock instance-level settings query
        mock_result = MagicMock()
        mock_instance = MagicMock()
        mock_instance.system_prompt = "Instance-specific prompt"
        mock_instance.provider_name = "deepseek"
        mock_instance.model_name = "deepseek-chat"
        mock_result.scalar_one_or_none.return_value = mock_instance
        mock_session.execute.return_value = mock_result

        # Call get_effective_prompt
        result = await agent_settings_service.get_effective_prompt(
            mock_session, "agent-123", AgentType.RESIDENT
        )

        # Should return instance-level prompt
        assert result == "Instance-specific prompt"

    @pytest.mark.asyncio
    async def test_instance_override_model(self):
        """Test that instance-level model assignment overrides type-level."""
        mock_session = AsyncMock()

        # Mock instance-level settings query
        mock_result = MagicMock()
        mock_instance = MagicMock()
        mock_instance.provider_name = "deepseek"
        mock_instance.model_name = "deepseek-chat"
        mock_result.scalar_one_or_none.return_value = mock_instance
        mock_session.execute.return_value = mock_result

        # Call get_effective_model
        provider, model = await agent_settings_service.get_effective_model(
            mock_session, "agent-123", AgentType.RESIDENT
        )

        # Should return instance-level model
        assert provider == "deepseek"
        assert model == "deepseek-chat"

    @pytest.mark.asyncio
    async def test_get_effective_model_fallback(self):
        """Test fallback to type-level when no instance settings."""
        mock_session = AsyncMock()

        # First call: instance-level query returns None
        # Second call: type-level query returns settings
        mock_result_instance = MagicMock()
        mock_result_instance.scalar_one_or_none.return_value = None

        mock_result_type = MagicMock()
        mock_type_settings = MagicMock()
        mock_type_settings.provider_name = "openai"
        mock_type_settings.model_name = "gpt-4o-mini"
        mock_result_type.scalar_one_or_none.return_value = mock_type_settings

        mock_session.execute.side_effect = [mock_result_instance, mock_result_type]

        # Call get_effective_model
        provider, model = await agent_settings_service.get_effective_model(
            mock_session, "agent-456", AgentType.OWNER
        )

        # Should fall back to type-level model
        assert provider == "openai"
        assert model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_delete_instance_settings(self):
        """Test deleting instance-level settings."""
        mock_session = AsyncMock()

        # Mock the delete query
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        # Call delete_agent_settings
        result = await agent_settings_service.delete_agent_settings(
            mock_session, "agent-789"
        )

        # Should return True if settings were deleted
        assert result is True

    @pytest.mark.asyncio
    async def test_reset_type_settings(self):
        """Test resetting type-level settings to default."""
        mock_session = AsyncMock()

        # Mock the delete query
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        # Call reset_type_settings
        result = await agent_settings_service.reset_type_settings(
            mock_session, AgentType.WORKER
        )

        # Should return True if settings were reset
        assert result is True


class TestAgentSettingsServiceIntegration:
    """Integration tests for AgentSettingsService."""

    @pytest.mark.asyncio
    async def test_full_settings_lifecycle(self):
        """Test the full lifecycle of settings: create, read, update, delete."""
        mock_session = AsyncMock()

        # Setup mocks for create
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        # Create type-level settings
        type_settings = await agent_settings_service.set_type_prompt(
            mock_session, AgentType.RESIDENT, "Default resident prompt"
        )
        assert type_settings.system_prompt == "Default resident prompt"

        # Set model for type
        type_settings = await agent_settings_service.set_type_model(
            mock_session, AgentType.RESIDENT, "openai", "gpt-4o"
        )
        assert type_settings.provider_name == "openai"
        assert type_settings.model_name == "gpt-4o"
