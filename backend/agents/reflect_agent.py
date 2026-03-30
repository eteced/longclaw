"""
Reflect Agent for LongClaw.
Monitors agent execution and provides intervention when needed.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus, AgentType
from backend.models.message import Message, MessageType, ReceiverType, SenderType
from backend.services.config_service import config_service
from backend.services.llm_service import ChatMessage, llm_service
from backend.services.message_service import message_service

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """State of a monitored agent."""

    agent_id: str
    agent_name: str
    agent_type: str
    status: str
    task_id: str | None
    parent_agent_id: str | None
    last_activity: datetime
    last_output: str | None = None
    consecutive_same_outputs: int = 0
    tool_calls_without_progress: int = 0
    is_stuck: bool = False
    stuck_reason: str | None = None


@dataclass
class ReflectAnalysis:
    """Result of reflect analysis."""

    agent_id: str
    needs_intervention: bool
    is_truly_stuck: bool
    intervention_message: str | None = None
    should_terminate: bool = False
    reason: str | None = None


class ReflectAgent:
    """Reflect Agent - monitors and intervenes in agent execution.

    This agent:
    - Monitors all running agents for signs of being stuck
    - Sends intervention messages to help agents continue
    - Can recommend termination for truly stuck agents
    - Reports failures to parent agents
    """

    def __init__(self) -> None:
        """Initialize the reflect agent."""
        self._id: str = f"reflect-{uuid4().hex[:8]}"
        self._agent_states: dict[str, AgentState] = {}
        self._running: bool = False
        self._check_interval: int = 30  # seconds
        self._stuck_threshold: int | None = 120  # seconds without activity, None means disabled
        self._same_output_threshold: int = 3  # consecutive same outputs
        self._prompt_templates: dict[str, str] = {
            "gentle": [
                "怎么样了？",
                "进展如何？",
                "还在处理吗？",
                "有什么需要帮助的吗？",
            ],
            "urgent": [
                "看起来卡住了，需要帮助吗？",
                "检测到长时间没有进展，请确认当前状态。",
                "如果有问题，请告诉我，我可以帮你调整计划。",
            ],
            "terminate": "检测到 Agent 已无法继续工作，建议终止并向上汇报。",
        }

    async def start(self) -> None:
        """Start the reflect agent."""
        self._running = True
        logger.info(f"Reflect agent {self._id} started")

        # Load configuration
        # Note: get_int returns None when config value is -1 (disabled)
        self._check_interval = await config_service.get_int("reflect_check_interval", 30)
        self._stuck_threshold = await config_service.get_int("reflect_stuck_threshold", 120)

    async def stop(self) -> None:
        """Stop the reflect agent."""
        self._running = False
        logger.info(f"Reflect agent {self._id} stopped")

    async def check_all_agents(self) -> list[ReflectAnalysis]:
        """Check all running agents.

        Returns:
            List of analysis results for agents needing intervention.
        """
        results = []

        async with db_manager.session() as session:
            from sqlalchemy import select

            # Get all running/idle agents (exclude TERMINATED, ERROR)
            result = await session.execute(
                select(Agent).where(
                    Agent.status.in_([AgentStatus.RUNNING, AgentStatus.IDLE])
                )
            )
            agents = list(result.scalars().all())

            for agent in agents:
                state = await self._get_agent_state(agent)
                analysis = await self._analyze_agent(state)

                if analysis.needs_intervention:
                    results.append(analysis)
                    self._agent_states[agent.id] = state

        return results

    async def _get_agent_state(self, agent: Agent) -> AgentState:
        """Get the current state of an agent.

        Args:
            agent: The agent to get state for.

        Returns:
            Agent state.
        """
        # Check if we have previous state
        prev_state = self._agent_states.get(agent.id)

        # Get recent messages to check for output
        async with db_manager.session() as session:
            messages = await message_service.get_agent_messages(
                session, agent.id, limit=5
            )

        last_output = None
        if messages:
            # Get the most recent assistant message
            for msg in messages:
                if msg.sender_type.value == agent.agent_type.value:
                    last_output = msg.content
                    break

        # Calculate consecutive same outputs
        consecutive_same = 0
        if prev_state and last_output and prev_state.last_output:
            if last_output == prev_state.last_output:
                consecutive_same = prev_state.consecutive_same_outputs + 1
            else:
                consecutive_same = 0

        return AgentState(
            agent_id=agent.id,
            agent_name=agent.name,
            agent_type=agent.agent_type.value,
            status=agent.status.value,
            task_id=agent.task_id,
            parent_agent_id=agent.parent_agent_id,
            last_activity=agent.updated_at,
            last_output=last_output,
            consecutive_same_outputs=consecutive_same,
            tool_calls_without_progress=prev_state.tool_calls_without_progress if prev_state else 0,
        )

    async def _analyze_agent(self, state: AgentState) -> ReflectAnalysis:
        """Analyze an agent's state to determine if intervention is needed.

        Args:
            state: The agent state to analyze.

        Returns:
            Analysis result.
        """
        now = datetime.utcnow()
        time_since_activity = (now - state.last_activity).total_seconds()

        # Check if agent is stuck based on time
        # If _stuck_threshold is None (disabled), skip time-based check
        if self._stuck_threshold is None:
            is_time_stuck = False
        else:
            is_time_stuck = time_since_activity > self._stuck_threshold

        # Check if agent is stuck based on repeated outputs
        is_output_stuck = state.consecutive_same_outputs >= self._same_output_threshold

        # Determine intervention level
        if is_time_stuck or is_output_stuck:
            # More severe: over 2x threshold
            if self._stuck_threshold is not None and time_since_activity > self._stuck_threshold * 2:
                return ReflectAnalysis(
                    agent_id=state.agent_id,
                    needs_intervention=True,
                    is_truly_stuck=True,
                    intervention_message=self._get_prompt("urgent"),
                    should_terminate=self._stuck_threshold is not None
                        and time_since_activity > self._stuck_threshold * 3,
                    reason=f"Agent inactive for {int(time_since_activity)}s",
                )

            # Moderate: needs intervention
            return ReflectAnalysis(
                agent_id=state.agent_id,
                needs_intervention=True,
                is_truly_stuck=False,
                intervention_message=self._get_prompt("gentle"),
                should_terminate=False,
                reason=f"Agent may be stuck: time_inactive={int(time_since_activity)}s, "
                       f"consecutive_same_outputs={state.consecutive_same_outputs}",
            )

        return ReflectAnalysis(
            agent_id=state.agent_id,
            needs_intervention=False,
            is_truly_stuck=False,
        )

    def _get_prompt(self, level: str) -> str:
        """Get an intervention prompt.

        Args:
            level: Prompt level (gentle, urgent).

        Returns:
            Intervention prompt.
        """
        import random

        prompts = self._prompt_templates.get(level, self._prompt_templates["gentle"])
        if isinstance(prompts, list):
            return random.choice(prompts)
        return prompts

    async def send_intervention(
        self,
        agent_id: str,
        message: str,
    ) -> Message | None:
        """Send an intervention message to an agent.

        Args:
            agent_id: The agent ID to send message to.
            message: The intervention message.

        Returns:
            Created message or None.
        """
        try:
            async with db_manager.session() as session:
                msg = await message_service.create_message(
                    session,
                    sender_type=SenderType.SYSTEM,
                    sender_id=self._id,
                    receiver_type=ReceiverType.AGENT,
                    receiver_id=agent_id,
                    content=message,
                    message_type=MessageType.TEXT,
                )
                await message_service.publish_message(msg)
                logger.info(f"Sent intervention to agent {agent_id}: {message[:50]}...")
                return msg
        except Exception as e:
            logger.error(f"Failed to send intervention: {e}")
            return None

    async def report_failure_to_parent(
        self,
        agent_id: str,
        parent_agent_id: str,
        reason: str,
    ) -> None:
        """Report an agent failure to its parent agent.

        Args:
            agent_id: The failed agent ID.
            parent_agent_id: The parent agent ID.
            reason: The failure reason.
        """
        message = (
            f"子任务 Agent {agent_id} 执行失败: {reason}\n"
            f"请重新规划该任务或创建新的执行 Agent。"
        )

        try:
            async with db_manager.session() as session:
                msg = await message_service.create_message(
                    session,
                    sender_type=SenderType.SYSTEM,
                    sender_id=self._id,
                    receiver_type=ReceiverType.AGENT,
                    receiver_id=parent_agent_id,
                    content=message,
                    message_type=MessageType.TEXT,
                )
                await message_service.publish_message(msg)
                logger.info(f"Reported failure of {agent_id} to parent {parent_agent_id}")
        except Exception as e:
            logger.error(f"Failed to report failure: {e}")

    async def record_agent_progress(
        self,
        agent_id: str,
        progress_type: str,
        details: str | None = None,
    ) -> None:
        """Record that an agent has made progress.

        This resets the stuck detection for the agent.

        Args:
            agent_id: The agent ID.
            progress_type: Type of progress (tool_call, llm_response, message_sent).
            details: Optional details.
        """
        if agent_id in self._agent_states:
            state = self._agent_states[agent_id]
            state.last_activity = datetime.utcnow()
            state.tool_calls_without_progress = 0
            logger.debug(f"Agent {agent_id} made progress: {progress_type}")


# Global reflect agent instance
reflect_agent = ReflectAgent()
