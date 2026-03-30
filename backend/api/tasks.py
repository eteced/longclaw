"""
Tasks API for LongClaw.
"""
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.subtask import SubtaskStatus
from backend.models.task import Task, TaskStatus
from backend.services.task_service import task_service

router = APIRouter()


# ==================== Schemas ====================


class TaskCreate(BaseModel):
    """Schema for creating a task."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    channel_id: str | None = None
    original_message: str | None = None


class TaskUpdate(BaseModel):
    """Schema for updating a task."""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus | None = None
    plan: dict[str, Any] | None = None
    summary: str | None = None


class SubtaskStats(BaseModel):
    """Schema for subtask statistics."""

    total: int = 0
    completed: int = 0
    running: int = 0
    failed: int = 0
    pending: int = 0


class TaskResponse(BaseModel):
    """Schema for task response."""

    id: str
    title: str
    description: str | None
    status: TaskStatus
    owner_agent_id: str | None
    channel_id: str | None
    original_message: str | None
    plan: dict[str, Any] | None
    summary: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    terminated_at: datetime | None
    subtask_stats: SubtaskStats = SubtaskStats()

    class Config:
        from_attributes = True


class SubtaskResponse(BaseModel):
    """Schema for subtask response."""

    id: str
    task_id: str
    parent_subtask_id: str | None
    title: str
    description: str | None
    status: SubtaskStatus
    worker_agent_id: str | None
    summary: str | None
    result: dict[str, Any] | None
    order_index: int | None
    priority: int = 0
    depends_on: list[str] | None = None
    created_at: datetime
    completed_at: datetime | None

    class Config:
        from_attributes = True


class TaskDetailResponse(TaskResponse):
    """Schema for detailed task response with subtasks."""

    subtasks: list[SubtaskResponse] = []


class TaskListResponse(BaseModel):
    """Schema for task list response."""

    items: list[TaskResponse]
    total: int
    limit: int
    offset: int


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency.

    Yields:
        AsyncSession instance.
    """
    async with db_manager.session() as session:
        yield session


# ==================== Endpoints ====================


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: TaskStatus | None = Query(None, description="Filter by status"),
    channel_id: str | None = Query(None, description="Filter by channel ID"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> TaskListResponse:
    """List tasks with optional filtering.

    Args:
        status: Optional status filter.
        channel_id: Optional channel ID filter.
        limit: Maximum number of results.
        offset: Offset for pagination.
        session: Database session.

    Returns:
        List of tasks.
    """
    tasks = await task_service.get_tasks(
        session,
        status=status,
        channel_id=channel_id,
        limit=limit,
        offset=offset,
    )
    total = await task_service.count_tasks(session, status=status)

    # Build response with subtask stats
    items = []
    for t in tasks:
        stats = await task_service.get_subtask_stats(session, t.id)
        task_dict = {
            'id': t.id,
            'title': t.title,
            'description': t.description,
            'status': t.status,
            'owner_agent_id': t.owner_agent_id,
            'channel_id': t.channel_id,
            'original_message': t.original_message,
            'plan': t.plan,
            'summary': t.summary,
            'created_at': t.created_at,
            'updated_at': t.updated_at,
            'completed_at': t.completed_at,
            'terminated_at': t.terminated_at,
            'subtask_stats': SubtaskStats(**stats),
        }
        items.append(TaskResponse(**task_dict))

    return TaskListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> TaskDetailResponse:
    """Get a task by ID.

    Args:
        task_id: Task ID.
        session: Database session.

    Returns:
        Task details.

    Raises:
        HTTPException: If task not found.
    """
    task = await task_service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subtasks = await task_service.get_task_subtasks(session, task_id)
    stats = await task_service.get_subtask_stats(session, task_id)

    task_dict = {
        'id': task.id,
        'title': task.title,
        'description': task.description,
        'status': task.status,
        'owner_agent_id': task.owner_agent_id,
        'channel_id': task.channel_id,
        'original_message': task.original_message,
        'plan': task.plan,
        'summary': task.summary,
        'created_at': task.created_at,
        'updated_at': task.updated_at,
        'completed_at': task.completed_at,
        'terminated_at': task.terminated_at,
        'subtask_stats': SubtaskStats(**stats),
    }

    return TaskDetailResponse(
        **task_dict,
        subtasks=[SubtaskResponse.model_validate(s) for s in subtasks],
    )


@router.post("", response_model=TaskResponse, status_code=201)
async def create_task(
    data: TaskCreate,
    session: AsyncSession = Depends(get_session),
) -> Task:
    """Create a new task.

    Args:
        data: Task creation data.
        session: Database session.

    Returns:
        Created task.
    """
    task = await task_service.create_task(
        session,
        title=data.title,
        description=data.description,
        channel_id=data.channel_id,
        original_message=data.original_message,
    )
    return task


@router.patch("/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    data: TaskUpdate,
    session: AsyncSession = Depends(get_session),
) -> Task:
    """Update a task.

    Args:
        task_id: Task ID.
        data: Task update data.
        session: Database session.

    Returns:
        Updated task.

    Raises:
        HTTPException: If task not found.
    """
    task = await task_service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    update_data = data.model_dump(exclude_unset=True)
    task = await task_service.update_task(session, task_id, **update_data)

    return task  # type: ignore


@router.post("/{task_id}/terminate", response_model=TaskResponse)
async def terminate_task(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> Task:
    """Terminate a task.

    Args:
        task_id: Task ID.
        session: Database session.

    Returns:
        Terminated task.

    Raises:
        HTTPException: If task not found.
    """
    task = await task_service.terminate_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return task


@router.get("/{task_id}/subtasks", response_model=list[SubtaskResponse])
async def list_subtasks(
    task_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[SubtaskResponse]:
    """List subtasks for a task.

    Args:
        task_id: Task ID.
        session: Database session.

    Returns:
        List of subtasks.

    Raises:
        HTTPException: If task not found.
    """
    task = await task_service.get_task(session, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    subtasks = await task_service.get_task_subtasks(session, task_id)
    return [SubtaskResponse.model_validate(s) for s in subtasks]


@router.get("/subtasks/{subtask_id}", response_model=SubtaskResponse)
async def get_subtask(
    subtask_id: str,
    session: AsyncSession = Depends(get_session),
) -> SubtaskResponse:
    """Get a subtask by ID.

    Args:
        subtask_id: Subtask ID.
        session: Database session.

    Returns:
        Subtask details.

    Raises:
        HTTPException: If subtask not found.
    """
    subtask = await task_service.get_subtask(session, subtask_id)
    if not subtask:
        raise HTTPException(status_code=404, detail="Subtask not found")

    return SubtaskResponse.model_validate(subtask)
