"""
LLM Service for LongClaw.
Provides unified interface for multiple LLM providers.
"""
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)

# Global cache for database config
_db_llm_config: dict[str, Any] | None = None


async def load_db_config() -> dict[str, Any] | None:
    """Load LLM configuration from database.

    Returns:
        Database config dict with 'default_provider' and 'providers' keys, or None if not available.
    """
    global _db_llm_config

    try:
        from backend.database import db_manager
        from backend.services.model_config_service import model_config_service

        async with db_manager.session() as session:
            config = await model_config_service.get_config(session)
            if config:
                _db_llm_config = {
                    "default_provider": config.default_provider,
                    "providers": {p["name"]: p for p in config.providers},
                }
                logger.info(f"Loaded LLM config from database: default_provider={config.default_provider}")
                return _db_llm_config
    except Exception as e:
        logger.warning(f"Failed to load LLM config from database: {e}")

    return None


def get_db_config() -> dict[str, Any] | None:
    """Get cached database config.

    Returns:
        Cached database config or None.
    """
    return _db_llm_config


@dataclass
class LLMConfig:
    """Configuration for an LLM provider."""

    api_key: str
    base_url: str
    model: str
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class HealthCheckResult:
    """Result of an LLM health check."""

    provider: str
    model: str
    base_url: str
    is_healthy: bool
    latency_ms: float | None = None
    models_available: list[str] | None = None
    error: str | None = None


@dataclass
class StreamChunk:
    """A chunk of streaming response."""

    content: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_arguments: str | None = None
    finish_reason: str | None = None
    is_tool_call: bool = False


@dataclass
class ToolCall:
    """A tool call request from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "ToolCall":
        """Create from API response data.

        Args:
            data: Tool call data from API.

        Returns:
            ToolCall instance.
        """
        function = data.get("function", {})
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        return cls(
            id=data.get("id", ""),
            name=function.get("name", ""),
            arguments=arguments,
        )


@dataclass
class ChatMessage:
    """A single chat message."""

    role: str  # system, user, assistant, tool
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # For tool response messages
    name: str | None = None  # Tool name for tool response messages

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API request.

        Returns:
            Dictionary representation.
        """
        result: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            result["content"] = self.content

        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]

        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id

        if self.name:
            result["name"] = self.name

        return result


@dataclass
class LLMResponse:
    """Response from an LLM completion."""

    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str = ""
    tool_calls: list[ToolCall] | None = None

    @classmethod
    def from_api_response(cls, data: dict[str, Any]) -> "LLMResponse":
        """Create from API response data.

        Args:
            data: API response dictionary.

        Returns:
            LLMResponse instance.
        """
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        # Parse tool calls if present
        tool_calls = None
        if "tool_calls" in message:
            tool_calls = [
                ToolCall.from_api_response(tc)
                for tc in message["tool_calls"]
            ]
            logger.info(f"Parsed {len(tool_calls)} tool calls from API response")

        return cls(
            content=message.get("content") or "",
            model=data.get("model", ""),
            usage=data.get("usage", {}),
            finish_reason=choice.get("finish_reason", ""),
            tool_calls=tool_calls,
        )

    @property
    def has_tool_calls(self) -> bool:
        """Check if response has tool calls.

        Returns:
            True if has tool calls.
        """
        return bool(self.tool_calls)


class LLMService:
    """Service for interacting with LLM providers."""

    def __init__(self) -> None:
        """Initialize the LLM service."""
        self._configs: dict[str, LLMConfig] = {}
        self._http_client: httpx.AsyncClient | None = None
        self._load_configs()
        # Semaphore control for provider+model concurrency
        self._provider_semaphores: dict[str, asyncio.Semaphore] = {}
        self._semaphore_lock = asyncio.Lock()

    def _load_configs(self) -> None:
        """Load LLM configurations from settings."""
        settings = get_settings()

        if settings.openai_api_key:
            self._configs["openai"] = LLMConfig(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.openai_model,
            )

        if settings.deepseek_api_key:
            self._configs["deepseek"] = LLMConfig(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
                model=settings.deepseek_model,
            )

        logger.info(f"Loaded {len(self._configs)} LLM provider configurations")

    async def init(self) -> None:
        """Initialize the HTTP client."""
        # Get configurable timeout values
        from backend.services.config_service import config_service

        request_timeout = await config_service.get_float("llm_request_timeout", 300.0)
        connect_timeout = await config_service.get_float("llm_connect_timeout", 30.0)

        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        logger.info(f"LLM service HTTP client initialized (timeout={request_timeout}s, connect={connect_timeout}s)")

        # Load config from database
        await load_db_config()

    async def _get_semaphore(self, provider: str, model: str) -> asyncio.Semaphore:
        """Get or create a semaphore for provider+model concurrency control.

        Args:
            provider: Provider name.
            model: Model name.

        Returns:
            Semaphore for this provider+model combination.
        """
        key = f"{provider}:{model}"
        async with self._semaphore_lock:
            if key not in self._provider_semaphores:
                # Get max_parallel_requests from ProviderScheduler
                try:
                    from backend.services.provider_scheduler_service import provider_scheduler_service
                    max_parallel = provider_scheduler_service.get_model_max_parallel(provider, model)
                except Exception as e:
                    logger.warning(f"Failed to get max_parallel from provider_scheduler: {e}")
                    max_parallel = 10  # Default fallback
                self._provider_semaphores[key] = asyncio.Semaphore(max_parallel)
                logger.debug(f"Created semaphore for {key} with max_parallel={max_parallel}")
            return self._provider_semaphores[key]

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            logger.info("LLM service HTTP client closed")

    def get_config(self, provider: str | None = None) -> LLMConfig:
        """Get LLM configuration for a provider.

        Checks database config first, then falls back to env vars.

        Args:
            provider: Provider name, defaults to default provider.

        Returns:
            LLM configuration.

        Raises:
            ValueError: If provider is not configured.
        """
        # Try to get config from database first
        db_config = get_db_config()
        if db_config:
            provider_name = provider or db_config.get("default_provider", "openai")
            providers = db_config.get("providers", {})
            if provider_name in providers:
                p = providers[provider_name]
                api_key = p.get("api_key", "")
                base_url = p.get("base_url", "")
                models = p.get("models", [])
                # models is a list of dicts like {"name": "gpt-4o", "max_context_tokens": ...}
                if models:
                    first_model = models[0]
                    model = first_model.get("name") if isinstance(first_model, dict) else str(first_model)
                else:
                    model = ""

                if api_key:  # Only use db config if api_key is set
                    logger.debug(f"Using database config for provider: {provider_name}")
                    return LLMConfig(
                        api_key=api_key,
                        base_url=base_url,
                        model=model,
                    )

        # Fall back to env vars
        settings = get_settings()
        provider = provider or settings.llm_default_provider

        if provider not in self._configs:
            raise ValueError(f"LLM provider '{provider}' is not configured")

        return self._configs[provider]

    async def health_check(self, provider: str | None = None) -> HealthCheckResult:
        """Check health of an LLM provider.

        Calls the /models endpoint to verify API availability.

        Args:
            provider: Provider to check, defaults to default provider.

        Returns:
            Health check result with latency and available models.
        """
        import time

        if not self._http_client:
            return HealthCheckResult(
                provider=provider or "unknown",
                model="",
                base_url="",
                is_healthy=False,
                error="LLM service not initialized",
            )

        try:
            config = self.get_config(provider)
            provider_name = provider or self._get_default_provider_name()
            url = f"{config.base_url.rstrip('/')}/models"
            headers = self._build_headers(config)

            start_time = time.monotonic()
            response = await self._http_client.get(url, headers=headers)
            latency_ms = (time.monotonic() - start_time) * 1000

            if response.status_code == 200:
                data = response.json()
                models_available = []
                if "data" in data:
                    models_available = [m.get("id", "") for m in data["data"]]

                return HealthCheckResult(
                    provider=provider_name,
                    model=config.model,
                    base_url=config.base_url,
                    is_healthy=True,
                    latency_ms=round(latency_ms, 2),
                    models_available=models_available[:50],  # Limit to 50 models
                )
            else:
                return HealthCheckResult(
                    provider=provider_name,
                    model=config.model,
                    base_url=config.base_url,
                    is_healthy=False,
                    latency_ms=round(latency_ms, 2),
                    error=f"HTTP {response.status_code}: {response.text[:200]}",
                )

        except ValueError as e:
            # Provider not configured
            return HealthCheckResult(
                provider=provider or "unknown",
                model="",
                base_url="",
                is_healthy=False,
                error=str(e),
            )
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return HealthCheckResult(
                provider=provider or "unknown",
                model="",
                base_url="",
                is_healthy=False,
                error=str(e),
            )

    def _get_default_provider_name(self) -> str:
        """Get the default provider name.

        Returns:
            Default provider name.
        """
        db_config = get_db_config()
        if db_config:
            return db_config.get("default_provider", "openai")
        return get_settings().llm_default_provider

    def _build_headers(self, config: LLMConfig) -> dict[str, str]:
        """Build request headers.

        Args:
            config: LLM configuration.

        Returns:
            Headers dictionary.
        """
        return {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

    def _build_request_body(
        self,
        config: LLMConfig,
        messages: list[ChatMessage],
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build request body.

        Args:
            config: LLM configuration.
            messages: List of chat messages.
            stream: Whether to stream the response.
            tools: Optional list of tool definitions.
            **kwargs: Additional parameters.

        Returns:
            Request body dictionary.
        """
        body: dict[str, Any] = {
            "model": config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": kwargs.get("temperature", config.temperature),
            "max_tokens": kwargs.get("max_tokens", config.max_tokens),
            "stream": stream,
        }

        if tools:
            body["tools"] = tools
            logger.info(f"Added {len(tools)} tools to request: {[t['function']['name'] for t in tools]}")
        else:
            logger.debug("No tools provided in request")

        return body

    async def complete(
        self,
        messages: list[ChatMessage],
        provider: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Send a completion request.

        Args:
            messages: List of chat messages.
            provider: Provider to use, defaults to default provider.
            tools: Optional list of tool definitions for function calling.
            **kwargs: Additional parameters.

        Returns:
            LLM response.

        Raises:
            RuntimeError: If service is not initialized.
            httpx.HTTPError: If request fails.
        """
        if not self._http_client:
            raise RuntimeError("LLM service not initialized")

        config = self.get_config(provider)
        provider_name = provider or self._get_default_provider_name()

        # Get semaphore for this provider+model and wait for available slot
        semaphore = await self._get_semaphore(provider_name, config.model)

        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(config)
        body = self._build_request_body(config, messages, stream=False, tools=tools, **kwargs)

        logger.debug(f"Sending completion request to {url}")
        try:
            # Wait for semaphore before making request
            async with semaphore:
                response = await self._http_client.post(url, headers=headers, json=body)
                response.raise_for_status()

                data = response.json()
                # Check for API-level errors
                base_resp = data.get("base_resp", {})
                status_code = base_resp.get("status_code", 0)
                if status_code != 0:
                    error_msg = base_resp.get("status_msg", str(data))
                    raise RuntimeError(f"LLM API error: {error_msg}")

                # Log the finish_reason and tool_calls presence for debugging
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError(f"LLM API returned empty choices: {data}")
                choice = choices[0]
                finish_reason = choice.get("finish_reason", "")
                message = choice.get("message", {})
                has_tool_calls = "tool_calls" in message
                logger.info(f"LLM response: finish_reason={finish_reason}, has_tool_calls={has_tool_calls}")
                if has_tool_calls:
                    tool_call_names = [tc.get("function", {}).get("name", "") for tc in message.get("tool_calls", [])]
                    logger.info(f"Tool calls in response: {tool_call_names}")

                return LLMResponse.from_api_response(data)
        except httpx.ConnectError as e:
            # Provide user-friendly connection error message
            error_msg = (
                f"LLM 连接失败\n"
                f"连接地址: {url}\n"
                f"错误原因: {str(e)}\n\n"
                f"请检查 Models 配置页面，确保 API 地址和密钥正确。"
            )
            logger.error(f"LLM connection failed: {e}")
            raise RuntimeError(error_msg) from e
        except httpx.TimeoutException as e:
            error_msg = (
                f"LLM 请求超时\n"
                f"连接地址: {url}\n"
                f"错误原因: {str(e)}\n\n"
                f"请检查网络连接或尝试更换模型。"
            )
            logger.error(f"LLM request timeout: {e}")
            raise RuntimeError(error_msg) from e
        except httpx.HTTPStatusError as e:
            error_msg = (
                f"LLM API 错误\n"
                f"连接地址: {url}\n"
                f"状态码: {e.response.status_code}\n"
                f"错误原因: {str(e)}\n\n"
                f"请检查 Models 配置页面，确保 API 密钥有效。"
            )
            logger.error(f"LLM HTTP error: {e}")
            raise RuntimeError(error_msg) from e
        except Exception as e:
            error_msg = (
                f"LLM 请求失败\n"
                f"连接地址: {url}\n"
                f"错误原因: {str(e)}\n\n"
                f"请检查 Models 配置页面。"
            )
            logger.error(f"LLM request failed: {e}")
            raise RuntimeError(error_msg) from e

    async def complete_stream(
        self,
        messages: list[ChatMessage],
        provider: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Send a streaming completion request.

        Args:
            messages: List of chat messages.
            provider: Provider to use, defaults to default provider.
            **kwargs: Additional parameters.

        Yields:
            Streaming content chunks.

        Raises:
            RuntimeError: If service is not initialized.
            httpx.HTTPError: If request fails.
        """
        if not self._http_client:
            raise RuntimeError("LLM service not initialized")

        config = self.get_config(provider)
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(config)
        body = self._build_request_body(config, messages, stream=True, **kwargs)

        logger.debug(f"Sending streaming completion request to {url}")
        async with self._http_client.stream(
            "POST", url, headers=headers, json=body
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        # Check if the response contains an error (non-zero status in base_resp)
                        base_resp = chunk.get("base_resp", {})
                        status_code = base_resp.get("status_code", 0)
                        has_error = "error" in chunk or (status_code != 0)

                        # Handle error response
                        if has_error:
                            error_msg = chunk.get("error", {}).get("message") or base_resp.get("status_msg", str(chunk))
                            raise RuntimeError(f"LLM API error: {error_msg}")

                        # Handle normal response
                        choices = chunk.get("choices")
                        if not choices:
                            # Empty choices is not an error, just skip
                            continue
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
                    except RuntimeError:
                        raise
                    except (IndexError, KeyError) as e:
                        # Handle malformed responses - skip them
                        continue

    async def complete_stream_with_tools(
        self,
        messages: list[ChatMessage],
        provider: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Send a streaming completion request with tool support.

        Args:
            messages: List of chat messages.
            provider: Provider to use, defaults to default provider.
            tools: Optional list of tool definitions.
            **kwargs: Additional parameters.

        Yields:
            StreamChunk objects with content or tool call info.

        Raises:
            RuntimeError: If service is not initialized.
            httpx.HTTPError: If request fails.
        """
        if not self._http_client:
            raise RuntimeError("LLM service not initialized")

        config = self.get_config(provider)
        url = f"{config.base_url.rstrip('/')}/chat/completions"
        headers = self._build_headers(config)
        body = self._build_request_body(config, messages, stream=True, tools=tools, **kwargs)

        logger.debug(f"Sending streaming completion request with tools to {url}")

        # Track tool calls across chunks
        tool_calls_in_progress: dict[int, dict[str, Any]] = {}

        async with self._http_client.stream(
            "POST", url, headers=headers, json=body
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        # Yield any remaining tool calls
                        for idx, tc in tool_calls_in_progress.items():
                            yield StreamChunk(
                                is_tool_call=True,
                                tool_call_id=tc.get("id", ""),
                                tool_name=tc.get("function", {}).get("name", ""),
                                tool_arguments=tc.get("function", {}).get("arguments", ""),
                            )
                        break
                    try:
                        chunk = json.loads(data)
                        # Check for API-level errors
                        base_resp = chunk.get("base_resp", {})
                        status_code = base_resp.get("status_code", 0)
                        if status_code != 0:
                            error_msg = base_resp.get("status_msg", str(chunk))
                            raise RuntimeError(f"LLM API error: {error_msg}")

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue  # Skip empty chunks
                        choice = choices[0]
                        delta = choice.get("delta", {})
                        finish_reason = choice.get("finish_reason")

                        # Handle content
                        content = delta.get("content", "")
                        if content:
                            yield StreamChunk(content=content)

                        # Handle tool calls
                        if "tool_calls" in delta:
                            for tc_delta in delta["tool_calls"]:
                                idx = tc_delta.get("index", 0)

                                # Initialize if first chunk for this tool call
                                if idx not in tool_calls_in_progress:
                                    tool_calls_in_progress[idx] = {
                                        "id": tc_delta.get("id", ""),
                                        "function": {"name": "", "arguments": ""},
                                    }

                                # Update with delta info
                                if "id" in tc_delta:
                                    tool_calls_in_progress[idx]["id"] = tc_delta["id"]
                                if "function" in tc_delta:
                                    if "name" in tc_delta["function"]:
                                        tool_calls_in_progress[idx]["function"]["name"] = tc_delta["function"]["name"]
                                    if "arguments" in tc_delta["function"]:
                                        tool_calls_in_progress[idx]["function"]["arguments"] += tc_delta["function"]["arguments"]

                        # Handle finish
                        if finish_reason:
                            # Yield any remaining tool calls
                            for idx, tc in tool_calls_in_progress.items():
                                yield StreamChunk(
                                    is_tool_call=True,
                                    tool_call_id=tc.get("id", ""),
                                    tool_name=tc.get("function", {}).get("name", ""),
                                    tool_arguments=tc.get("function", {}).get("arguments", ""),
                                )
                            yield StreamChunk(finish_reason=finish_reason)

                    except json.JSONDecodeError:
                        continue

    async def simple_complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        provider: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Simple completion with a single prompt.

        Args:
            prompt: User prompt.
            system_prompt: Optional system prompt.
            provider: Provider to use.
            **kwargs: Additional parameters.

        Returns:
            Generated text.
        """
        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))

        response = await self.complete(messages, provider=provider, **kwargs)
        return response.content

    def get_provider_config(self, provider: str | None = None) -> dict[str, Any] | None:
        """Get provider configuration as dictionary.

        Args:
            provider: Provider name, defaults to default provider.

        Returns:
            Provider config dict with name, base_url, model, api_key (masked), or None if not found.
        """
        try:
            config = self.get_config(provider)
            provider_name = provider or self._get_default_provider_name()
            return {
                "name": provider_name,
                "base_url": config.base_url,
                "model": config.model,
                "api_key": config.api_key[:8] + "..." if len(config.api_key) > 8 else "***",
            }
        except ValueError:
            return None


# Global LLM service instance
llm_service = LLMService()
