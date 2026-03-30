"""Tests for ModelConfigService extensions (context limit and service mode)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.model_config_service import model_config_service, DEFAULT_MODEL_CONTEXT_LIMITS


class TestModelConfigServiceExtensions:
    """Tests for ModelConfigService context limit and service mode methods."""

    @pytest.mark.asyncio
    async def test_get_model_context_limit(self):
        """Test getting context limit for a specific model."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_model_context_limit
        limit = await model_config_service.get_model_context_limit(
            mock_session, "openai", "gpt-4o"
        )

        # Should return the configured limit
        assert limit == 128000

    @pytest.mark.asyncio
    async def test_get_model_context_limit_default(self):
        """Test getting context limit for a model not in config (uses DEFAULT_MODEL_CONTEXT_LIMITS)."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_model_context_limit for a model not in config
        limit = await model_config_service.get_model_context_limit(
            mock_session, "openai", "gpt-3.5-turbo"
        )

        # Should return the default from DEFAULT_MODEL_CONTEXT_LIMITS
        assert limit == DEFAULT_MODEL_CONTEXT_LIMITS.get("gpt-3.5-turbo", 8192)

    @pytest.mark.asyncio
    async def test_set_model_context_limit(self):
        """Test setting context limit for a specific model."""
        mock_session = AsyncMock()

        # Mock the config query and update
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        # Call set_model_context_limit
        result = await model_config_service.set_model_context_limit(
            mock_session, "openai", "gpt-4o", 64000
        )

        # Should return True indicating success
        assert result is True

    @pytest.mark.asyncio
    async def test_set_model_context_limit_model_not_found(self):
        """Test setting context limit for a non-existent model."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call set_model_context_limit for non-existent model
        result = await model_config_service.set_model_context_limit(
            mock_session, "openai", "non-existent-model", 64000
        )

        # Should return False indicating model not found
        assert result is False

    @pytest.mark.asyncio
    async def test_get_provider_service_mode(self):
        """Test getting service mode for a specific provider."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "deepseek",
                "service_mode": "serial",
                "models": [
                    {"name": "deepseek-chat", "max_context_tokens": 64000},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_provider_service_mode
        mode = await model_config_service.get_provider_service_mode(
            mock_session, "deepseek"
        )

        # Should return the configured service mode
        assert mode == "serial"

    @pytest.mark.asyncio
    async def test_get_provider_service_mode_default(self):
        """Test getting service mode when not configured (defaults to 'parallel')."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_provider_service_mode
        mode = await model_config_service.get_provider_service_mode(
            mock_session, "openai"
        )

        # Should return default 'parallel'
        assert mode == "parallel"

    @pytest.mark.asyncio
    async def test_set_provider_service_mode(self):
        """Test setting service mode for a specific provider."""
        mock_session = AsyncMock()

        # Mock the config query and update
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "deepseek",
                "service_mode": "parallel",
                "models": [
                    {"name": "deepseek-chat", "max_context_tokens": 64000},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result
        mock_session.flush = AsyncMock()

        # Call set_provider_service_mode
        result = await model_config_service.set_provider_service_mode(
            mock_session, "deepseek", "serial"
        )

        # Should return True indicating success
        assert result is True

    @pytest.mark.asyncio
    async def test_set_provider_service_mode_invalid(self):
        """Test setting invalid service mode raises error."""
        mock_session = AsyncMock()

        # Call set_provider_service_mode with invalid mode
        with pytest.raises(ValueError, match="Invalid service mode"):
            await model_config_service.set_provider_service_mode(
                mock_session, "openai", "invalid_mode"
            )

    @pytest.mark.asyncio
    async def test_get_all_model_context_limits(self):
        """Test getting all model context limits across providers."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                    {"name": "gpt-4o-mini", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            },
            {
                "name": "deepseek",
                "models": [
                    {"name": "deepseek-chat", "max_context_tokens": 64000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_all_model_context_limits
        limits = await model_config_service.get_all_model_context_limits(mock_session)

        # Should return a dict with provider/model keys
        assert "openai/gpt-4o" in limits
        assert limits["openai/gpt-4o"] == 128000
        assert "openai/gpt-4o-mini" in limits
        assert limits["openai/gpt-4o-mini"] == 128000
        assert "deepseek/deepseek-chat" in limits
        assert limits["deepseek/deepseek-chat"] == 64000

    @pytest.mark.asyncio
    async def test_default_context_limits_dict(self):
        """Test that DEFAULT_MODEL_CONTEXT_LIMITS contains expected models."""
        # Check some expected defaults
        assert "gpt-4o" in DEFAULT_MODEL_CONTEXT_LIMITS
        assert DEFAULT_MODEL_CONTEXT_LIMITS["gpt-4o"] == 128000
        assert "deepseek-chat" in DEFAULT_MODEL_CONTEXT_LIMITS
        assert DEFAULT_MODEL_CONTEXT_LIMITS["deepseek-chat"] == 64000
        # Check a model that should use default (8192)
        assert DEFAULT_MODEL_CONTEXT_LIMITS.get("unknown-model", 8192) == 8192


class TestModelConfigServiceProviderConfig:
    """Tests for provider configuration methods."""

    @pytest.mark.asyncio
    async def test_get_provider_config(self):
        """Test getting configuration for a specific provider."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {
                "name": "openai",
                "base_url": "https://api.openai.com/v1",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_provider_config
        provider_config = await model_config_service.get_provider_config(
            mock_session, "openai"
        )

        # Should return the provider config
        assert provider_config is not None
        assert provider_config["name"] == "openai"
        assert provider_config["base_url"] == "https://api.openai.com/v1"

    @pytest.mark.asyncio
    async def test_get_provider_config_not_found(self):
        """Test getting configuration for a non-existent provider."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.providers = [
            {"name": "openai", "models": []}
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_provider_config
        provider_config = await model_config_service.get_provider_config(
            mock_session, "non-existent-provider"
        )

        # Should return None
        assert provider_config is None

    @pytest.mark.asyncio
    async def test_get_default_provider_config(self):
        """Test getting configuration for the default provider."""
        mock_session = AsyncMock()

        # Mock the config query
        mock_result = MagicMock()
        mock_config = MagicMock()
        mock_config.default_provider = "openai"
        mock_config.providers = [
            {
                "name": "openai",
                "base_url": "https://api.openai.com/v1",
                "models": [
                    {"name": "gpt-4o", "max_context_tokens": 128000, "service_mode": "parallel"},
                ]
            }
        ]
        mock_result.scalar_one_or_none.return_value = mock_config
        mock_session.execute.return_value = mock_result

        # Call get_default_provider_config
        provider_config = await model_config_service.get_default_provider_config(mock_session)

        # Should return the default provider config
        assert provider_config is not None
        assert provider_config["name"] == "openai"
