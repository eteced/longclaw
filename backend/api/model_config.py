"""
Model Configuration API for LongClaw.
"""
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.services.model_config_service import model_config_service

router = APIRouter()


# ==================== Schemas ====================


class ModelInfo(BaseModel):
    """Schema for model information."""

    name: str
    max_context_tokens: int = 8192
    service_mode: Literal["parallel", "serial"] = "parallel"


class ProviderConfig(BaseModel):
    """Schema for a provider configuration."""

    name: str
    display_name: str | None = None
    base_url: str
    api_key: str | None = None
    service_mode: Literal["parallel", "serial"] = "parallel"
    models: list[ModelInfo] = Field(default_factory=list)


class ModelConfigResponse(BaseModel):
    """Schema for model configuration response."""

    id: str
    default_provider: str
    providers: list[dict[str, Any]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelConfigUpdate(BaseModel):
    """Schema for updating model configuration."""

    default_provider: str | None = None
    providers: list[dict[str, Any]] | None = None


class ContextLimitUpdate(BaseModel):
    """Schema for updating context limit."""

    max_context_tokens: int = Field(..., ge=256, le=1000000)


class ServiceModeUpdate(BaseModel):
    """Schema for updating service mode."""

    service_mode: Literal["parallel", "serial"]


class TestProviderRequest(BaseModel):
    """Schema for testing a provider connection."""

    base_url: str
    api_key: str | None = None


class TestProviderResponse(BaseModel):
    """Schema for test provider response."""

    success: bool
    models: list[str] | None = None
    latency_ms: float | None = None
    error: str | None = None


class ModelInfoResponse(BaseModel):
    """Schema for model info response."""

    provider: str
    model: str
    max_context_tokens: int
    service_mode: str


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency.

    Yields:
        AsyncSession instance.
    """
    async with db_manager.session() as session:
        yield session


# ==================== Endpoints ====================


@router.get("", response_model=ModelConfigResponse)
async def get_model_config(
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    """Get the model configuration.

    Args:
        session: Database session.

    Returns:
        Model configuration.
    """
    config = await model_config_service.get_config(session)
    return ModelConfigResponse.model_validate(config)


@router.put("", response_model=ModelConfigResponse)
async def update_model_config(
    data: ModelConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    """Update the model configuration.

    Args:
        data: Update data.
        session: Database session.

    Returns:
        Updated model configuration.
    """
    config = await model_config_service.update_config(
        session,
        default_provider=data.default_provider,
        providers=data.providers,
    )

    # Refresh LLM service config from database
    from backend.services.llm_service import load_db_config
    await load_db_config()

    return ModelConfigResponse.model_validate(config)


@router.post("/refresh", response_model=ModelConfigResponse)
async def refresh_model_config(
    session: AsyncSession = Depends(get_session),
) -> ModelConfigResponse:
    """Refresh model configuration from .env file.

    This updates the database config with the latest values from environment variables.

    Args:
        session: Database session.

    Returns:
        Refreshed model configuration.
    """
    config = await model_config_service.refresh_from_env(session)

    # Refresh LLM service config from database
    from backend.services.llm_service import load_db_config
    await load_db_config()

    return ModelConfigResponse.model_validate(config)


@router.get("/models/{provider}/{model}", response_model=ModelInfoResponse)
async def get_model_info(
    provider: str,
    model: str,
    session: AsyncSession = Depends(get_session),
) -> ModelInfoResponse:
    """Get information about a specific model.

    Args:
        provider: Provider name.
        model: Model name.
        session: Database session.

    Returns:
        Model information.
    """
    model_info = await model_config_service.get_model_info(session, provider, model)
    if not model_info:
        raise HTTPException(status_code=404, detail=f"Model not found: {provider}/{model}")

    return ModelInfoResponse(
        provider=provider,
        model=model,
        max_context_tokens=model_info.get("max_context_tokens", 8192),
        service_mode=model_info.get("service_mode", "parallel"),
    )


@router.put("/models/{provider}/{model}/context-limit", response_model=ModelInfoResponse)
async def set_model_context_limit(
    provider: str,
    model: str,
    data: ContextLimitUpdate,
    session: AsyncSession = Depends(get_session),
) -> ModelInfoResponse:
    """Set the context limit for a specific model.

    Args:
        provider: Provider name.
        model: Model name.
        data: Context limit data.
        session: Database session.

    Returns:
        Updated model information.
    """
    success = await model_config_service.set_model_context_limit(
        session, provider, model, data.max_context_tokens
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Model not found: {provider}/{model}")

    return ModelInfoResponse(
        provider=provider,
        model=model,
        max_context_tokens=data.max_context_tokens,
        service_mode=await model_config_service.get_model_service_mode(session, provider, model),
    )


@router.put("/providers/{provider}/service-mode")
async def set_provider_service_mode(
    provider: str,
    data: ServiceModeUpdate,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Set the service mode for a specific provider.

    Args:
        provider: Provider name.
        data: Service mode data.
        session: Database session.

    Returns:
        Updated provider information.
    """
    success = await model_config_service.set_provider_service_mode(
        session, provider, data.service_mode
    )
    if not success:
        raise HTTPException(status_code=404, detail=f"Provider not found: {provider}")

    return {"provider": provider, "service_mode": data.service_mode}


@router.get("/context-limits")
async def get_all_context_limits(
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Get context limits for all models.

    Args:
        session: Database session.

    Returns:
        Dictionary mapping "provider/model" to context limit.
    """
    return await model_config_service.get_all_model_context_limits(session)


class HealthCheckResponse(BaseModel):
    """Schema for health check response."""

    provider: str
    model: str
    base_url: str
    is_healthy: bool
    latency_ms: float | None = None
    models_available: list[str] | None = None
    error: str | None = None


@router.get("/health", response_model=HealthCheckResponse)
async def check_llm_health(
    provider: str | None = None,
) -> HealthCheckResponse:
    """Check LLM provider health.

    Calls the provider's /models endpoint to verify API availability.

    Args:
        provider: Optional provider name to check. Defaults to default provider.

    Returns:
        Health check result with latency and available models.
    """
    from backend.services.llm_service import llm_service

    result = await llm_service.health_check(provider)
    return HealthCheckResponse(
        provider=result.provider,
        model=result.model,
        base_url=result.base_url,
        is_healthy=result.is_healthy,
        latency_ms=result.latency_ms,
        models_available=result.models_available,
        error=result.error,
    )


class SpeedTestResponse(BaseModel):
    """Schema for LLM speed test response."""

    provider: str
    model: str
    is_success: bool
    # Timing metrics
    connection_time_ms: float | None = None
    prefill_time_ms: float | None = None  # Time to first token
    generation_time_ms: float | None = None  # Time for generation
    total_time_ms: float | None = None
    tokens_generated: int | None = None
    # Speed metrics
    tokens_per_second: float | None = None
    ms_per_token: float | None = None
    # Recommended timeout config
    recommended_timeouts: dict[str, int] | None = None
    error: str | None = None


@router.get("/speed-test", response_model=SpeedTestResponse)
async def test_llm_speed(
    provider: str | None = None,
    test_prompt: str | None = None,
) -> SpeedTestResponse:
    """Test LLM speed and recommend timeout configurations.

    Sends a test request to the LLM and measures:
    - Connection time
    - Time to first token (prefill)
    - Generation speed (tokens per second)

    Then recommends appropriate timeout values based on the results.

    Args:
        provider: Optional provider name to test. Defaults to default provider.
        test_prompt: Optional test prompt. Defaults to a simple test prompt.

    Returns:
        Speed test results with recommended timeout configurations.
    """
    import time
    from backend.services.llm_service import llm_service, ChatMessage

    # Default test prompt
    prompt = test_prompt or "Please respond with exactly 50 words about the weather today."

    try:
        # Get provider config
        provider_config = llm_service.get_provider_config(provider)
        if not provider_config:
            return SpeedTestResponse(
                provider=provider or "default",
                model="unknown",
                is_success=False,
                error=f"Provider not found: {provider}",
            )

        # Measure connection and prefill time (time to first token)
        start_time = time.time()
        first_token_time = None
        tokens_generated = 0
        content = ""

        messages = [ChatMessage(role="user", content=prompt)]

        # Use streaming to measure prefill vs generation time
        async for chunk in llm_service.complete_stream(messages, provider=provider):
            if first_token_time is None:
                first_token_time = time.time()
                prefill_time_ms = (first_token_time - start_time) * 1000
            if chunk:
                content += chunk
                tokens_generated += 1

        end_time = time.time()
        total_time_ms = (end_time - start_time) * 1000

        # Calculate metrics
        generation_time_ms = total_time_ms - prefill_time_ms if first_token_time else total_time_ms

        # Estimate tokens (rough estimate: ~4 chars per token for Chinese, ~5 for English)
        if tokens_generated == 0:
            tokens_generated = len(content) // 4  # Rough estimate

        tokens_per_second = (tokens_generated / generation_time_ms * 1000) if generation_time_ms > 0 else 0
        ms_per_token = (generation_time_ms / tokens_generated) if tokens_generated > 0 else 0

        # Recommend timeouts based on performance
        # Base assumptions:
        # - A typical task might need 1000-4000 tokens
        # - Prefill overhead for context
        # - Safety margin of 2x

        recommended_timeouts = {}

        if tokens_per_second > 0:
            # Estimate timeouts based on token speed
            # For a 2000 token response: 2000 / tokens_per_second
            base_response_time = 2000 / tokens_per_second if tokens_per_second > 0 else 60

            # Worker timeout: time for typical subtask
            recommended_timeouts["worker_subtask_timeout"] = max(120, int(base_response_time * 2 + 60))

            # Owner timeout: multiple workers + synthesis
            recommended_timeouts["owner_task_timeout"] = max(300, int(recommended_timeouts["worker_subtask_timeout"] * 3))

            # Resident chat timeout: quick response
            recommended_timeouts["resident_chat_timeout"] = max(60, int(base_response_time + 30))

            # LLM request timeout: single request
            recommended_timeouts["llm_request_timeout"] = max(60, int(base_response_time * 1.5 + 30))

            # Connection timeout
            recommended_timeouts["llm_connect_timeout"] = max(10, int(prefill_time_ms / 1000 + 5))
        else:
            # Fallback defaults if we couldn't measure speed
            recommended_timeouts = {
                "worker_subtask_timeout": 300,
                "owner_task_timeout": 600,
                "resident_chat_timeout": 120,
                "llm_request_timeout": 180,
                "llm_connect_timeout": 30,
            }

        return SpeedTestResponse(
            provider=provider_config.get("name", provider or "default"),
            model=provider_config.get("model", "unknown"),
            is_success=True,
            connection_time_ms=prefill_time_ms * 0.1 if prefill_time_ms else None,  # Estimate
            prefill_time_ms=prefill_time_ms,
            generation_time_ms=generation_time_ms,
            total_time_ms=total_time_ms,
            tokens_generated=tokens_generated,
            tokens_per_second=round(tokens_per_second, 2),
            ms_per_token=round(ms_per_token, 2),
            recommended_timeouts=recommended_timeouts,
        )

    except Exception as e:
        return SpeedTestResponse(
            provider=provider or "default",
            model="unknown",
            is_success=False,
            error=str(e),
        )


@router.post("/apply-timeouts")
async def apply_recommended_timeouts(
    timeouts: dict[str, int],
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Apply recommended timeout values to system configuration.

    Args:
        timeouts: Dictionary of timeout key -> value in seconds.
        session: Database session.

    Returns:
        Updated configuration values.
    """
    from backend.services.config_service import config_service

    updated = {}
    for key, value in timeouts.items():
        if value > 0:
            await config_service.set(session, key, str(value))
            updated[key] = value

    return {"updated": updated, "message": f"Updated {len(updated)} timeout configurations"}


@router.post("/test-provider", response_model=TestProviderResponse)
async def test_provider_connection(
    data: TestProviderRequest,
) -> TestProviderResponse:
    """Test provider connection and fetch available models.

    This endpoint tests the connection to a provider's API and returns
    the list of available models. It's useful for:
    - Validating API credentials
    - Auto-discovering available models
    - Checking API connectivity

    Args:
        data: Provider connection details (base_url, api_key).

    Returns:
        Test result with available models if successful.
    """
    result = await model_config_service.test_provider_connection(
        base_url=data.base_url,
        api_key=data.api_key,
    )

    return TestProviderResponse(
        success=result.get("success", False),
        models=result.get("models"),
        latency_ms=result.get("latency_ms"),
        error=result.get("error"),
    )
