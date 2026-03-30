"""
Console API for LongClaw.
Provides administrative view and intervention capabilities.
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus, AgentType
from backend.models.channel import Channel
from backend.models.message import Message, SenderType, ReceiverType
from backend.models.task import Task, TaskStatus
from backend.services.agent_service import agent_service
from backend.services.message_service import message_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Schemas ====================


class AgentSummary(BaseModel):
    """Schema for agent summary."""

    id: str
    name: str
    agent_type: str
    status: str
    task_id: str | None
    parent_agent_id: str | None
    created_at: datetime
    updated_at: datetime | None


class ChannelSummary(BaseModel):
    """Schema for channel summary."""

    id: str
    channel_type: str
    resident_agent_id: str | None
    target_agent_id: str | None
    is_active: bool


class TaskSummary(BaseModel):
    """Schema for task summary."""

    id: str
    title: str
    status: str
    owner_agent_id: str | None
    created_at: datetime


class MessageSummary(BaseModel):
    """Schema for message summary."""

    id: str
    sender_type: str
    sender_id: str | None
    receiver_type: str
    receiver_id: str | None
    content: str
    created_at: datetime


class InterventionRequest(BaseModel):
    """Schema for intervention request."""

    message: str
    target_type: str  # "agent" or "channel"
    target_id: str


class ConsoleOverview(BaseModel):
    """Schema for console overview."""

    total_agents: int
    running_agents: int
    total_channels: int
    active_channels: int
    total_tasks: int
    running_tasks: int
    recent_messages: int


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency."""
    async with db_manager.session() as session:
        yield session


# ==================== Endpoints ====================


@router.get("/overview", response_model=ConsoleOverview)
async def get_console_overview(
    session: AsyncSession = Depends(get_session),
) -> ConsoleOverview:
    """Get console overview statistics.

    Args:
        session: Database session.

    Returns:
        Overview statistics.
    """
    # Count agents
    agents_result = await session.execute(select(Agent))
    all_agents = list(agents_result.scalars().all())
    running_agents = [a for a in all_agents if a.status == AgentStatus.RUNNING]

    # Count channels
    channels_result = await session.execute(select(Channel))
    all_channels = list(channels_result.scalars().all())
    active_channels = [c for c in all_channels if c.is_active]

    # Count tasks
    tasks_result = await session.execute(select(Task))
    all_tasks = list(tasks_result.scalars().all())
    running_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]

    # Count recent messages (last hour)
    from datetime import timedelta
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    messages_result = await session.execute(
        select(Message).where(Message.created_at >= one_hour_ago)
    )
    recent_messages = len(list(messages_result.scalars().all()))

    return ConsoleOverview(
        total_agents=len(all_agents),
        running_agents=len(running_agents),
        total_channels=len(all_channels),
        active_channels=len(active_channels),
        total_tasks=len(all_tasks),
        running_tasks=len(running_tasks),
        recent_messages=recent_messages,
    )


@router.get("/agents", response_model=list[AgentSummary])
async def list_all_agents(
    status: AgentStatus | None = Query(None),
    agent_type: AgentType | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[AgentSummary]:
    """List all agents with optional filtering.

    Args:
        status: Optional status filter.
        agent_type: Optional type filter.
        limit: Maximum results.
        session: Database session.

    Returns:
        List of agents.
    """
    stmt = select(Agent)

    if status:
        stmt = stmt.where(Agent.status == status)
    if agent_type:
        stmt = stmt.where(Agent.agent_type == agent_type)

    stmt = stmt.order_by(desc(Agent.updated_at)).limit(limit)
    result = await session.execute(stmt)
    agents = list(result.scalars().all())

    return [
        AgentSummary(
            id=a.id,
            name=a.name,
            agent_type=a.agent_type.value,
            status=a.status.value,
            task_id=a.task_id,
            parent_agent_id=a.parent_agent_id,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in agents
    ]


@router.get("/channels", response_model=list[ChannelSummary])
async def list_all_channels(
    session: AsyncSession = Depends(get_session),
) -> list[ChannelSummary]:
    """List all channels.

    Args:
        session: Database session.

    Returns:
        List of channels.
    """
    result = await session.execute(select(Channel))
    channels = list(result.scalars().all())

    return [
        ChannelSummary(
            id=c.id,
            channel_type=c.channel_type.value,
            resident_agent_id=c.resident_agent_id,
            target_agent_id=c.target_agent_id,
            is_active=c.is_active,
        )
        for c in channels
    ]


@router.get("/tasks", response_model=list[TaskSummary])
async def list_all_tasks(
    status: TaskStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
) -> list[TaskSummary]:
    """List all tasks with optional filtering.

    Args:
        status: Optional status filter.
        limit: Maximum results.
        session: Database session.

    Returns:
        List of tasks.
    """
    stmt = select(Task)

    if status:
        stmt = stmt.where(Task.status == status)

    stmt = stmt.order_by(desc(Task.updated_at)).limit(limit)
    result = await session.execute(stmt)
    tasks = list(result.scalars().all())

    return [
        TaskSummary(
            id=t.id,
            title=t.title,
            status=t.status.value,
            owner_agent_id=t.owner_agent_id,
            created_at=t.created_at,
        )
        for t in tasks
    ]


@router.get("/messages", response_model=list[MessageSummary])
async def list_all_messages(
    agent_id: str | None = Query(None, description="Filter by agent (sender or receiver)"),
    channel_id: str | None = Query(None, description="Filter by channel"),
    limit: int = Query(100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[MessageSummary]:
    """List messages with optional filtering.

    Args:
        agent_id: Filter by agent ID (sender or receiver).
        channel_id: Filter by channel ID.
        limit: Maximum results.
        session: Database session.

    Returns:
        List of messages.
    """
    stmt = select(Message)

    if agent_id:
        stmt = stmt.where(
            or_(
                Message.sender_id == agent_id,
                Message.receiver_id == agent_id,
            )
        )

    if channel_id:
        stmt = stmt.where(
            or_(
                Message.sender_id == channel_id,
                Message.receiver_id == channel_id,
            )
        )

    stmt = stmt.order_by(desc(Message.created_at)).limit(limit)
    result = await session.execute(stmt)
    messages = list(result.scalars().all())

    return [
        MessageSummary(
            id=m.id,
            sender_type=m.sender_type.value,
            sender_id=m.sender_id,
            receiver_type=m.receiver_type.value,
            receiver_id=m.receiver_id,
            content=m.content[:500] if m.content else "",
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("/intervene")
async def send_intervention(
    data: InterventionRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Send an intervention message to an agent or channel.

    This allows administrators to send messages directly to agents
    for debugging, guidance, or intervention.

    Args:
        data: Intervention request data.
        session: Database session.

    Returns:
        Result including message ID.
    """
    from uuid import uuid4

    # Validate target exists
    if data.target_type == "agent":
        result = await session.execute(
            select(Agent).where(Agent.id == data.target_id)
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="Agent not found")

        receiver_type = ReceiverType.AGENT
    elif data.target_type == "channel":
        result = await session.execute(
            select(Channel).where(Channel.id == data.target_id)
        )
        target = result.scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="Channel not found")

        receiver_type = ReceiverType.CHANNEL
    else:
        raise HTTPException(status_code=400, detail="Invalid target_type. Use 'agent' or 'channel'.")

    # Create intervention message
    message = await message_service.create_message(
        session,
        sender_type=SenderType.SYSTEM,
        sender_id="console",
        receiver_type=receiver_type,
        receiver_id=data.target_id,
        content=f"[系统干预] {data.message}",
    )

    # Publish message
    await message_service.publish_message(message)

    logger.info(f"Sent intervention to {data.target_type} {data.target_id}: {data.message[:50]}...")

    return {
        "status": "sent",
        "message_id": message.id,
        "target_type": data.target_type,
        "target_id": data.target_id,
    }


@router.get("/agent/{agent_id}/knowledge")
async def get_agent_knowledge(
    agent_id: str,
    limit: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get knowledge for an agent.

    Args:
        agent_id: Agent ID.
        limit: Maximum results.
        session: Database session.

    Returns:
        List of knowledge items.
    """
    from backend.services.retrieval_service import retrieval_service

    knowledge = await retrieval_service.get_agent_knowledge(agent_id, limit)
    return knowledge


@router.get("/agent/{agent_id}/work-summary")
async def get_agent_work_summary(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Get work summary for an agent.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Work summary.
    """
    from backend.services.reflect_service import reflect_service

    # Get reflect check for this agent
    analyses = await reflect_agent.check_all_agents()
    analysis = next((a for a in analyses if a.agent_id == agent_id), None)

    return {
        "agent_id": agent_id,
        "analysis": {
            "needs_intervention": analysis.needs_intervention if analysis else False,
            "is_stuck": analysis.is_truly_stuck if analysis else False,
            "reason": analysis.reason if analysis else None,
        } if analysis else None,
    }


# Import reflect_agent for the work summary
from backend.agents.reflect_agent import reflect_agent
