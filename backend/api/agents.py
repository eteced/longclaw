"""
Agents API for LongClaw.
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus, AgentType
from backend.services.agent_service import agent_service
from backend.services.message_service import message_service

router = APIRouter()


# ==================== Schemas ====================


class AgentResponse(BaseModel):
    """Schema for agent response."""

    id: str
    agent_type: AgentType
    name: str
    personality: str | None
    status: AgentStatus
    error_message: str | None = None
    parent_agent_id: str | None
    task_id: str | None
    llm_config: dict[str, Any] | None = Field(None, alias="model_config")
    created_at: datetime
    updated_at: datetime
    terminated_at: datetime | None

    class Config:
        from_attributes = True
        populate_by_name = True


class AgentListResponse(BaseModel):
    """Schema for agent list response."""

    items: list[AgentResponse]
    total: int
    limit: int
    offset: int


class AgentSummaryResponse(BaseModel):
    """Schema for agent summary response."""

    agent_id: str
    summary: str


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency.

    Yields:
        AsyncSession instance.
    """
    async with db_manager.session() as session:
        yield session


# ==================== Endpoints ====================


@router.get("", response_model=AgentListResponse)
async def list_agents(
    agent_type: AgentType | None = Query(None, description="Filter by agent type"),
    status: AgentStatus | None = Query(None, description="Filter by status"),
    task_id: str | None = Query(None, description="Filter by task ID"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> AgentListResponse:
    """List agents with optional filtering.

    Args:
        agent_type: Optional agent type filter.
        status: Optional status filter.
        task_id: Optional task ID filter.
        limit: Maximum number of results.
        offset: Offset for pagination.
        session: Database session.

    Returns:
        List of agents.
    """
    agents = await agent_service.get_agents(
        session,
        agent_type=agent_type,
        status=status,
        task_id=task_id,
        limit=limit,
        offset=offset,
    )
    total = await agent_service.count_agents(
        session,
        agent_type=agent_type,
        status=status,
        task_id=task_id,
    )

    return AgentListResponse(
        items=[AgentResponse.model_validate(a) for a in agents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> Agent:
    """Get an agent by ID.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Agent details.

    Raises:
        HTTPException: If agent not found.
    """
    agent = await agent_service.get_agent(session, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return agent


@router.get("/{agent_id}/messages")
async def get_agent_messages(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    """Get messages involving an agent.

    Args:
        agent_id: Agent ID.
        limit: Maximum number of results.
        offset: Offset for pagination.
        session: Database session.

    Returns:
        List of messages.

    Raises:
        HTTPException: If agent not found.
    """
    agent = await agent_service.get_agent(session, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    messages = await message_service.get_agent_messages(
        session, agent_id, limit=limit, offset=offset
    )

    return [
        {
            "id": m.id,
            "sender_type": m.sender_type.value,
            "sender_id": m.sender_id,
            "receiver_type": m.receiver_type.value,
            "receiver_id": m.receiver_id,
            "message_type": m.message_type.value,
            "content": m.content,
            "task_id": m.task_id,
            "created_at": m.created_at.isoformat(),
        }
        for m in messages
    ]


@router.get("/{agent_id}/summary", response_model=AgentSummaryResponse)
async def get_agent_summary(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> AgentSummaryResponse:
    """Get an agent's summary.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Agent summary.

    Raises:
        HTTPException: If agent not found.
    """
    agent = await agent_service.get_agent(session, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Extract summary from personality if exists
    summary = ""
    if agent.personality:
        parts = agent.personality.split("\n\nLast Summary: ")
        if len(parts) > 1:
            summary = parts[1]

    return AgentSummaryResponse(agent_id=agent_id, summary=summary)
