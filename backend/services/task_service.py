"""
Task Service for LongClaw.
Manages tasks and subtasks.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.subtask import Subtask, SubtaskStatus
from backend.models.task import Task, TaskStatus

logger = logging.getLogger(__name__)


class TaskService:
    """Service for managing tasks and subtasks."""

    # ==================== Task Operations ====================

    async def create_task(
        self,
        session: AsyncSession,
        title: str,
        description: str | None = None,
        channel_id: str | None = None,
        original_message: str | None = None,
        owner_agent_id: str | None = None,
    ) -> Task:
        """Create a new task.

        Args:
            session: Database session.
            title: Task title.
            description: Optional task description.
            channel_id: Optional channel ID.
            original_message: Optional original message that triggered the task.
            owner_agent_id: Optional owner agent ID.

        Returns:
            Created task.
        """
        task = Task(
            id=str(uuid4()),
            title=title,
            description=description,
            status=TaskStatus.PLANNING,
            channel_id=channel_id,
            original_message=original_message,
            owner_agent_id=owner_agent_id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(task)
        await session.flush()

        logger.info(f"Created task {task.id}: {title}")
        return task

    async def get_task(self, session: AsyncSession, task_id: str) -> Task | None:
        """Get a task by ID.

        Args:
            session: Database session.
            task_id: Task ID.

        Returns:
            Task if found, None otherwise.
        """
        result = await session.execute(
            select(Task).where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    async def get_tasks(
        self,
        session: AsyncSession,
        status: TaskStatus | None = None,
        channel_id: str | None = None,
        owner_agent_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """Get tasks with optional filtering.

        Args:
            session: Database session.
            status: Optional status filter.
            channel_id: Optional channel ID filter.
            owner_agent_id: Optional owner agent ID filter.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of tasks.
        """
        query = select(Task)

        if status:
            query = query.where(Task.status == status)
        if channel_id:
            query = query.where(Task.channel_id == channel_id)
        if owner_agent_id:
            query = query.where(Task.owner_agent_id == owner_agent_id)

        query = query.order_by(Task.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_status(
        self,
        session: AsyncSession,
        task_id: str,
        status: TaskStatus,
    ) -> Task | None:
        """Update a task's status.

        Args:
            session: Database session.
            task_id: Task ID.
            status: New status.

        Returns:
            Updated task if found, None otherwise.
        """
        task = await self.get_task(session, task_id)
        if not task:
            return None

        task.status = status
        task.updated_at = datetime.utcnow()

        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.utcnow()
        elif status == TaskStatus.TERMINATED:
            task.terminated_at = datetime.utcnow()

        await session.flush()
        logger.info(f"Updated task {task_id} status to {status.value}")
        return task

    async def update_task(
        self,
        session: AsyncSession,
        task_id: str,
        **kwargs: Any,
    ) -> Task | None:
        """Update a task's attributes.

        Args:
            session: Database session.
            task_id: Task ID.
            **kwargs: Attributes to update.

        Returns:
            Updated task if found, None otherwise.
        """
        task = await self.get_task(session, task_id)
        if not task:
            return None

        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)

        task.updated_at = datetime.utcnow()
        await session.flush()
        logger.debug(f"Updated task {task_id}: {list(kwargs.keys())}")
        return task

    async def set_plan(
        self,
        session: AsyncSession,
        task_id: str,
        plan: dict[str, Any],
    ) -> Task | None:
        """Set the task plan.

        Args:
            session: Database session.
            task_id: Task ID.
            plan: Plan data.

        Returns:
            Updated task if found, None otherwise.
        """
        return await self.update_task(session, task_id, plan=plan)

    async def set_summary(
        self,
        session: AsyncSession,
        task_id: str,
        summary: str,
    ) -> Task | None:
        """Set the task summary.

        Args:
            session: Database session.
            task_id: Task ID.
            summary: Summary text.

        Returns:
            Updated task if found, None otherwise.
        """
        return await self.update_task(session, task_id, summary=summary)

    async def terminate_task(self, session: AsyncSession, task_id: str) -> Task | None:
        """Terminate a task.

        Args:
            session: Database session.
            task_id: Task ID.

        Returns:
            Terminated task if found, None otherwise.
        """
        return await self.update_status(session, task_id, TaskStatus.TERMINATED)

    # ==================== Subtask Operations ====================

    async def create_subtask(
        self,
        session: AsyncSession,
        task_id: str,
        title: str,
        description: str | None = None,
        parent_subtask_id: str | None = None,
        order_index: int | None = None,
        priority: int = 0,
        depends_on: list[str] | None = None,
    ) -> Subtask:
        """Create a new subtask.

        Args:
            session: Database session.
            task_id: Parent task ID.
            title: Subtask title.
            description: Optional subtask description.
            parent_subtask_id: Optional parent subtask ID for nesting.
            order_index: Optional order index.
            priority: Priority (higher = more important).
            depends_on: List of subtask spec IDs this task depends on.

        Returns:
            Created subtask.
        """
        subtask = Subtask(
            id=str(uuid4()),
            task_id=task_id,
            parent_subtask_id=parent_subtask_id,
            title=title,
            description=description,
            status=SubtaskStatus.PENDING,
            order_index=order_index,
            priority=priority,
            depends_on=depends_on,
            created_at=datetime.utcnow(),
        )
        session.add(subtask)
        await session.flush()

        logger.debug(f"Created subtask {subtask.id} for task {task_id}: {title}")
        return subtask

    async def get_subtask(
        self, session: AsyncSession, subtask_id: str
    ) -> Subtask | None:
        """Get a subtask by ID.

        Args:
            session: Database session.
            subtask_id: Subtask ID.

        Returns:
            Subtask if found, None otherwise.
        """
        result = await session.execute(
            select(Subtask).where(Subtask.id == subtask_id)
        )
        return result.scalar_one_or_none()

    async def get_task_subtasks(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> list[Subtask]:
        """Get all subtasks for a task.

        Args:
            session: Database session.
            task_id: Task ID.

        Returns:
            List of subtasks ordered by order_index.
        """
        # Execute a fresh query to get the latest data from database
        # Using execution_options for fresh data instead of expire_all
        # which can cause issues with async lazy loading
        result = await session.execute(
            select(Subtask)
            .where(Subtask.task_id == task_id)
            .order_by(Subtask.order_index)
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def update_subtask_status(
        self,
        session: AsyncSession,
        subtask_id: str,
        status: SubtaskStatus,
        summary: str | None = None,
        result: dict[str, Any] | None = None,
    ) -> Subtask | None:
        """Update a subtask's status.

        Args:
            session: Database session.
            subtask_id: Subtask ID.
            status: New status.
            summary: Optional summary.
            result: Optional result data.

        Returns:
            Updated subtask if found, None otherwise.
        """
        subtask = await self.get_subtask(session, subtask_id)
        if not subtask:
            return None

        subtask.status = status

        if summary:
            subtask.summary = summary
        if result:
            subtask.result = result
        if status == SubtaskStatus.COMPLETED:
            subtask.completed_at = datetime.utcnow()

        await session.flush()
        logger.debug(f"Updated subtask {subtask_id} status to {status.value}")
        return subtask

    async def touch_subtask(
        self,
        session: AsyncSession,
        subtask_id: str,
    ) -> bool:
        """Update subtask's updated_at timestamp to signal it's still active.

        This is used to prevent the scheduler from marking a subtask as stalled
        when the worker is actively processing.

        Args:
            session: Database session.
            subtask_id: Subtask ID.

        Returns:
            True if subtask was found and updated, False otherwise.
        """
        subtask = await self.get_subtask(session, subtask_id)
        if not subtask:
            return False

        subtask.updated_at = datetime.utcnow()
        await session.flush()
        return True

    async def assign_worker(
        self,
        session: AsyncSession,
        subtask_id: str,
        worker_agent_id: str,
    ) -> Subtask | None:
        """Assign a worker agent to a subtask.

        Args:
            session: Database session.
            subtask_id: Subtask ID.
            worker_agent_id: Worker agent ID.

        Returns:
            Updated subtask if found, None otherwise.
        """
        subtask = await self.get_subtask(session, subtask_id)
        if not subtask:
            return None

        subtask.worker_agent_id = worker_agent_id
        await session.flush()
        logger.debug(f"Assigned worker {worker_agent_id} to subtask {subtask_id}")
        return subtask

    async def count_tasks(
        self,
        session: AsyncSession,
        status: TaskStatus | None = None,
    ) -> int:
        """Count tasks with optional filtering.

        Args:
            session: Database session.
            status: Optional status filter.

        Returns:
            Count of tasks.
        """
        from sqlalchemy import func

        query = select(func.count(Task.id))

        if status:
            query = query.where(Task.status == status)

        result = await session.execute(query)
        return result.scalar_one()

    async def get_subtask_stats(
        self,
        session: AsyncSession,
        task_id: str,
    ) -> dict[str, int]:
        """Get subtask statistics for a task.

        Args:
            session: Database session.
            task_id: Task ID.

        Returns:
            Dictionary with total, completed, running, failed, pending counts.
        """
        from sqlalchemy import func, case

        result = await session.execute(
            select(
                func.count(Subtask.id).label('total'),
                func.sum(case((Subtask.status == SubtaskStatus.COMPLETED, 1), else_=0)).label('completed'),
                func.sum(case((Subtask.status == SubtaskStatus.RUNNING, 1), else_=0)).label('running'),
                func.sum(case((Subtask.status == SubtaskStatus.FAILED, 1), else_=0)).label('failed'),
                func.sum(case((Subtask.status == SubtaskStatus.PENDING, 1), else_=0)).label('pending'),
            ).where(Subtask.task_id == task_id)
        )
        row = result.one()
        return {
            'total': row.total or 0,
            'completed': row.completed or 0,
            'running': row.running or 0,
            'failed': row.failed or 0,
            'pending': row.pending or 0,
        }


# Global task service instance
task_service = TaskService()
