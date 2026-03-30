"""
Base Agent for LongClaw.
Abstract base class for all agent types.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus, AgentType
from backend.models.message import Message, MessageType, SenderType, ReceiverType
from backend.services.agent_service import agent_service
from backend.services.agent_settings_service import agent_settings_service
from backend.services.llm_service import ChatMessage, llm_service
from backend.services.message_service import message_service
from backend.services.model_config_service import model_config_service

logger = logging.getLogger(__name__)


def get_current_datetime_str() -> str:
    """Get current date and time string for system prompt injection.

    Returns:
        Formatted date/time string like "当前日期：2026-03-23，星期一，亚洲/上海时区"
    """
    now = datetime.now()
    weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekdays[now.weekday()]
    return f"当前日期：{now.strftime('%Y-%m-%d')}，{weekday}，亚洲/上海时区"


@dataclass
class WorkEvidence:
    """Evidence of agent work progress."""

    timestamp: datetime
    evidence_type: str  # tool_call, llm_response, message_sent
    description: str
    details: dict[str, Any] = field(default_factory=dict)


class TimeoutManager:
    """Manages dynamic timeouts for agents.

    Features:
    - Track work evidence
    - Extend timeout when progress detected (no hard limit)
    - Report stall status
    - Support "infinite" timeout as long as agent is making progress

    Design Philosophy (per 核心改进诉求20260324.md):
    - LongClaw is designed for continuous operation
    - As long as there's evidence the agent is working normally, timeout should be extended
    - Only terminate when there's clear evidence the agent has stopped
    """

    def __init__(
        self,
        base_timeout: int = 300,
        max_extension: int = 0,  # 0 means no limit - extend as long as there's progress
        min_progress_interval: int = 30,
    ) -> None:
        """Initialize the timeout manager.

        Args:
            base_timeout: Base timeout in seconds.
            max_extension: Maximum timeout extension in seconds. 0 means no limit.
            min_progress_interval: Minimum seconds between progress updates.
        """
        self._base_timeout = base_timeout
        self._max_extension = max_extension  # 0 = unlimited
        self._min_progress_interval = min_progress_interval

        self._start_time: datetime | None = None
        self._last_progress_time: datetime | None = None
        self._current_extension: int = 0
        self._work_evidence: list[WorkEvidence] = []
        self._is_stalled: bool = False
        self._touch_callback: Any = None  # Callback to update agent's updated_at in DB

    def start(self) -> None:
        """Start the timeout timer."""
        self._start_time = datetime.utcnow()
        self._last_progress_time = self._start_time
        self._current_extension = 0
        self._work_evidence = []
        self._is_stalled = False

    def set_touch_callback(self, callback: Any) -> None:
        """Set a callback to be called when progress is recorded.

        This is used to update the agent's updated_at timestamp in the database.

        Args:
            callback: Async callback function to call.
        """
        self._touch_callback = callback

    def record_progress(
        self,
        evidence_type: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record work progress.

        Args:
            evidence_type: Type of progress (tool_call, llm_response, message_sent).
            description: Description of the progress.
            details: Optional additional details.
        """
        now = datetime.utcnow()

        # Check if this is significant progress (after min interval)
        if self._last_progress_time:
            time_since_last = (now - self._last_progress_time).total_seconds()
            if time_since_last >= self._min_progress_interval:
                # Extend timeout - if max_extension is 0, there's no limit
                extension = min(int(time_since_last), 60)  # Max 60s per extension
                if self._max_extension > 0:
                    self._current_extension = min(
                        self._current_extension + extension,
                        self._max_extension,
                    )
                else:
                    # No limit - extend indefinitely as long as there's progress
                    self._current_extension = self._current_extension + extension
                logger.debug(
                    f"Extended timeout by {extension}s, "
                    f"total extension: {self._current_extension}s"
                )

        self._last_progress_time = now
        self._is_stalled = False

        # Record evidence
        evidence = WorkEvidence(
            timestamp=now,
            evidence_type=evidence_type,
            description=description,
            details=details or {},
        )
        self._work_evidence.append(evidence)

        # Call touch callback if set (to update DB)
        # Note: This should be awaited, but we can't await here
        # The caller should handle calling _touch() after record_progress

    def get_current_timeout(self) -> int:
        """Get the current effective timeout.

        Returns:
            Current timeout in seconds.
        """
        return self._base_timeout + self._current_extension

    def get_remaining_time(self) -> float:
        """Get remaining time before timeout.

        Returns:
            Remaining seconds, or -1 if not started.
        """
        if not self._start_time:
            return -1

        elapsed = (datetime.utcnow() - self._start_time).total_seconds()
        remaining = self.get_current_timeout() - elapsed
        return max(0, remaining)

    def is_timed_out(self) -> bool:
        """Check if the agent has timed out.

        Returns:
            True if timed out.
        """
        if not self._start_time:
            return False

        remaining = self.get_remaining_time()
        return remaining <= 0

    def is_stalled(self, stall_threshold: int = 60) -> bool:
        """Check if the agent is stalled (no recent progress).

        Args:
            stall_threshold: Seconds without progress to consider stalled.

        Returns:
            True if stalled.
        """
        if not self._last_progress_time:
            return True

        time_since_progress = (
            datetime.utcnow() - self._last_progress_time
        ).total_seconds()

        self._is_stalled = time_since_progress > stall_threshold
        return self._is_stalled

    def get_work_summary(self) -> dict[str, Any]:
        """Get a summary of work done.

        Returns:
            Work summary dictionary.
        """
        tool_calls = sum(1 for e in self._work_evidence if e.evidence_type == "tool_call")
        llm_responses = sum(1 for e in self._work_evidence if e.evidence_type == "llm_response")
        messages_sent = sum(1 for e in self._work_evidence if e.evidence_type == "message_sent")

        return {
            "total_evidence_count": len(self._work_evidence),
            "tool_calls": tool_calls,
            "llm_responses": llm_responses,
            "messages_sent": messages_sent,
            "current_timeout": self.get_current_timeout(),
            "remaining_time": self.get_remaining_time(),
            "is_stalled": self._is_stalled,
            "last_progress": self._last_progress_time.isoformat() if self._last_progress_time else None,
        }

    def get_recent_evidence(self, count: int = 5) -> list[dict[str, Any]]:
        """Get recent work evidence.

        Args:
            count: Number of recent evidence items.

        Returns:
            List of evidence dictionaries.
        """
        recent = self._work_evidence[-count:]
        return [
            {
                "timestamp": e.timestamp.isoformat(),
                "type": e.evidence_type,
                "description": e.description,
            }
            for e in recent
        ]


class BaseAgent(ABC):
    """Abstract base class for all agents.

    Provides:
    - Lifecycle management (create, run, pause, terminate)
    - State persistence
    - Message handling
    - LLM integration
    - Summary generation
    """

    def __init__(
        self,
        agent_id: str | None = None,
        name: str = "Agent",
        agent_type: AgentType = AgentType.WORKER,
        personality: str | None = None,
        system_prompt: str | None = None,
        llm_config: dict[str, Any] | None = None,
        parent_agent_id: str | None = None,
        task_id: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Initialize the agent.

        Args:
            agent_id: Existing agent ID (for loading from DB).
            name: Agent name.
            agent_type: Type of agent.
            personality: Personality description.
            system_prompt: System prompt for LLM.
            llm_config: LLM configuration.
            parent_agent_id: Parent agent ID.
            task_id: Associated task ID.
            timeout: Agent timeout in seconds.
        """
        self._id: str | None = agent_id
        self._name = name
        self._agent_type = agent_type
        self._personality = personality
        self._system_prompt = system_prompt
        self._llm_config = llm_config or {}
        self._parent_agent_id = parent_agent_id
        self._task_id = task_id

        self._status: AgentStatus = AgentStatus.IDLE
        self._model: Agent | None = None
        self._run_task: asyncio.Task[Any] | None = None
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._last_summary: str | None = None
        self._context: dict[str, Any] = {}

        # Dynamic timeout management
        self._timeout_manager = TimeoutManager(
            base_timeout=timeout or 300,
            max_extension=600,
            min_progress_interval=30,
        )

    @property
    def id(self) -> str:
        """Get agent ID.

        Returns:
            Agent ID.

        Raises:
            RuntimeError: If agent is not persisted.
        """
        if not self._id:
            raise RuntimeError("Agent not persisted")
        return self._id

    @property
    def name(self) -> str:
        """Get agent name.

        Returns:
            Agent name.
        """
        return self._name

    @property
    def agent_type(self) -> AgentType:
        """Get agent type.

        Returns:
            Agent type.
        """
        return self._agent_type

    @property
    def status(self) -> AgentStatus:
        """Get agent status.

        Returns:
            Agent status.
        """
        return self._status

    @property
    def task_id(self) -> str | None:
        """Get associated task ID.

        Returns:
            Task ID if associated, None otherwise.
        """
        return self._task_id

    @property
    def parent_agent_id(self) -> str | None:
        """Get parent agent ID.

        Returns:
            Parent agent ID if has parent, None otherwise.
        """
        return self._parent_agent_id

    # ==================== Lifecycle Methods ====================

    async def persist(self) -> str:
        """Persist the agent to the database.

        Returns:
            Agent ID.

        Raises:
            RuntimeError: If agent is already persisted.
        """
        if self._id:
            raise RuntimeError("Agent already persisted")

        async with db_manager.session() as session:
            agent = await agent_service.create_agent(
                session,
                agent_type=self._agent_type,
                name=self._name,
                personality=self._personality,
                parent_agent_id=self._parent_agent_id,
                task_id=self._task_id,
                llm_config=self._llm_config,
                system_prompt=self._system_prompt,
            )
            self._id = agent.id
            self._model = agent

        logger.info(f"Persisted agent {self._id} ({self._agent_type.value}): {self._name}")
        return self._id

    async def load(self, agent_id: str) -> None:
        """Load an agent from the database.

        Args:
            agent_id: Agent ID to load.

        Raises:
            ValueError: If agent not found.
        """
        async with db_manager.session() as session:
            agent = await agent_service.get_agent(session, agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            self._id = agent.id
            self._name = agent.name
            self._agent_type = agent.agent_type
            self._personality = agent.personality
            self._system_prompt = agent.system_prompt
            self._llm_config = agent.model_assignment or {}
            self._parent_agent_id = agent.parent_agent_id
            self._task_id = agent.task_id
            self._status = agent.status
            self._model = agent

        logger.info(f"Loaded agent {self._id} ({self._agent_type.value}): {self._name}")

    async def start(self) -> None:
        """Start the agent's main loop."""
        if not self._id:
            await self.persist()

        if self._status == AgentStatus.RUNNING:
            logger.warning(f"Agent {self._id} is already running")
            return

        await self._update_status(AgentStatus.RUNNING)
        self._run_task = asyncio.create_task(self._run_loop())
        logger.info(f"Started agent {self._id}")

    async def pause(self) -> None:
        """Pause the agent."""
        if self._status != AgentStatus.RUNNING:
            return

        await self._update_status(AgentStatus.PAUSED)
        logger.info(f"Paused agent {self._id}")

    async def resume(self) -> None:
        """Resume a paused agent."""
        if self._status != AgentStatus.PAUSED:
            return

        await self._update_status(AgentStatus.RUNNING)
        self._run_task = asyncio.create_task(self._run_loop())
        logger.info(f"Resumed agent {self._id}")

    async def terminate(self) -> None:
        """Terminate the agent."""
        if self._run_task:
            self._run_task.cancel()
            try:
                await self._run_task
            except asyncio.CancelledError:
                pass
            self._run_task = None

        await self._update_status(AgentStatus.TERMINATED)
        logger.info(f"Terminated agent {self._id}")

    async def _update_status(self, status: AgentStatus, error_message: str | None = None) -> None:
        """Update agent status in database.

        Args:
            status: New status.
            error_message: Optional error message when status is ERROR.
        """
        self._status = status

        async with db_manager.session() as session:
            await agent_service.update_status(session, self.id, status, error_message=error_message)

        # Publish update
        await message_service.publish_agent_update(self.id, status.value, self._task_id)

    async def _touch(self) -> None:
        """Update agent's updated_at timestamp to signal it's still active.

        This should be called during long-running operations to prevent
        the scheduler from marking the agent as error due to inactivity.
        """
        if not self._id:
            return

        async with db_manager.session() as session:
            await agent_service.touch(session, self.id)

    async def _resolve_model(self) -> tuple[str | None, str | None]:
        """Resolve the effective model for this agent.

        Resolution order:
        1. Agent's own model_assignment field
        2. Instance-level AgentSettings for this agent_id
        3. Type-level AgentSettings for this agent_type
        4. None (use default from ModelConfigService)

        Returns:
            Tuple of (provider_name, model_name) or (None, None) for default.
        """
        # Check agent's own model_assignment first
        if self._model and hasattr(self._model, 'model_assignment') and self._model.model_assignment:
            provider = self._model.model_assignment.get('provider')
            model = self._model.model_assignment.get('model')
            if provider and model:
                logger.debug(f"Using model from model_assignment: {provider}/{model}")
                return (provider, model)

        # Check AgentSettings
        if self._id:
            async with db_manager.session() as session:
                provider, model = await agent_settings_service.get_effective_model(
                    session, self._id, self._agent_type
                )
                if provider and model:
                    logger.debug(f"Using model from AgentSettings: {provider}/{model}")
                    return (provider, model)

        # Use default
        logger.debug(f"Using default model for agent type {self._agent_type.value}")
        return (None, None)

    async def _resolve_context_limit(self) -> int:
        """Resolve the context limit for this agent's model.

        Uses the model's max_context_tokens from ModelConfigService.

        Returns:
            Context limit in tokens (default 8192 if not configured).
        """
        provider, model = await self._resolve_model()

        async with db_manager.session() as session:
            if provider and model:
                limit = await model_config_service.get_model_context_limit(
                    session, provider, model
                )
                logger.debug(f"Context limit for {provider}/{model}: {limit}")
                return limit

            # Get default provider's first model context limit
            config = await model_config_service.get_config(session)
            default_provider = config.default_provider
            provider_config = await model_config_service.get_provider_config(
                session, default_provider
            )

            if provider_config:
                models = provider_config.get("models", [])
                if models:
                    first_model = models[0]
                    if isinstance(first_model, dict):
                        return first_model.get("max_context_tokens", 8192)

        return 8192

    # ==================== Timeout Management ====================

    def _record_progress(
        self,
        evidence_type: str,
        description: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record work progress for dynamic timeout management.

        Args:
            evidence_type: Type of progress (tool_call, llm_response, message_sent).
            description: Description of the progress.
            details: Optional additional details.
        """
        self._timeout_manager.record_progress(evidence_type, description, details)

    def _get_remaining_timeout(self) -> float:
        """Get remaining time before timeout.

        Returns:
            Remaining seconds.
        """
        return self._timeout_manager.get_remaining_time()

    def _is_timed_out(self) -> bool:
        """Check if the agent has timed out.

        Returns:
            True if timed out.
        """
        return self._timeout_manager.is_timed_out()

    def _is_stalled(self, threshold: int = 60) -> bool:
        """Check if the agent is stalled (no recent progress).

        Args:
            threshold: Seconds without progress to consider stalled.

        Returns:
            True if stalled.
        """
        return self._timeout_manager.is_stalled(threshold)

    def _get_work_summary(self) -> dict[str, Any]:
        """Get a summary of work done.

        Returns:
            Work summary dictionary.
        """
        return self._timeout_manager.get_work_summary()

    # ==================== Main Loop ====================

    async def _run_loop(self) -> None:
        """Main agent loop."""
        try:
            await self.on_start()

            while self._status == AgentStatus.RUNNING:
                try:
                    # Wait for message with timeout
                    message = await asyncio.wait_for(
                        self._message_queue.get(),
                        timeout=1.0,
                    )
                    await self._handle_message(message)
                except asyncio.TimeoutError:
                    # No message, run idle processing
                    await self.on_idle()

        except asyncio.CancelledError:
            logger.debug(f"Agent {self._id} run loop cancelled")
        except Exception as e:
            logger.exception(f"Agent {self._id} error: {e}")
            await self._update_status(AgentStatus.ERROR, error_message=str(e))
        finally:
            await self.on_stop()

    # ==================== Message Handling ====================

    async def send_message(
        self,
        receiver_type: ReceiverType,
        receiver_id: str,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        task_id: str | None = None,
        subtask_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """Send a message to another entity.

        Args:
            receiver_type: Type of receiver.
            receiver_id: ID of receiver.
            content: Message content.
            message_type: Type of message.
            task_id: Optional task ID.
            subtask_id: Optional subtask ID.
            metadata: Optional metadata.

        Returns:
            Created message.
        """
        async with db_manager.session() as session:
            message = await message_service.create_message(
                session,
                sender_type=SenderType(self._agent_type.value),
                sender_id=self.id,
                receiver_type=receiver_type,
                receiver_id=receiver_id,
                content=content,
                message_type=message_type,
                task_id=task_id or self._task_id,
                subtask_id=subtask_id,
                metadata=metadata,
            )

        # Publish notification
        await message_service.publish_message(message)

        logger.debug(
            f"Agent {self._id} sent message to {receiver_type.value}:{receiver_id}"
        )
        return message

    async def receive_message(self, message: Message) -> None:
        """Receive a message into the queue.

        Args:
            message: Message to receive.
        """
        await self._message_queue.put(message)
        logger.debug(f"Agent {self._id} received message from {message.sender_type}")

    async def _handle_message(self, message: Message) -> None:
        """Handle an incoming message.

        Args:
            message: Message to handle.
        """
        await self.on_message(message)

    # ==================== LLM Integration ====================

    async def think(
        self,
        messages: list[ChatMessage],
        provider: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Call the LLM to think.

        Args:
            messages: Chat messages.
            provider: Optional provider override.
            **kwargs: Additional parameters.

        Returns:
            LLM response content.
        """
        # Add system prompt if configured
        if self._system_prompt:
            # Inject current date/time into system prompt
            datetime_str = get_current_datetime_str()
            full_system_prompt = f"{datetime_str}\n\n{self._system_prompt}"
            system_msg = ChatMessage(role="system", content=full_system_prompt)
            messages = [system_msg] + messages

        # Merge llm config with kwargs
        merged_kwargs = {**self._llm_config, **kwargs}

        # Resolve provider/model if not specified
        resolved_provider = provider
        if resolved_provider is None:
            resolved_provider, resolved_model = await self._resolve_model()
            if resolved_model:
                merged_kwargs['model'] = resolved_model

        response = await llm_service.complete(messages, provider=resolved_provider, **merged_kwargs)
        return response.content

    async def think_stream(
        self,
        messages: list[ChatMessage],
        provider: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Call the LLM with streaming.

        Args:
            messages: Chat messages.
            provider: Optional provider override.
            **kwargs: Additional parameters.

        Yields:
            Content chunks.
        """
        if self._system_prompt:
            # Inject current date/time into system prompt
            datetime_str = get_current_datetime_str()
            full_system_prompt = f"{datetime_str}\n\n{self._system_prompt}"
            system_msg = ChatMessage(role="system", content=full_system_prompt)
            messages = [system_msg] + messages

        # Merge llm config with kwargs
        merged_kwargs = {**self._llm_config, **kwargs}

        # Resolve provider/model if not specified
        resolved_provider = provider
        if resolved_provider is None:
            resolved_provider, resolved_model = await self._resolve_model()
            if resolved_model:
                merged_kwargs['model'] = resolved_model

        async for chunk in llm_service.complete_stream(
            messages, provider=resolved_provider, **merged_kwargs
        ):
            yield chunk

    # ==================== Summary Generation ====================

    async def get_summary(self) -> str:
        """Generate a summary of the agent's work.

        Returns:
            Summary text.
        """
        if self._last_summary:
            return self._last_summary

        # Build summary from context and recent activity
        summary_parts = [
            f"Agent: {self._name} ({self._agent_type.value})",
            f"Status: {self._status.value}",
        ]

        if self._task_id:
            summary_parts.append(f"Task ID: {self._task_id}")

        if self._context:
            summary_parts.append(f"Context: {self._context}")

        # Let subclass add to summary
        custom_summary = await self.generate_summary()
        if custom_summary:
            summary_parts.append(f"Summary: {custom_summary}")

        self._last_summary = "\n".join(summary_parts)
        return self._last_summary

    async def save_summary(self, summary: str) -> None:
        """Save a summary.

        Args:
            summary: Summary text.
        """
        self._last_summary = summary

        async with db_manager.session() as session:
            await agent_service.update_agent(
                session,
                self.id,
                personality=f"{self._personality or ''}\n\nLast Summary: {summary}",
            )

    # ==================== Abstract Methods ====================

    @abstractmethod
    async def on_start(self) -> None:
        """Called when the agent starts.

        Override this to perform initialization.
        """
        pass

    @abstractmethod
    async def on_stop(self) -> None:
        """Called when the agent stops.

        Override this to perform cleanup.
        """
        pass

    @abstractmethod
    async def on_message(self, message: Message) -> None:
        """Handle an incoming message.

        Args:
            message: The message to handle.

        Override this to process messages.
        """
        pass

    @abstractmethod
    async def on_idle(self) -> None:
        """Called when the agent is idle (no messages).

        Override this to perform periodic tasks.
        """
        pass

    @abstractmethod
    async def generate_summary(self) -> str:
        """Generate a summary of the agent's work.

        Returns:
            Summary text.

        Override this to provide custom summary logic.
        """
        pass
