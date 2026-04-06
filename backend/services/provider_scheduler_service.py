"""
Provider Scheduler Service for LongClaw.
Manages efficient allocation of model inference slots to agents based on priority rules.

Allocation Priority Rules:
1. When Resident/Owner needs immediate reply to user → allocate, otherwise reclaim
2. When Reflect mechanism needs to check worker and send messages → allocate, otherwise reclaim
3. When Owner Agent hasn't done task planning/created workers OR has no workers running → allocate, otherwise reclaim
4. When worker is not waiting for tool chain, is running → allocate, otherwise reclaim

If no allocation needed, sleep 1 second and loop again.
"""
import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus, AgentType
from backend.models.message import Message, MessageType, ReceiverType, SenderType
from backend.models.model_slot import ModelSlot
from backend.models.task import Task, TaskStatus
from backend.models.subtask import Subtask, SubtaskStatus
from backend.services.config_service import config_service

logger = logging.getLogger(__name__)


# Priority levels for allocation
class Priority:
    """Priority levels for slot allocation."""
    RESIDENT_REPLY = 100  # Highest - user waiting
    REFLECT_CHECK = 90     # System maintenance
    OWNER_PLANNING = 80    # Task initialization
    WORKER_WAITING_OWNER = 75  # Owner should respond to waiting workers
    OWNER_WAITING_WORKERS = 70  # Has workers but waiting
    WORKER_RUNNING = 60    # Actively working
    WORKER_WAITING_TOOL = 50   # Waiting for tool (lower priority)
    IDLE = 10              # Lowest - just allocated but not working


@dataclass
class SlotAllocation:
    """Represents a slot allocation request or current allocation."""
    agent_id: str
    provider_name: str
    model_name: str
    priority: int
    priority_reason: str
    operation_type: str
    task_id: str | None = None
    subtask_id: str | None = None


@dataclass
class AgentState:
    """Current state of an agent for scheduling decisions."""
    agent_id: str
    agent_type: AgentType
    name: str
    status: AgentStatus
    task_id: str | None
    parent_agent_id: str | None
    last_llm_call: datetime | None
    last_heartbeat: datetime
    is_waiting_for_reply: bool = False  # Someone waiting for this agent's reply
    is_waiting_for_tool: bool = False    # Agent is waiting for tool execution
    is_waiting_for_owner: bool = False   # Worker waiting for owner response
    worker_count: int = 0               # Number of active workers
    has_completed_planning: bool = False  # Owner has created workers


class ProviderSchedulerService:
    """Service for managing provider model slot allocation.

    This service runs a continuous loop that:
    1. Checks all active agents and their scheduling needs
    2. Allocates slots based on priority rules
    3. Reclaims slots from agents that no longer need them
    4. Ensures no provider/model exceeds max parallel requests
    """

    def __init__(self) -> None:
        """Initialize the provider scheduler service."""
        self._running: bool = False
        self._scheduler_task: asyncio.Task[Any] | None = None
        self._check_interval: float = 1.0  # Check every second
        self._heartbeat_timeout: int = 60  # Seconds before considering slot abandoned

        # Cache for provider config (loaded from DB)
        self._provider_max_parallel: dict[str, dict[str, int]] = {}  # provider -> model -> max
        self._provider_total_max: dict[str, int] = {}  # provider -> max total
        self._default_provider: str = "openai"  # Default provider name
        self._default_model: str = "minimax-m2.7"  # Default model name

        # Current allocations: agent_id -> ModelSlot
        self._allocations: dict[str, ModelSlot] = {}

        # Lock for allocation changes
        self._allocation_lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the provider scheduler."""
        if self._running:
            logger.warning("Provider scheduler already running")
            return

        self._running = True
        await self._load_provider_config()
        self._scheduler_task = asyncio.create_task(self._schedule_loop())
        logger.info("Provider scheduler started")

    async def stop(self) -> None:
        """Stop the provider scheduler."""
        self._running = False

        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            self._scheduler_task = None

        # Release all slots
        async with self._allocation_lock:
            await self._release_all_slots()

        logger.info("Provider scheduler stopped")

    async def _load_provider_config(self) -> None:
        """Load provider parallelism configuration from database."""
        from backend.services.model_config_service import model_config_service

        try:
            async with db_manager.session() as session:
                config = await model_config_service.get_config(session)

                self._provider_max_parallel = {}
                self._provider_total_max = {}
                self._default_provider = config.default_provider or "openai"
                self._default_model = "default"  # Will be set when we find the default provider

                for provider in config.providers:
                    provider_name = provider.get("name", "")
                    # Provider-level max parallel
                    self._provider_total_max[provider_name] = provider.get("max_parallel_requests", 10)

                    # Model-level max parallel
                    self._provider_max_parallel[provider_name] = {}
                    for model in provider.get("models", []):
                        model_name = model.get("name", "")
                        self._provider_max_parallel[provider_name][model_name] = model.get(
                            "max_parallel_requests",
                            self._provider_total_max.get(provider_name, 10)
                        )
                        # Set default model from the default provider
                        # Note: _default_model is initialized to "default" string, so we check == "default"
                        if provider_name == self._default_provider and self._default_model == "default":
                            self._default_model = model_name

                # If no models found for default provider, use "default"
                if self._default_model == "default" and self._default_provider in self._provider_max_parallel:
                    models = self._provider_max_parallel[self._default_provider]
                    if models:
                        self._default_model = next(iter(models.keys()))

                logger.info(f"Loaded provider config: {self._provider_max_parallel}, default_provider: {self._default_provider}, default_model: {self._default_model}")

        except Exception as e:
            logger.error(f"Failed to load provider config: {e}")
            # Use defaults
            self._default_provider = "openai"
            self._default_model = "minimax-m2.7"
            self._provider_max_parallel = {self._default_provider: {self._default_model: 10}}
            self._provider_total_max = {self._default_provider: 10}

    async def _schedule_loop(self) -> None:
        """Main scheduling loop."""
        while self._running:
            try:
                await self._run_schedule_cycle()
            except Exception as e:
                logger.exception(f"Error in schedule cycle: {e}")

            await asyncio.sleep(self._check_interval)

    async def _run_schedule_cycle(self) -> None:
        """Run one scheduling cycle."""
        # Step 1: Get all scheduling decisions needed
        allocation_requests = await self._gather_allocation_requests()

        # Step 2: Check current allocations and reclaim if needed
        await self._check_and_reclaim_slots()

        # Step 3: Process new allocation requests (priority order)
        allocation_requests.sort(key=lambda x: x.priority, reverse=True)

        for request in allocation_requests:
            await self._try_allocate(request)

        # Step 4: Update agent model_assignment to reflect current slot
        await self._update_agent_model_assignments()

    async def _should_resident_always_allocate(self) -> bool:
        """Check if resident agents should always get slot allocation.

        Returns:
            True if resident should always allocate, False if only when active.
        """
        try:
            return await config_service.get_bool("resident_always_allocate_slot", True)
        except Exception:
            return True  # Default to always allocating

    async def _gather_allocation_requests(self) -> list[SlotAllocation]:
        """Gather all agents that need model slots.

        Returns:
            List of allocation requests sorted by priority.
        """
        requests: list[SlotAllocation] = []

        async with db_manager.session() as session:
            # Get all running and waiting agents
            result = await session.execute(
                select(Agent).where(Agent.status.in_([AgentStatus.RUNNING, AgentStatus.WAITING]))
            )
            agents = list(result.scalars().all())

            # Track owners that have workers in WAITING state
            owners_with_waiting_workers: set[str] = set()

            for agent in agents:
                state = await self._get_agent_state(session, agent)

                # Rule 0: Worker in WAITING state - notify owner to respond
                if state.agent_type in (AgentType.WORKER, AgentType.SUB) and state.status == AgentStatus.WAITING:
                    if state.parent_agent_id:
                        owners_with_waiting_workers.add(state.parent_agent_id)

                # Rule 1: Resident agent gets slot if running and has recent activity
                # RESIDENT agents need to be responsive to user input, but can release
                # slot when idle if configured
                if state.agent_type == AgentType.RESIDENT:
                    # Check if resident should always get slot or only when active
                    always_allocate = await self._should_resident_always_allocate()

                    if always_allocate or state.is_waiting_for_reply:
                        # Either always allocate mode, or has pending user message
                        requests.append(SlotAllocation(
                            agent_id=state.agent_id,
                            provider_name=self._default_provider,
                            model_name=self._default_model,
                            priority=Priority.RESIDENT_REPLY,
                            priority_reason="Resident agent is the user interface",
                            operation_type="resident_reply",
                            task_id=state.task_id,
                        ))
                    else:
                        # Idle mode - no recent user activity, don't allocate
                        logger.debug(f"Resident agent {state.agent_id} is idle, not allocating slot")

                # Rule 2: Owner Agent hasn't planned or has no workers
                elif state.agent_type == AgentType.OWNER:
                    # Check if this owner has waiting workers
                    has_waiting = state.agent_id in owners_with_waiting_workers

                    if not state.has_completed_planning or state.worker_count == 0:
                        requests.append(SlotAllocation(
                            agent_id=state.agent_id,
                            provider_name=self._default_provider,
                            model_name=self._default_model,
                            priority=Priority.OWNER_PLANNING,
                            priority_reason="Owner agent needs to plan or create workers",
                            operation_type="owner_planning",
                            task_id=state.task_id,
                        ))
                    elif has_waiting:
                        # Has workers in WAITING state - respond with higher priority
                        requests.append(SlotAllocation(
                            agent_id=state.agent_id,
                            provider_name=self._default_provider,
                            model_name=self._default_model,
                            priority=Priority.WORKER_WAITING_OWNER,
                            priority_reason="Owner has worker waiting for clarification",
                            operation_type="owner_respond_worker",
                            task_id=state.task_id,
                        ))
                    # NOTE: Owner monitoring (state.worker_count > 0 but no waiting workers)
                    # does NOT get a slot allocation - workers should use the slots instead.
                    # Owner only needs a slot when planning or when workers need response.

                # Rule 3: Worker running (not waiting for tool)
                elif state.agent_type in (AgentType.WORKER, AgentType.SUB):
                    if not state.is_waiting_for_tool:
                        requests.append(SlotAllocation(
                            agent_id=state.agent_id,
                            provider_name=self._default_provider,
                            model_name=self._default_model,
                            priority=Priority.WORKER_RUNNING,
                            priority_reason="Worker agent is actively running",
                            operation_type="worker_execution",
                            task_id=state.task_id,
                            subtask_id=None,  # Will be filled from agent's task
                        ))
                    else:
                        requests.append(SlotAllocation(
                            agent_id=state.agent_id,
                            provider_name=self._default_provider,
                            model_name=self._default_model,
                            priority=Priority.WORKER_WAITING_TOOL,
                            priority_reason="Worker agent waiting for tool",
                            operation_type="worker_waiting_tool",
                            task_id=state.task_id,
                        ))

        return requests

    async def _get_agent_state(self, session: AsyncSession, agent: Agent) -> AgentState:
        """Get current state of an agent for scheduling decisions.

        Args:
            session: Database session.
            agent: The agent to check.

        Returns:
            AgentState with scheduling information.
        """
        state = AgentState(
            agent_id=agent.id,
            agent_type=agent.agent_type,
            name=agent.name,
            status=agent.status,
            task_id=agent.task_id,
            parent_agent_id=agent.parent_agent_id,
            last_llm_call=None,
            last_heartbeat=agent.updated_at or datetime.utcnow(),
        )

        # Check if this agent has unresponded messages addressed to them
        # is_waiting_for_reply means "SOMEONE sent a message TO this agent and is waiting for a reply"
        if agent.agent_type == AgentType.RESIDENT:
            # For Resident: check for unresponded messages from USER (via CHANNEL)
            state.is_waiting_for_reply = await self._has_unresponded_messages_to_agent(
                session,
                agent.id,
                receiver_type=ReceiverType.RESIDENT,
                sender_type=SenderType.CHANNEL,  # User messages come via channel
                max_age_seconds=30.0,
            )
        elif agent.agent_type == AgentType.OWNER:
            # For Owner: check for unresponded QUESTION messages from workers
            state.is_waiting_for_reply = await self._has_unresponded_messages_to_agent(
                session,
                agent.id,
                receiver_type=ReceiverType.OWNER,
                sender_type=SenderType.WORKER,
                message_type=MessageType.QUESTION,
                max_age_seconds=60.0,  # Owners can take longer to respond
            )

        # For OWNER agents, check if they have created workers
        if agent.agent_type == AgentType.OWNER and agent.task_id:
            worker_result = await session.execute(
                select(func.count(Agent.id))
                .where(Agent.parent_agent_id == agent.id)
                .where(Agent.status.in_([AgentStatus.RUNNING, AgentStatus.WAITING]))
            )
            state.worker_count = worker_result.scalar_one()

            # Check if planning is done by checking if subtasks exist
            subtask_result = await session.execute(
                select(func.count(Subtask.id))
                .where(Subtask.task_id == agent.task_id)
            )
            subtask_count = subtask_result.scalar_one()
            state.has_completed_planning = subtask_count > 0

        # For WORKER/SUB agents, check if waiting for owner (WAITING status)
        if agent.agent_type in (AgentType.WORKER, AgentType.SUB):
            if agent.status == AgentStatus.WAITING:
                state.is_waiting_for_owner = True
            else:
                # Check recent tool execution - if last message was a tool result, might be waiting
                tool_msg = await session.execute(
                    select(Message)
                    .where(Message.sender_id == agent.id)
                    .where(Message.message_type == "tool")  # type: ignore
                    .order_by(Message.created_at.desc())
                    .limit(1)
                )
                tool_result = tool_msg.scalar_one_or_none()
                if tool_result:
                    # If tool result was sent recently, agent is likely waiting for next LLM call
                    time_since_tool = (datetime.utcnow() - tool_result.created_at).total_seconds()
                    if time_since_tool < 5:
                        state.is_waiting_for_tool = False  # Just got tool result, ready to continue
                    elif time_since_tool < 30:
                        state.is_waiting_for_tool = True  # Waiting for LLM to process result

        return state

    async def _has_unresponded_messages_to_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        receiver_type: ReceiverType,
        sender_type: SenderType | None = None,
        message_type: MessageType | None = None,
        max_age_seconds: float = 30.0,
    ) -> bool:
        """Check if an agent has unresponded messages directed to them.

        An unresponded message is one where:
        1. The message was sent TO the agent (receiver_id = agent_id)
        2. The agent has not sent a response BACK TO THE ORIGINAL SENDER

        IMPORTANT: We do NOT check message age here. If a message needs reply,
        the agent should get a slot regardless of message age. The agent might be
        busy processing other tasks. The heartbeat-based reclaim logic will handle
        truly stuck agents.

        We only consider it responded if the agent sent a message specifically
        to the original sender (receiver_id of response == sender_id of received message).
        If the agent sent messages to OTHER recipients, the original sender is still waiting.

        Args:
            session: Database session.
            agent_id: The agent's ID.
            receiver_type: The receiver type (e.g., RESIDENT, OWNER).
            sender_type: Optional filter for specific sender type (e.g., CHANNEL, WORKER).
            message_type: Optional filter for specific message type (e.g., QUESTION).
            max_age_seconds: Deprecated, no longer used (kept for API compatibility).

        Returns:
            True if there are unresponded messages, False otherwise.
        """
        from sqlalchemy import and_

        # 1. Find the most recent message TO this agent
        conditions = [
            Message.receiver_id == agent_id,
            Message.receiver_type == receiver_type,
        ]
        if sender_type:
            conditions.append(Message.sender_type == sender_type)
        if message_type:
            conditions.append(Message.message_type == message_type)

        result = await session.execute(
            select(Message)
            .where(and_(*conditions))
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        latest_received = result.scalar_one_or_none()

        if not latest_received:
            return False

        # 2. IMPORTANT: We no longer check message age here.
        # If a message needs reply, the agent should get a slot regardless of message age.
        # The agent might be busy with other tasks, so we give it time to process.
        # The heartbeat-based reclaim logic will handle truly stuck agents.

        # 3. Check if the agent sent a response BACK TO THE SENDER of the received message
        # The response must be directed at the original sender, not just any message from the agent
        response_result = await session.execute(
            select(Message)
            .where(
                and_(
                    Message.sender_id == agent_id,
                    Message.receiver_id == latest_received.sender_id,
                    Message.created_at > latest_received.created_at
                )
            )
            .order_by(Message.created_at.asc())
            .limit(1)
        )
        response_msg = response_result.scalar_one_or_none()

        # If agent sent a message back to the original sender, it has responded
        # Otherwise, it hasn't responded yet (even if it sent other messages)
        return response_msg is None

    async def _check_and_reclaim_slots(self) -> None:
        """Check current allocations and reclaim if no longer needed."""
        async with self._allocation_lock:
            for agent_id, slot in list(self._allocations.items()):
                if slot.is_released:
                    continue

                # Check if slot is abandoned (no heartbeat)
                time_since_heartbeat = (datetime.utcnow() - slot.last_heartbeat).total_seconds()
                if time_since_heartbeat > self._heartbeat_timeout:
                    logger.warning(f"Reclaiming abandoned slot for agent {agent_id}")
                    await self._release_slot(slot)
                    continue

                # Check if agent still exists and needs the slot
                async with db_manager.session() as session:
                    result = await session.execute(
                        select(Agent).where(Agent.id == agent_id)
                    )
                    agent = result.scalar_one_or_none()

                    if not agent or agent.status != AgentStatus.RUNNING:
                        # Agent is done or terminated, release slot
                        await self._release_slot(slot)
                        continue

                    # Check if the allocation priority is still valid
                    state = await self._get_agent_state(session, agent)
                    current_priority = await self._get_current_priority(state)

                    # For resident agents, check if they should release slot when idle
                    if state.agent_type == AgentType.RESIDENT:
                        always_allocate = await self._should_resident_always_allocate()
                        if not always_allocate and not state.is_waiting_for_reply:
                            # Resident is idle and not configured to always allocate
                            logger.info(f"Reclaiming idle resident slot for agent {agent_id}")
                            await self._release_slot(slot)
                            continue

                    # For owner agents, reclaim if just monitoring (no planning, no waiting workers)
                    if state.agent_type == AgentType.OWNER:
                        # Check if any workers are waiting for this owner
                        waiting_workers_result = await session.execute(
                            select(func.count(Agent.id))
                            .where(Agent.parent_agent_id == agent_id)
                            .where(Agent.status == AgentStatus.WAITING)
                        )
                        waiting_worker_count = waiting_workers_result.scalar_one()

                        if state.has_completed_planning and state.worker_count > 0 and waiting_worker_count == 0:
                            # Owner is monitoring, has workers, but none are waiting for response
                            # Release slot so workers can use it
                            logger.debug(f"Reclaiming monitoring owner slot for agent {agent_id}")
                            await self._release_slot(slot)
                            continue

                    if current_priority < slot.priority:
                        # Priority dropped significantly, might want to reclaim
                        # But for now, we keep the slot if agent is still running
                        pass

    async def _get_current_priority(self, state: AgentState) -> int:
        """Get current priority level for an agent state.

        Args:
            state: Current agent state.

        Returns:
            Priority level.
        """
        if state.is_waiting_for_reply:
            return Priority.RESIDENT_REPLY
        elif state.agent_type == AgentType.OWNER:
            if not state.has_completed_planning or state.worker_count == 0:
                return Priority.OWNER_PLANNING
            return Priority.OWNER_WAITING_WORKERS
        elif state.agent_type in (AgentType.WORKER, AgentType.SUB):
            if state.is_waiting_for_tool:
                return Priority.WORKER_WAITING_TOOL
            return Priority.WORKER_RUNNING
        return Priority.IDLE

    async def _try_allocate(self, request: SlotAllocation) -> bool:
        """Try to allocate a slot for a request.

        Args:
            request: The allocation request.

        Returns:
            True if allocated, False otherwise.
        """
        async with self._allocation_lock:
            # Check if already has slot
            if request.agent_id in self._allocations:
                existing = self._allocations[request.agent_id]
                if not existing.is_released:
                    # Update heartbeat
                    existing.last_heartbeat = datetime.utcnow()
                    return True

            # Check provider total capacity
            provider = request.provider_name
            if provider not in self._provider_total_max:
                provider = "default"

            total_max = self._provider_total_max.get(provider, 10)

            # Count current allocations for this provider
            provider_allocations = [
                s for s in self._allocations.values()
                if s.provider_name == provider and not s.is_released
            ]

            if len(provider_allocations) >= total_max:
                # Try to reclaim a lower priority slot
                # Handle None priority by using a very low default (0 or lower than any valid priority)
                lowest_priority_slot = min(
                    provider_allocations,
                    key=lambda s: s.priority if s.priority is not None else -1,
                    default=None
                )

                if lowest_priority_slot and (lowest_priority_slot.priority or 0) < request.priority:
                    await self._release_slot(lowest_priority_slot)
                else:
                    return False  # No capacity

            # Check model capacity
            model = request.model_name
            model_max = self._provider_max_parallel.get(provider, {}).get(model, total_max)

            model_allocations = [
                s for s in provider_allocations
                if s.model_name == model
            ]

            if len(model_allocations) >= model_max:
                # Try to reclaim a lower priority slot
                # Handle None priority by using a very low default (0 or lower than any valid priority)
                lowest_priority_slot = min(
                    model_allocations,
                    key=lambda s: s.priority if s.priority is not None else -1,
                    default=None
                )

                if lowest_priority_slot and (lowest_priority_slot.priority or 0) < request.priority:
                    await self._release_slot(lowest_priority_slot)
                else:
                    return False  # No capacity

            # Calculate slot index
            existing_indices = [s.slot_index for s in provider_allocations]
            slot_index = 0
            while slot_index in existing_indices:
                slot_index += 1

            # Create new allocation (task_id will be validated by DB FK, use None if invalid)
            new_slot = ModelSlot(
                id=str(uuid4()),
                agent_id=request.agent_id,
                provider_name=provider,
                model_name=model,
                priority=request.priority,
                priority_reason=request.priority_reason,
                operation_type=request.operation_type,
                task_id=request.task_id,  # DB will reject if FK invalid
                subtask_id=request.subtask_id,
                slot_index=slot_index,
                allocated_at=datetime.utcnow(),
                last_heartbeat=datetime.utcnow(),
                is_active=True,
            )

            # Persist to database
            async with db_manager.session() as session:
                session.add(new_slot)
                try:
                    await session.commit()
                except Exception as e:
                    logger.warning(f"Failed to persist slot to DB (FK issue?): {e}")
                    await session.rollback()
                    # Fallback: create slot without task_id
                    new_slot.task_id = None
                    session.add(new_slot)
                    await session.commit()

            # Add to memory
            self._allocations[request.agent_id] = new_slot
            logger.info(f"Allocated slot {new_slot} to agent {request.agent_id} (priority={request.priority})")

            return True

    async def _release_slot(self, slot: ModelSlot) -> None:
        """Release a slot allocation.

        Args:
            slot: The slot to release.
        """
        slot.is_released = True
        slot.released_at = datetime.utcnow()

        async with db_manager.session() as session:
            await session.execute(
                update(ModelSlot)
                .where(ModelSlot.id == slot.id)
                .values(is_released=True, released_at=datetime.utcnow())
            )
            await session.commit()

        # Remove from memory
        agent_id = slot.agent_id
        if agent_id in self._allocations and self._allocations[agent_id].id == slot.id:
            del self._allocations[agent_id]

        logger.info(f"Released slot {slot.id} from agent {agent_id}")

    async def _release_all_slots(self) -> None:
        """Release all slot allocations."""
        async with db_manager.session() as session:
            await session.execute(
                update(ModelSlot)
                .where(ModelSlot.is_released == False)
                .values(is_released=True, released_at=datetime.utcnow())
            )
            await session.commit()

        self._allocations.clear()

    async def _update_agent_model_assignments(self) -> None:
        """Update agent's model_assignment to reflect current slot allocation."""
        async with db_manager.session() as session:
            # Get all active agent IDs that currently have slots
            active_agent_ids = set()
            for agent_id, slot in self._allocations.items():
                if slot.is_released:
                    continue
                active_agent_ids.add(agent_id)

                try:
                    result = await session.execute(
                        select(Agent).where(Agent.id == agent_id)
                    )
                    agent = result.scalar_one_or_none()

                    if agent:
                        # Update model_assignment to reflect current allocation
                        model_assignment = {
                            "provider": slot.provider_name,
                            "model": slot.model_name,
                            "slot_id": slot.id,
                            "slot_index": slot.slot_index,
                        }
                        agent.model_assignment = model_assignment

                except Exception as e:
                    logger.warning(f"Failed to update model_assignment for agent {agent_id}: {e}")

            # Clear model_assignment for agents that no longer have slots
            # Only check agents that have some model_assignment set
            logger.info(f"[_update_agent_model_assignments] Checking {len(active_agent_ids)} active agents for clearing stale assignments")
            result = await session.execute(
                select(Agent).where(Agent.model_assignment.isnot(None))
            )
            agents_with_assignment = result.scalars().all()
            logger.info(f"[_update_agent_model_assignments] Found {len(agents_with_assignment)} agents with model_assignment to check")

            for agent in agents_with_assignment:
                if agent.id not in active_agent_ids:
                    # This agent no longer has an active slot, clear its model_assignment
                    # Use raw SQL to ensure we set SQL NULL not JSON null
                    await session.execute(
                        update(Agent)
                        .where(Agent.id == agent.id)
                        .values(model_assignment=None)
                    )
                    logger.info(f"Cleared model_assignment for agent {agent.id} (status={agent.status})")

            await session.commit()

    async def request_slot(
        self,
        agent_id: str,
        provider_name: str,
        model_name: str,
        priority: int,
        priority_reason: str,
        operation_type: str,
        task_id: str | None = None,
        subtask_id: str | None = None,
    ) -> str | None:
        """Request a model slot for an agent.

        This is called by agents when they need to make an LLM call.

        Args:
            agent_id: The agent requesting the slot.
            provider_name: The provider name.
            model_name: The model name.
            priority: Priority level (higher = more urgent).
            priority_reason: Human-readable reason for priority.
            operation_type: Type of operation (e.g., "llm_call", "planning").
            task_id: Associated task ID.
            subtask_id: Associated subtask ID.

        Returns:
            Slot ID if allocated, None if no capacity available.
        """
        request = SlotAllocation(
            agent_id=agent_id,
            provider_name=provider_name,
            model_name=model_name,
            priority=priority,
            priority_reason=priority_reason,
            operation_type=operation_type,
            task_id=task_id,
            subtask_id=subtask_id,
        )

        if await self._try_allocate(request):
            if agent_id in self._allocations:
                return self._allocations[agent_id].id

        return None

    async def release_slot(self, agent_id: str) -> None:
        """Release a slot for an agent.

        Args:
            agent_id: The agent releasing the slot.
        """
        async with self._allocation_lock:
            if agent_id in self._allocations:
                slot = self._allocations[agent_id]
                await self._release_slot(slot)

    async def heartbeat(self, agent_id: str) -> None:
        """Send a heartbeat for a slot allocation.

        Args:
            agent_id: The agent sending heartbeat.
        """
        async with self._allocation_lock:
            if agent_id in self._allocations:
                slot = self._allocations[agent_id]
                slot.last_heartbeat = datetime.utcnow()

                async with db_manager.session() as session:
                    await session.execute(
                        update(ModelSlot)
                        .where(ModelSlot.id == slot.id)
                        .values(last_heartbeat=datetime.utcnow())
                    )
                    await session.commit()

    async def get_allocation_status(self) -> dict[str, Any]:
        """Get current allocation status for monitoring.

        Returns:
            Dictionary with allocation status.
        """
        async with self._allocation_lock:
            active_slots = [s for s in self._allocations.values() if not s.is_released]

            # Group by provider
            by_provider: dict[str, list[dict[str, Any]]] = {}
            for slot in active_slots:
                provider = slot.provider_name
                if provider not in by_provider:
                    by_provider[provider] = []
                by_provider[provider].append({
                    "slot_id": slot.id,
                    "agent_id": slot.agent_id,
                    "model": slot.model_name,
                    "slot_index": slot.slot_index,
                    "priority": slot.priority,
                    "operation": slot.operation_type,
                })

            return {
                "total_active": len(active_slots),
                "by_provider": by_provider,
                "allocations": [s.to_dict() for s in active_slots],
                "provider_config": {
                    "total_max": self._provider_total_max,
                    "model_max": self._provider_max_parallel,
                },
            }

    def get_model_max_parallel(self, provider: str, model: str) -> int:
        """Get max parallel requests for a provider+model.

        Args:
            provider: Provider name.
            model: Model name.

        Returns:
            Max parallel requests allowed.
        """
        return self._provider_max_parallel.get(provider, {}).get(model, 10)

    async def get_agent_allocation(self, agent_id: str) -> dict[str, Any] | None:
        """Get allocation for a specific agent.

        Args:
            agent_id: The agent ID.

        Returns:
            Allocation info or None.
        """
        async with self._allocation_lock:
            if agent_id in self._allocations:
                slot = self._allocations[agent_id]
                if not slot.is_released:
                    return slot.to_dict()
            return None

    async def get_all_allocations(self) -> list[dict[str, Any]]:
        """Get all current slot allocations for display.

        Returns:
            List of allocation dictionaries with agent info.
        """
        async with self._allocation_lock:
            allocations = []
            for slot in self._allocations.values():
                if slot.is_released:
                    continue

                # Get agent info from database
                async with db_manager.session() as session:
                    result = await session.execute(
                        select(Agent).where(Agent.id == slot.agent_id)
                    )
                    agent = result.scalar_one_or_none()

                allocations.append({
                    "slot_id": slot.id,
                    "agent_id": slot.agent_id,
                    "agent_name": agent.name if agent else "Unknown",
                    "agent_type": agent.agent_type.value if agent else "Unknown",
                    "provider": slot.provider_name,
                    "model": slot.model_name,
                    "slot_index": slot.slot_index,
                    "priority": slot.priority,
                    "priority_reason": slot.priority_reason,
                    "operation_type": slot.operation_type,
                    "allocated_at": slot.allocated_at.isoformat() if slot.allocated_at else None,
                })

            return allocations

    def get_allocated_agent_count(self, provider_name: str | None = None) -> int:
        """Get count of currently allocated agents.

        Args:
            provider_name: Optional provider to filter by.

        Returns:
            Number of allocated agents.
        """
        if provider_name:
            return len([
                s for s in self._allocations.values()
                if not s.is_released and s.provider_name == provider_name
            ])
        return len([s for s in self._allocations.values() if not s.is_released])


# Global provider scheduler service instance
provider_scheduler_service = ProviderSchedulerService()