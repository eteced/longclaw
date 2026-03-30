"""
Scheduler Service for LongClaw.
Handles periodic tasks and message dispatch.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus
from backend.models.task import Task, TaskStatus
from backend.services.config_service import config_service
from backend.services.message_service import message_service

logger = logging.getLogger(__name__)

# Global reflect service (lazy import to avoid circular dependency)
_reflect_service = None


async def get_reflect_service():
    """Get the reflect service instance.

    Returns:
        Reflect service instance.
    """
    global _reflect_service
    if _reflect_service is None:
        from backend.services.reflect_service import reflect_service
        _reflect_service = reflect_service
    return _reflect_service


class SchedulerService:
    """Service for scheduling and running periodic tasks."""

    def __init__(self) -> None:
        """Initialize the scheduler service."""
        self._running: bool = False
        self._tasks: list[asyncio.Task[Any]] = []
        self._tick_handlers: list[Callable[[], Any]] = []
        self._agent_timeout_seconds: int | None = None  # Loaded from config
        self._check_interval_seconds: int | None = None  # Loaded from config
        self._task_execution_lock: asyncio.Lock = asyncio.Lock()

    def register_tick_handler(self, handler: Callable[[], Any]) -> None:
        """Register a handler to be called on each tick.

        Args:
            handler: Async function to call on each tick.
        """
        self._tick_handlers.append(handler)

    async def start(self) -> None:
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler is already running")
            return

        self._running = True
        self._tasks.append(asyncio.create_task(self._run_loop()))
        logger.info("Scheduler service started")

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        logger.info("Scheduler service stopped")

    async def _run_loop(self) -> None:
        """Main scheduler loop."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.exception(f"Error in scheduler tick: {e}")

            # Get check interval from config (default 10 seconds to reduce DB load)
            if self._check_interval_seconds is None:
                self._check_interval_seconds = await config_service.get_int("scheduler_check_interval", 10)

            await asyncio.sleep(self._check_interval_seconds)

    async def _tick(self) -> None:
        """Execute one tick of the scheduler."""
        # Initialize tick counter
        if not hasattr(self, '_tick_count'):
            self._tick_count = 0
        self._tick_count += 1

        # Run registered handlers
        for handler in self._tick_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler()
                else:
                    handler()
            except Exception as e:
                logger.exception(f"Error in tick handler: {e}")

        # Check for new tasks to execute (every tick - this is important)
        await self._check_pending_tasks()

        # Check agent health (every 6 ticks = ~60 seconds with default interval)
        if self._tick_count % 6 == 0:
            await self._check_agent_health()

        # Check task status (every 6 ticks = ~60 seconds)
        if self._tick_count % 6 == 0:
            await self._check_task_status()

        # Run reflect check (every 30 ticks = ~5 minutes with default interval)
        if self._tick_count % 30 == 0:
            await self._run_reflect_check()

    async def _check_agent_health(self) -> None:
        """Check health of running agents.

        This method checks if agents have been active recently. If an agent
        hasn't updated its timestamp within the timeout period, it's marked as ERROR.

        Note: Resident Agents should call _touch() periodically during long operations
        (via _heartbeat_during_execution) to prevent being marked as stale.
        """
        # Get agent timeout from config
        # Note: get_int returns None when config value is -1 (disabled)
        if self._agent_timeout_seconds is None:
            self._agent_timeout_seconds = await config_service.get_int("scheduler_agent_timeout", 300)

        # If timeout is None (disabled), skip health check
        if self._agent_timeout_seconds is None:
            return

        async with db_manager.session() as session:
            from sqlalchemy import select, and_

            # Find agents that are running but haven't been updated recently
            timeout_threshold = datetime.utcnow() - timedelta(
                seconds=self._agent_timeout_seconds
            )

            result = await session.execute(
                select(Agent).where(
                    and_(
                        Agent.status == AgentStatus.RUNNING,
                        Agent.updated_at < timeout_threshold,
                    )
                )
            )
            stale_agents = list(result.scalars().all())

            for agent in stale_agents:
                logger.warning(
                    f"Agent {agent.id} ({agent.name}, type={agent.agent_type.value}) has not updated recently, "
                    f"marking as error"
                )
                agent.status = AgentStatus.ERROR
                agent.updated_at = datetime.utcnow()

                # Publish update
                await message_service.publish_agent_update(
                    agent.id, AgentStatus.ERROR.value, agent.task_id
                )

    async def _check_task_status(self) -> None:
        """Check status of tasks and update as needed."""
        async with db_manager.session() as session:
            from sqlalchemy import select

            # Find tasks that are running but have no active agents
            result = await session.execute(
                select(Task).where(Task.status == TaskStatus.RUNNING)
            )
            running_tasks = list(result.scalars().all())

            for task in running_tasks:
                # Check if owner agent is still active
                if task.owner_agent_id:
                    agent_result = await session.execute(
                        select(Agent).where(Agent.id == task.owner_agent_id)
                    )
                    owner = agent_result.scalar_one_or_none()

                    if not owner or owner.status in (
                        AgentStatus.TERMINATED,
                        AgentStatus.ERROR,
                    ):
                        logger.warning(
                            f"Task {task.id} has no active owner agent, "
                            f"marking as error"
                        )
                        task.status = TaskStatus.ERROR
                        task.updated_at = datetime.utcnow()

                        await message_service.publish_task_update(
                            task.id, TaskStatus.ERROR.value
                        )

    async def _run_reflect_check(self) -> None:
        """Run reflect check on all agents.

        This uses the reflect service to intelligently monitor agent health
        and send interventions when needed.
        """
        try:
            rs = await get_reflect_service()
            if rs and hasattr(rs, 'manual_check'):
                result = await rs.manual_check()
                if result.get("interventions"):
                    logger.info(f"Reflect check result: {result}")
        except Exception as e:
            logger.warning(f"Reflect check failed: {e}")

    async def _check_pending_tasks(self) -> None:
        """Check for pending tasks and execute them."""
        # Use lock to prevent concurrent execution
        if self._task_execution_lock.locked():
            return

        async with self._task_execution_lock:
            async with db_manager.session() as session:
                from sqlalchemy import select

                # Find tasks in PLANNING status that haven't been picked up
                # Double-check both status AND owner_agent_id to prevent race conditions
                result = await session.execute(
                    select(Task)
                    .where(Task.status == TaskStatus.PLANNING)
                    .where(Task.owner_agent_id.is_(None))
                    .limit(1)
                )
                pending_task = result.scalar_one_or_none()

                if pending_task and pending_task.original_message:
                    # Execute this task in background
                    logger.info(f"Scheduler picking up pending task {pending_task.id}")
                    asyncio.create_task(self._execute_task(pending_task.id))

    async def _execute_task(self, task_id: str) -> None:
        """Execute a task using OwnerAgent.

        Args:
            task_id: Task ID to execute.
        """
        from backend.agents.owner_agent import OwnerAgent
        from backend.services.task_service import task_service

        try:
            async with db_manager.session() as session:
                task = await task_service.get_task(session, task_id)
                if not task or task.status != TaskStatus.PLANNING:
                    return

                # Update task status to RUNNING
                await task_service.update_status(session, task_id, TaskStatus.RUNNING)

                # Get the original message as the task description
                user_request = task.original_message or task.title

            logger.info(f"Executing task {task_id}: {user_request[:100]}...")

            # Create and run OwnerAgent
            owner = OwnerAgent(
                task_id=task_id,
                timeout=None,  # Use config default
                max_subagents=5,
            )

            result = await owner.execute(user_request)
            await owner.terminate()

            # Update task with result
            async with db_manager.session() as session:
                await task_service.update_task(
                    session, task_id, summary=result, status=TaskStatus.COMPLETED
                )

            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            logger.exception(f"Error executing task {task_id}: {e}")
            async with db_manager.session() as session:
                await task_service.update_status(session, task_id, TaskStatus.ERROR)


# Global scheduler service instance
scheduler_service = SchedulerService()
