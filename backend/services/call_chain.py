"""
Call Chain Context for LongClaw.
Provides context management for agent hierarchies.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from backend.database import db_manager
from backend.models.agent import AgentStatus

logger = logging.getLogger(__name__)


@dataclass
class CallChainContext:
    """Context for agent call chains.

    Tracks:
    - Parent-child relationships
    - Task context
    - Current progress
    - Recovery information
    """

    chain_id: str
    root_agent_id: str
    current_agent_id: str
    task_id: str | None = None
    parent_context_id: str | None = None
    depth: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)

    # Task context
    task_description: str | None = None
    task_goal: str | None = None
    task_progress: float = 0.0

    # Work context
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)

    # Recovery context
    last_successful_action: str | None = None
    failure_count: int = 0
    last_error: str | None = None

    # Agent chain
    agent_chain: list[str] = field(default_factory=list)  # List of agent IDs in chain

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "chain_id": self.chain_id,
            "root_agent_id": self.root_agent_id,
            "current_agent_id": self.current_agent_id,
            "task_id": self.task_id,
            "parent_context_id": self.parent_context_id,
            "depth": self.depth,
            "created_at": self.created_at.isoformat(),
            "task_description": self.task_description,
            "task_goal": self.task_goal,
            "task_progress": self.task_progress,
            "current_step": self.current_step,
            "completed_steps": self.completed_steps,
            "pending_steps": self.pending_steps,
            "last_successful_action": self.last_successful_action,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
            "agent_chain": self.agent_chain,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CallChainContext":
        """Create from dictionary.

        Args:
            data: Dictionary data.

        Returns:
            CallChainContext instance.
        """
        return cls(
            chain_id=data.get("chain_id", str(uuid4())),
            root_agent_id=data.get("root_agent_id", ""),
            current_agent_id=data.get("current_agent_id", ""),
            task_id=data.get("task_id"),
            parent_context_id=data.get("parent_context_id"),
            depth=data.get("depth", 0),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data else datetime.utcnow(),
            task_description=data.get("task_description"),
            task_goal=data.get("task_goal"),
            task_progress=data.get("task_progress", 0.0),
            current_step=data.get("current_step"),
            completed_steps=data.get("completed_steps", []),
            pending_steps=data.get("pending_steps", []),
            last_successful_action=data.get("last_successful_action"),
            failure_count=data.get("failure_count", 0),
            last_error=data.get("last_error"),
            agent_chain=data.get("agent_chain", []),
            metadata=data.get("metadata", {}),
        )

    def create_child_context(
        self,
        child_agent_id: str,
        subtask_description: str | None = None,
    ) -> "CallChainContext":
        """Create a child context for a sub-agent.

        Args:
            child_agent_id: The child agent's ID.
            subtask_description: Description of the subtask.

        Returns:
            New CallChainContext for the child.
        """
        new_chain = self.agent_chain + [self.current_agent_id]

        return CallChainContext(
            chain_id=str(uuid4()),
            root_agent_id=self.root_agent_id,
            current_agent_id=child_agent_id,
            task_id=self.task_id,
            parent_context_id=self.chain_id,
            depth=self.depth + 1,
            task_description=subtask_description or self.task_description,
            task_goal=self.task_goal,
            agent_chain=new_chain,
        )

    def record_progress(
        self,
        step: str | None = None,
        progress: float | None = None,
    ) -> None:
        """Record progress.

        Args:
            step: Current step.
            progress: Progress percentage.
        """
        if step:
            self.current_step = step
        if progress is not None:
            self.task_progress = progress

    def record_completion(self, step: str) -> None:
        """Record a completed step.

        Args:
            step: Completed step.
        """
        if step not in self.completed_steps:
            self.completed_steps.append(step)
        if step in self.pending_steps:
            self.pending_steps.remove(step)
        self.last_successful_action = step

    def record_failure(self, error: str) -> None:
        """Record a failure.

        Args:
            error: Error message.
        """
        self.failure_count += 1
        self.last_error = error

    def get_recovery_prompt(self) -> str:
        """Generate a recovery prompt for a restarted agent.

        Returns:
            Recovery prompt.
        """
        parts = [
            f"这是一个恢复的任务。之前的执行状态:",
            f"- 任务目标: {self.task_goal or self.task_description}",
            f"- 完成进度: {self.task_progress * 100:.0f}%",
        ]

        if self.completed_steps:
            parts.append(f"- 已完成的步骤: {', '.join(self.completed_steps)}")

        if self.pending_steps:
            parts.append(f"- 待完成的步骤: {', '.join(self.pending_steps)}")

        if self.last_successful_action:
            parts.append(f"- 最后成功的操作: {self.last_successful_action}")

        if self.last_error:
            parts.append(f"- 上次失败原因: {self.last_error}")
            parts.append(f"- 失败次数: {self.failure_count}")

        parts.append("\n请从上次中断的地方继续执行任务。")

        return "\n".join(parts)


class CallChainManager:
    """Manager for call chain contexts.

    Provides:
    - Context storage and retrieval
    - Agent crash recovery
    - Context serialization
    """

    def __init__(self) -> None:
        """Initialize the manager."""
        self._contexts: dict[str, CallChainContext] = {}
        self._agent_contexts: dict[str, str] = {}  # agent_id -> context_id

    async def create_context(
        self,
        root_agent_id: str,
        task_id: str | None = None,
        task_description: str | None = None,
        task_goal: str | None = None,
    ) -> CallChainContext:
        """Create a new call chain context.

        Args:
            root_agent_id: The root agent ID.
            task_id: Optional task ID.
            task_description: Task description.
            task_goal: Task goal.

        Returns:
            New CallChainContext.
        """
        context = CallChainContext(
            chain_id=str(uuid4()),
            root_agent_id=root_agent_id,
            current_agent_id=root_agent_id,
            task_id=task_id,
            task_description=task_description,
            task_goal=task_goal,
            agent_chain=[],
        )

        self._contexts[context.chain_id] = context
        self._agent_contexts[root_agent_id] = context.chain_id

        logger.info(f"Created call chain context {context.chain_id} for agent {root_agent_id}")
        return context

    async def get_context(self, context_id: str) -> CallChainContext | None:
        """Get a context by ID.

        Args:
            context_id: Context ID.

        Returns:
            CallChainContext or None.
        """
        return self._contexts.get(context_id)

    async def get_agent_context(self, agent_id: str) -> CallChainContext | None:
        """Get the context for an agent.

        Args:
            agent_id: Agent ID.

        Returns:
            CallChainContext or None.
        """
        context_id = self._agent_contexts.get(agent_id)
        if context_id:
            return self._contexts.get(context_id)
        return None

    async def update_context(self, context: CallChainContext) -> None:
        """Update a context.

        Args:
            context: The context to update.
        """
        self._contexts[context.chain_id] = context
        self._agent_contexts[context.current_agent_id] = context.chain_id

    async def create_child_context(
        self,
        parent_agent_id: str,
        child_agent_id: str,
        subtask_description: str | None = None,
    ) -> CallChainContext | None:
        """Create a child context for a sub-agent.

        Args:
            parent_agent_id: Parent agent ID.
            child_agent_id: Child agent ID.
            subtask_description: Subtask description.

        Returns:
            New child context or None if parent not found.
        """
        parent_context = await self.get_agent_context(parent_agent_id)
        if not parent_context:
            logger.warning(f"No context found for parent agent {parent_agent_id}")
            return None

        child_context = parent_context.create_child_context(
            child_agent_id, subtask_description
        )

        self._contexts[child_context.chain_id] = child_context
        self._agent_contexts[child_agent_id] = child_context.chain_id

        logger.info(
            f"Created child context {child_context.chain_id} "
            f"for agent {child_agent_id} (depth={child_context.depth})"
        )
        return child_context

    async def recover_agent_context(
        self,
        agent_id: str,
    ) -> CallChainContext | None:
        """Recover context for a crashed agent.

        Args:
            agent_id: The agent ID.

        Returns:
            Recovered context or None.
        """
        context = await self.get_agent_context(agent_id)
        if context:
            logger.info(f"Recovered context for agent {agent_id}")
            return context
        return None

    async def report_agent_failure(
        self,
        agent_id: str,
        error: str,
    ) -> str | None:
        """Report an agent failure and get the parent agent ID.

        Args:
            agent_id: Failed agent ID.
            error: Error message.

        Returns:
            Parent agent ID if exists.
        """
        context = await self.get_agent_context(agent_id)
        if not context:
            return None

        context.record_failure(error)

        # Find parent in chain
        if context.agent_chain:
            parent_agent_id = context.agent_chain[-1]
            return parent_agent_id

        return context.root_agent_id if context.root_agent_id != agent_id else None

    async def persist_context(self, context_id: str) -> None:
        """Persist a context to the database.

        Args:
            context_id: Context ID to persist.
        """
        context = self._contexts.get(context_id)
        if not context:
            return

        try:
            async with db_manager.session() as session:
                from backend.services.config_service import config_service

                # Store as system config with special key
                key = f"call_chain_context_{context_id}"
                value = json.dumps(context.to_dict())
                await config_service.set(key, value, session)
                logger.debug(f"Persisted context {context_id}")
        except Exception as e:
            logger.error(f"Failed to persist context: {e}")

    async def load_context(self, context_id: str) -> CallChainContext | None:
        """Load a context from the database.

        Args:
            context_id: Context ID to load.

        Returns:
            Loaded context or None.
        """
        try:
            async with db_manager.session() as session:
                from backend.models.system_config import SystemConfig
                from sqlalchemy import select

                key = f"call_chain_context_{context_id}"
                result = await session.execute(
                    select(SystemConfig).where(SystemConfig.config_key == key)
                )
                config = result.scalar_one_or_none()

                if config and config.config_value:
                    data = json.loads(config.config_value)
                    context = CallChainContext.from_dict(data)
                    self._contexts[context_id] = context
                    return context

        except Exception as e:
            logger.error(f"Failed to load context: {e}")

        return None


# Global call chain manager
call_chain_manager = CallChainManager()
