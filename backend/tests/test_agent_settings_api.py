"""Tests for AgentSettingsAPI."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI

from backend.models.agent import AgentType
from backend.api.agent_settings import router, get_session

# Fixed datetime for testing
TEST_DATETIME = datetime(2025, 1, 1, 12, 0, 0)


def create_mock_settings(
    id: str = "test-id",
    agent_type: AgentType | None = None,
    agent_id: str | None = None,
    system_prompt: str = "Test prompt",
    provider_name: str | None = None,
    model_name: str | None = None,
    created_at: datetime | None = TEST_DATETIME,
    updated_at: datetime | None = TEST_DATETIME,
):
    """Create a mock AgentSettings-like object."""
    mock = MagicMock()
    mock.id = id
    mock.agent_type = agent_type
    mock.agent_id = agent_id
    mock.system_prompt = system_prompt
    mock.provider_name = provider_name
    mock.model_name = model_name
    mock.created_at = created_at
    mock.updated_at = updated_at
    return mock


class TestAgentSettingsAPI:
    """Tests for AgentSettingsAPI endpoints."""

    @pytest.fixture
    def mock_app(self):
        """Create a test FastAPI app with mocked dependencies."""
        app = FastAPI()
        app.include_router(router, prefix="/api/agent-settings")
        return app

    @pytest.fixture
    def client(self, mock_app):
        """Create a test client."""
        return TestClient(mock_app)

    def _override_session(self, mock_app, mock_session):
        """Override the session dependency with a mock."""
        async def mock_get_session():
            yield mock_session
        mock_app.dependency_overrides[get_session] = mock_get_session

    def test_get_all_settings(self, client, mock_app):
        """Test getting all agent settings."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            mock_service.get_all_settings = AsyncMock(return_value={
                "type_settings": {},
                "instance_settings": {}
            })

            # Make request
            response = client.get("/api/agent-settings")

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert "type_settings" in data
            assert "instance_settings" in data

    def test_get_type_settings(self, client, mock_app):
        """Test getting type-level settings."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # get_type_settings returns a dict
            mock_service.get_type_settings = AsyncMock(return_value={
                "id": "type-settings-id",
                "agent_type": "resident",
                "system_prompt": "Resident agent prompt",
                "provider_name": "openai",
                "model_name": "gpt-4o",
                "is_default": False,
                "created_at": None,
                "updated_at": None,
            })

            # Make request
            response = client.get("/api/agent-settings/type/resident")

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert data["agent_type"] == "resident"
            assert data["system_prompt"] == "Resident agent prompt"

    def test_get_type_settings_not_found(self, client, mock_app):
        """Test getting type-level settings with default values (not in DB)."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # Return default settings (no DB record, but still valid)
            mock_service.get_type_settings = AsyncMock(return_value={
                "id": None,
                "agent_type": "resident",
                "system_prompt": "",  # Default prompt
                "provider_name": None,
                "model_name": None,
                "is_default": True,
                "created_at": None,
                "updated_at": None,
            })

            # Make request with a valid agent type that has no DB settings
            response = client.get("/api/agent-settings/type/resident")

            # Should return 200 with default settings
            assert response.status_code == 200
            data = response.json()
            assert data["is_default"] is True
            assert data["agent_type"] == "resident"

    def test_update_type_settings(self, client, mock_app):
        """Test updating type-level settings."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # update_type_settings returns an AgentSettings object
            mock_settings = create_mock_settings(
                id="type-settings-id",
                agent_type=AgentType.OWNER,
                system_prompt="Updated owner prompt",
                provider_name="deepseek",
                model_name="deepseek-chat",
            )
            mock_service.update_type_settings = AsyncMock(return_value=mock_settings)

            # Make request
            response = client.put(
                "/api/agent-settings/type/owner",
                json={
                    "system_prompt": "Updated owner prompt",
                    "provider_name": "deepseek",
                    "model_name": "deepseek-chat"
                }
            )

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert data["system_prompt"] == "Updated owner prompt"

    def test_reset_type_settings(self, client, mock_app):
        """Test resetting type-level settings to default."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            mock_service.reset_type_settings = AsyncMock(return_value=True)

            # Make request
            response = client.delete("/api/agent-settings/type/worker")

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    def test_get_agent_settings(self, client, mock_app):
        """Test getting instance-level settings."""
        from backend.models.agent import Agent

        mock_session = AsyncMock()

        # Mock agent query
        mock_agent_result = MagicMock()
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = "agent-123"
        mock_agent.agent_type = AgentType.RESIDENT
        mock_agent_result.scalar_one_or_none.return_value = mock_agent
        mock_session.execute.return_value = mock_agent_result

        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # get_agent_settings returns a dict
            mock_service.get_agent_settings = AsyncMock(return_value={
                "id": "instance-settings-id",
                "agent_id": "agent-123",
                "system_prompt": "Instance-specific prompt",
                "provider_name": None,
                "model_name": None,
                "created_at": TEST_DATETIME,
                "updated_at": TEST_DATETIME,
            })

            # Make request
            response = client.get("/api/agent-settings/agent/agent-123")

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert data["agent_id"] == "agent-123"
            assert data["system_prompt"] == "Instance-specific prompt"

    def test_get_agent_settings_not_found(self, client, mock_app):
        """Test getting instance-level settings that don't exist."""
        from backend.models.agent import Agent

        mock_session = AsyncMock()

        # Mock agent query - agent exists but no settings
        mock_agent_result = MagicMock()
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = "agent-123"
        mock_agent.agent_type = AgentType.RESIDENT
        mock_agent_result.scalar_one_or_none.return_value = mock_agent
        mock_session.execute.return_value = mock_agent_result

        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # Return settings without id (not found)
            mock_service.get_agent_settings = AsyncMock(return_value={
                "id": None,
                "agent_id": "agent-123",
                "system_prompt": "",
                "provider_name": None,
                "model_name": None,
                "created_at": TEST_DATETIME,
                "updated_at": TEST_DATETIME,
            })

            # Make request
            response = client.get("/api/agent-settings/agent/agent-123")

            # Should return 404
            assert response.status_code == 404

    def test_update_agent_settings(self, client, mock_app):
        """Test updating instance-level settings."""
        from backend.models.agent import Agent

        mock_session = AsyncMock()

        # Mock agent query
        mock_agent_result = MagicMock()
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = "agent-456"
        mock_agent.agent_type = AgentType.RESIDENT
        mock_agent_result.scalar_one_or_none.return_value = mock_agent
        mock_session.execute.return_value = mock_agent_result

        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # update_agent_settings returns an AgentSettings object
            mock_settings = create_mock_settings(
                id="instance-settings-id",
                agent_id="agent-456",
                system_prompt="Custom prompt for this agent",
                provider_name="openai",
                model_name="gpt-4o-mini",
            )
            mock_service.update_agent_settings = AsyncMock(return_value=mock_settings)

            # Make request
            response = client.put(
                "/api/agent-settings/agent/agent-456",
                json={
                    "system_prompt": "Custom prompt for this agent",
                    "provider_name": "openai",
                    "model_name": "gpt-4o-mini"
                }
            )

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert data["system_prompt"] == "Custom prompt for this agent"

    def test_delete_agent_settings(self, client, mock_app):
        """Test deleting instance-level settings."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            mock_service.delete_agent_settings = AsyncMock(return_value=True)

            # Make request
            response = client.delete("/api/agent-settings/agent/agent-789")

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert "message" in data

    def test_set_type_model(self, client, mock_app):
        """Test setting model assignment for a type."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # set_type_model returns an AgentSettings object
            mock_settings = create_mock_settings(
                id="type-settings-id",
                agent_type=AgentType.RESIDENT,
                system_prompt="Resident prompt",
                provider_name="deepseek",
                model_name="deepseek-chat",
            )
            mock_service.set_type_model = AsyncMock(return_value=mock_settings)

            # Make request
            response = client.put(
                "/api/agent-settings/type/resident/model",
                json={
                    "provider_name": "deepseek",
                    "model_name": "deepseek-chat"
                }
            )

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert data["provider_name"] == "deepseek"
            assert data["model_name"] == "deepseek-chat"

    def test_set_agent_model(self, client, mock_app):
        """Test setting model assignment for an agent instance."""
        from backend.models.agent import Agent

        mock_session = AsyncMock()

        # Mock agent query
        mock_agent_result = MagicMock()
        mock_agent = MagicMock(spec=Agent)
        mock_agent.id = "agent-999"
        mock_agent.agent_type = AgentType.RESIDENT
        mock_agent_result.scalar_one_or_none.return_value = mock_agent
        mock_session.execute.return_value = mock_agent_result

        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # set_agent_model returns an AgentSettings object
            mock_settings = create_mock_settings(
                id="instance-settings-id",
                agent_id="agent-999",
                system_prompt="Custom prompt",
                provider_name="openai",
                model_name="gpt-4-turbo",
            )
            mock_service.set_agent_model = AsyncMock(return_value=mock_settings)

            # Make request
            response = client.put(
                "/api/agent-settings/agent/agent-999/model",
                json={
                    "provider_name": "openai",
                    "model_name": "gpt-4-turbo"
                }
            )

            # Should return 200
            assert response.status_code == 200
            data = response.json()
            assert data["provider_name"] == "openai"
            assert data["model_name"] == "gpt-4-turbo"


class TestAgentSettingsAPIValidation:
    """Tests for API validation."""

    @pytest.fixture
    def mock_app(self):
        """Create a test FastAPI app with mocked dependencies."""
        app = FastAPI()
        app.include_router(router, prefix="/api/agent-settings")
        return app

    @pytest.fixture
    def client(self, mock_app):
        """Create a test client."""
        return TestClient(mock_app)

    def _override_session(self, mock_app, mock_session):
        """Override the session dependency with a mock."""
        async def mock_get_session():
            yield mock_session
        mock_app.dependency_overrides[get_session] = mock_get_session

    def test_update_type_settings_empty_prompt(self, client, mock_app):
        """Test that empty system prompt is handled."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            # update_type_settings returns an AgentSettings object
            mock_settings = create_mock_settings(
                id="type-settings-id",
                agent_type=AgentType.SUB,
                system_prompt="",
            )
            mock_service.update_type_settings = AsyncMock(return_value=mock_settings)

            # Make request with empty prompt (should fail validation)
            response = client.put(
                "/api/agent-settings/type/sub",
                json={"system_prompt": ""}
            )

            # Should return 422 (validation error) because min_length=1
            assert response.status_code == 422

    def test_invalid_agent_type(self, client, mock_app):
        """Test that invalid agent type is handled."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        # Make request with invalid agent type
        response = client.get("/api/agent-settings/type/invalid_type")

        # Should return 422 (validation error) because AgentType enum doesn't accept invalid values
        assert response.status_code == 422

    def test_max_context_tokens_minus_one_is_valid(self, client, mock_app):
        """Test that -1 is a valid value for max_context_tokens (unlimited)."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        with patch('backend.api.agent_settings.agent_settings_service') as mock_service:
            mock_settings = create_mock_settings(
                id="type-settings-id",
                agent_type=AgentType.RESIDENT,
                system_prompt="Test prompt",
            )
            mock_settings.max_context_tokens = -1
            mock_service.update_type_settings = AsyncMock(return_value=mock_settings)

            # Make request with max_context_tokens = -1
            response = client.put(
                "/api/agent-settings/type/resident",
                json={
                    "system_prompt": "Test prompt",
                    "max_context_tokens": -1
                }
            )

            # Should return 200 (not 422)
            assert response.status_code == 200
            data = response.json()
            assert data["max_context_tokens"] == -1

    def test_max_context_tokens_negative_two_is_invalid(self, client, mock_app):
        """Test that -2 is an invalid value for max_context_tokens."""
        mock_session = AsyncMock()
        self._override_session(mock_app, mock_session)

        # Make request with max_context_tokens = -2
        response = client.put(
            "/api/agent-settings/type/resident",
            json={
                "system_prompt": "Test prompt",
                "max_context_tokens": -2
            }
        )

        # Should return 422 (validation error)
        assert response.status_code == 422
