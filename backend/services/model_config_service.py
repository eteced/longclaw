"""
Model Configuration Service for LongClaw.
Manages LLM provider configurations.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.model_config import ModelConfig

logger = logging.getLogger(__name__)

# Default context limits for common models (in tokens)
DEFAULT_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16385,
    "deepseek-chat": 64000,
    "deepseek-coder": 16000,
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
}


def _get_default_providers() -> list[dict[str, Any]]:
    """Get default providers configuration from settings.

    Uses pydantic-settings which properly loads .env files.
    This function is called each time to ensure fresh settings are used.

    Returns:
        List of provider configurations.
    """
    settings = get_settings()
    logger.info(f"Loading default providers from settings - OpenAI base_url: {settings.openai_base_url}")

    # Helper function to convert model names to model info objects
    def make_model_info(model_name: str) -> dict[str, Any]:
        return {
            "name": model_name,
            "max_context_tokens": DEFAULT_MODEL_CONTEXT_LIMITS.get(model_name, 8192),
        }

    return [
        {
            "name": "openai",
            "display_name": "OpenAI",
            "base_url": settings.openai_base_url,
            "api_key": settings.openai_api_key,
            "service_mode": "parallel",  # Provider-level mode
            "models": [
                make_model_info(settings.openai_model),
                make_model_info("gpt-4o-mini"),
                make_model_info("gpt-4-turbo"),
                make_model_info("gpt-3.5-turbo"),
            ],
        },
        {
            "name": "deepseek",
            "display_name": "DeepSeek",
            "base_url": settings.deepseek_base_url,
            "api_key": settings.deepseek_api_key,
            "service_mode": "parallel",  # Provider-level mode
            "models": [
                make_model_info(settings.deepseek_model),
                make_model_info("deepseek-coder"),
            ],
        },
    ]


class ModelConfigService:
    """Service for managing model configurations."""

    async def get_config(self, session: AsyncSession) -> ModelConfig:
        """Get the model configuration, creating default if not exists.

        Args:
            session: Database session.

        Returns:
            ModelConfig instance.
        """
        result = await session.execute(
            select(ModelConfig).where(ModelConfig.config_type == "default")
        )
        config = result.scalar_one_or_none()

        if not config:
            # Create default configuration - get fresh providers from settings
            providers = _get_default_providers()
            logger.info(f"Creating default model config with providers: {providers}")

            config = ModelConfig(
                id=str(uuid4()),
                config_type="default",
                default_provider="openai",
                providers=providers,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            session.add(config)
            await session.flush()
            logger.info("Created default model configuration")

        return config

    async def refresh_from_env(self, session: AsyncSession) -> ModelConfig:
        """Refresh the model configuration from environment variables.

        This updates the database config with the latest values from .env.

        Args:
            session: Database session.

        Returns:
            Updated ModelConfig instance.
        """
        config = await self.get_config(session)

        # Get fresh providers from settings (which reads from .env)
        providers = _get_default_providers()
        logger.info(f"Refreshing model config from .env with providers: {providers}")

        config.providers = providers
        config.updated_at = datetime.utcnow()
        await session.flush()

        logger.info("Refreshed model configuration from .env")
        return config

    async def update_config(
        self,
        session: AsyncSession,
        default_provider: str | None = None,
        providers: list[dict[str, Any]] | None = None,
    ) -> ModelConfig:
        """Update the model configuration.

        Args:
            session: Database session.
            default_provider: Default provider name.
            providers: List of provider configurations.

        Returns:
            Updated ModelConfig instance.
        """
        config = await self.get_config(session)

        if default_provider is not None:
            config.default_provider = default_provider
        if providers is not None:
            config.providers = providers

        config.updated_at = datetime.utcnow()
        await session.flush()

        logger.info(f"Updated model configuration")
        return config

    async def get_provider_config(
        self, session: AsyncSession, provider_name: str
    ) -> dict[str, Any] | None:
        """Get configuration for a specific provider.

        Args:
            session: Database session.
            provider_name: Provider name.

        Returns:
            Provider configuration or None if not found.
        """
        config = await self.get_config(session)
        for provider in config.providers:
            if provider.get("name") == provider_name:
                return provider
        return None

    async def get_default_provider_config(
        self, session: AsyncSession
    ) -> dict[str, Any] | None:
        """Get configuration for the default provider.

        Args:
            session: Database session.

        Returns:
            Default provider configuration or None if not found.
        """
        config = await self.get_config(session)
        return await self.get_provider_config(session, config.default_provider)

    async def get_model_info(
        self, session: AsyncSession, provider_name: str, model_name: str
    ) -> dict[str, Any] | None:
        """Get information about a specific model.

        Args:
            session: Database session.
            provider_name: Provider name.
            model_name: Model name.

        Returns:
            Model info dictionary or None if not found.
        """
        provider = await self.get_provider_config(session, provider_name)
        if not provider:
            return None

        models = provider.get("models", [])
        for model in models:
            if isinstance(model, dict) and model.get("name") == model_name:
                return model
            elif isinstance(model, str) and model == model_name:
                # Legacy string format - return default values
                return {
                    "name": model,
                    "max_context_tokens": DEFAULT_MODEL_CONTEXT_LIMITS.get(model, 8192),
                    "service_mode": "parallel",
                }

        return None

    async def get_model_context_limit(
        self, session: AsyncSession, provider_name: str, model_name: str
    ) -> int:
        """Get the context limit for a specific model.

        Args:
            session: Database session.
            provider_name: Provider name.
            model_name: Model name.

        Returns:
            Context limit in tokens (default 8192 if not found).
        """
        model_info = await self.get_model_info(session, provider_name, model_name)
        if model_info:
            return model_info.get("max_context_tokens", 8192)
        return DEFAULT_MODEL_CONTEXT_LIMITS.get(model_name, 8192)

    async def set_model_context_limit(
        self, session: AsyncSession, provider_name: str, model_name: str, limit: int
    ) -> bool:
        """Set the context limit for a specific model.

        Args:
            session: Database session.
            provider_name: Provider name.
            model_name: Model name.
            limit: Context limit in tokens.

        Returns:
            True if updated, False if model not found.
        """
        config = await self.get_config(session)
        providers = list(config.providers)  # Create a copy

        for i, provider in enumerate(providers):
            if provider.get("name") == provider_name:
                models = list(provider.get("models", []))
                for j, model in enumerate(models):
                    model_name_to_check = model.get("name") if isinstance(model, dict) else model
                    if model_name_to_check == model_name:
                        # Convert to dict if it's a string (legacy format)
                        if isinstance(model, str):
                            models[j] = {
                                "name": model,
                                "max_context_tokens": limit,
                                "service_mode": "parallel",
                            }
                        else:
                            models[j] = {**model, "max_context_tokens": limit}

                        providers[i] = {**provider, "models": models}
                        config.providers = providers
                        config.updated_at = datetime.utcnow()
                        await session.flush()
                        logger.info(f"Set context limit for {provider_name}/{model_name}: {limit}")
                        return True

        return False

    async def get_provider_service_mode(
        self, session: AsyncSession, provider_name: str
    ) -> str:
        """Get the service mode for a specific provider.

        Args:
            session: Database session.
            provider_name: Provider name.

        Returns:
            Service mode ("parallel" or "serial", default "parallel").
        """
        provider = await self.get_provider_config(session, provider_name)
        if provider:
            return provider.get("service_mode", "parallel")
        return "parallel"

    async def set_provider_service_mode(
        self, session: AsyncSession, provider_name: str, mode: str
    ) -> bool:
        """Set the service mode for a specific provider.

        Args:
            session: Database session.
            provider_name: Provider name.
            mode: Service mode ("parallel" or "serial").

        Returns:
            True if updated, False if provider not found.
        """
        if mode not in ("parallel", "serial"):
            raise ValueError(f"Invalid service mode: {mode}. Must be 'parallel' or 'serial'.")

        config = await self.get_config(session)
        providers = list(config.providers)  # Create a copy

        for i, provider in enumerate(providers):
            if provider.get("name") == provider_name:
                providers[i] = {**provider, "service_mode": mode}
                config.providers = providers
                config.updated_at = datetime.utcnow()
                await session.flush()
                logger.info(f"Set service mode for provider {provider_name}: {mode}")
                return True

        return False

    async def get_all_model_context_limits(
        self, session: AsyncSession
    ) -> dict[str, int]:
        """Get context limits for all models across all providers.

        Args:
            session: Database session.

        Returns:
            Dictionary mapping "provider/model" to context limit.
        """
        config = await self.get_config(session)
        limits: dict[str, int] = {}

        for provider in config.providers:
            provider_name = provider.get("name", "")
            for model in provider.get("models", []):
                if isinstance(model, dict):
                    model_name = model.get("name", "")
                    limit = model.get("max_context_tokens", 8192)
                else:
                    model_name = model
                    limit = DEFAULT_MODEL_CONTEXT_LIMITS.get(model, 8192)

                key = f"{provider_name}/{model_name}"
                limits[key] = limit

        return limits

    async def test_provider_connection(
        self,
        base_url: str,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """Test provider connection and fetch available models.

        Args:
            base_url: Provider base URL.
            api_key: Optional API key.

        Returns:
            Dictionary with:
            - success: bool
            - models: list of model names (if successful)
            - error: str (if failed)
            - latency_ms: float (if successful)
        """
        import httpx
        import time

        # Ensure base_url doesn't end with slash for consistent path joining
        base_url = base_url.rstrip("/")
        models_url = f"{base_url}/models"

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        start_time = time.time()
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(models_url, headers=headers)
                latency_ms = (time.time() - start_time) * 1000

                if response.status_code == 200:
                    data = response.json()
                    # OpenAI-compatible API returns {"data": [{"id": "model-name", ...}, ...]}
                    models = []
                    if isinstance(data, dict) and "data" in data:
                        for model in data.get("data", []):
                            if isinstance(model, dict) and "id" in model:
                                models.append(model["id"])
                    elif isinstance(data, list):
                        # Some APIs return direct list
                        for model in data:
                            if isinstance(model, dict) and "id" in model:
                                models.append(model["id"])
                            elif isinstance(model, str):
                                models.append(model)

                    return {
                        "success": True,
                        "models": models,
                        "latency_ms": latency_ms,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"HTTP {response.status_code}: {response.text[:200]}",
                        "latency_ms": latency_ms,
                    }
        except httpx.TimeoutException:
            return {
                "success": False,
                "error": "Connection timeout (30s)",
                "latency_ms": 30000,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "latency_ms": (time.time() - start_time) * 1000,
            }


# Global model config service instance
model_config_service = ModelConfigService()
