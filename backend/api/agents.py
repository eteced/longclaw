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
from backend.services.agent_settings_service import agent_settings_service
from backend.services.message_service import message_service

router = APIRouter()


# ==================== Schemas ====================


class ModelAssignmentInfo(BaseModel):
    """Schema for model assignment information."""
    provider: str | None = None
    model: str | None = None
    slot_id: str | None = None
    slot_index: int | None = None


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
    model_assignment: ModelAssignmentInfo | None = None
    created_at: datetime
    updated_at: datetime
    terminated_at: datetime | None

    class Config:
        from_attributes = True
        populate_by_name = True


def _convert_agent_to_response(agent: Agent) -> AgentResponse:
    """Convert Agent model to AgentResponse with model_assignment."""
    model_assign = None
    if agent.model_assignment:
        ma = agent.model_assignment
        model_assign = ModelAssignmentInfo(
            provider=ma.get("provider"),
            model=ma.get("model"),
            slot_id=ma.get("slot_id"),
            slot_index=ma.get("slot_index"),
        )
    
    return AgentResponse(
        id=agent.id,
        agent_type=agent.agent_type,
        name=agent.name,
        personality=agent.personality,
        status=agent.status,
        error_message=agent.error_message,
        parent_agent_id=agent.parent_agent_id,
        task_id=agent.task_id,
        model_config=agent.model_assignment,
        model_assignment=model_assign,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
        terminated_at=agent.terminated_at,
    )


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


class AgentCreate(BaseModel):
    """Schema for creating an agent."""

    name: str = Field(..., min_length=1, max_length=100, description="Agent name")
    personality: str | None = Field(None, description="Agent personality description")
    system_prompt: str | None = Field(None, description="System prompt override")
    provider_name: str | None = Field(None, description="LLM provider name")
    model_name: str | None = Field(None, description="LLM model name")
    max_context_tokens: int | None = Field(None, description="Max context tokens")


class AgentUpdate(BaseModel):
    """Schema for updating an agent."""

    name: str | None = Field(None, min_length=1, max_length=100, description="Agent name")
    personality: str | None = Field(None, description="Agent personality description")
    system_prompt: str | None = Field(None, description="System prompt override")


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
        items=[_convert_agent_to_response(a) for a in agents],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=AgentResponse)
async def create_agent(
    data: AgentCreate,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Create a new agent.

    Args:
        data: Agent creation data.
        session: Database session.

    Returns:
        Created agent.
    """
    # Build model_assignment from provider/model if provided
    model_assignment = None
    if data.provider_name or data.model_name:
        model_assignment = {
            "provider": data.provider_name,
            "model": data.model_name,
        }

    # Create agent via service
    agent = await agent_service.create_agent(
        session,
        agent_type=AgentType.RESIDENT,  # Only allow resident for now
        name=data.name,
        personality=data.personality,
        model_assignment=model_assignment,
        system_prompt=data.system_prompt,
    )

    # If instance-level settings provided, save them
    if data.system_prompt or data.provider_name or data.model_name or data.max_context_tokens:
        await agent_settings_service.update_agent_settings(
            session,
            agent.id,
            system_prompt=data.system_prompt,
            provider_name=data.provider_name,
            model_name=data.model_name,
            max_context_tokens=data.max_context_tokens,
        )

    # Commit the transaction so the agent is visible to other sessions
    # (register_and_start_resident_agent opens a new session to load the agent)
    await session.commit()

    # Dynamically start the resident agent
    from backend.services.agent_registry import register_and_start_resident_agent
    await register_and_start_resident_agent(agent.id)

    return _convert_agent_to_response(agent)


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    data: AgentUpdate,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Update an agent.

    Args:
        agent_id: Agent ID.
        data: Update data.
        session: Database session.

    Returns:
        Updated agent.

    Raises:
        HTTPException: If agent not found.
    """
    # Check agent exists
    existing = await agent_service.get_agent(session, agent_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Build kwargs for update
    update_kwargs = {}
    if data.name is not None:
        update_kwargs["name"] = data.name
    if data.personality is not None:
        update_kwargs["personality"] = data.personality
    if data.system_prompt is not None:
        update_kwargs["system_prompt"] = data.system_prompt

    # Update via service
    agent = await agent_service.update_agent(session, agent_id, **update_kwargs)

    return _convert_agent_to_response(agent)


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


@router.post("/{agent_id}/terminate", response_model=AgentResponse)
async def terminate_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Terminate an agent.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Terminated agent.

    Raises:
        HTTPException: If agent not found.
    """
    agent = await agent_service.get_agent(session, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if agent is bound to any channel
    from backend.services.channel_service import channel_service
    channels = await channel_service.get_channels(session, resident_agent_id=agent_id)
    if channels:
        raise HTTPException(
            status_code=400,
            detail=f"Agent is bound to {len(channels)} channel(s). Unbind it first before terminating."
        )

    # Stop and unregister the agent instance from registry
    from backend.services.agent_registry import agent_registry
    if agent_registry.has_agent(agent_id):
        agent_instance = agent_registry.get_agent(agent_id)
        if agent_instance:
            await agent_instance.terminate()
        agent_registry.unregister_agent(agent_id)

    # Also remove from main.py's _resident_agents dict
    from backend.main import _resident_agents
    if agent_id in _resident_agents:
        del _resident_agents[agent_id]

    terminated = await agent_service.terminate_agent(session, agent_id)
    if not terminated:
        raise HTTPException(status_code=500, detail="Failed to terminate agent")

    # Commit to ensure terminate is persisted before response
    await session.commit()

    return _convert_agent_to_response(terminated)


@router.post("/{agent_id}/start", response_model=AgentResponse)
async def start_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> AgentResponse:
    """Start a terminated agent.

    This allows a previously terminated agent to be restarted.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Started agent.

    Raises:
        HTTPException: If agent not found or not in TERMINATED state.
    """
    agent = await agent_service.get_agent(session, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Only allow starting terminated agents
    if agent.status != AgentStatus.TERMINATED:
        raise HTTPException(
            status_code=400,
            detail=f"Only terminated agents can be started. Current status: {agent.status.value}"
        )

    # Check if agent is bound to any channel
    from backend.services.channel_service import channel_service
    channels = await channel_service.get_channels(session, resident_agent_id=agent_id)
    if not channels:
        raise HTTPException(
            status_code=400,
            detail="Agent is not bound to any channel. Bind it to a channel first before starting."
        )

    # Start the agent via registry
    from backend.services.agent_registry import register_and_start_resident_agent
    await register_and_start_resident_agent(agent_id)

    # Commit the start before fetching updated status
    await session.commit()

    # Fetch the agent again to get updated status
    agent = await agent_service.get_agent(session, agent_id)

    return _convert_agent_to_response(agent)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Delete an agent.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Success message.

    Raises:
        HTTPException: If agent not found or cannot be deleted.
    """
    agent = await agent_service.get_agent(session, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Check if agent is bound to any channel
    from backend.services.channel_service import channel_service
    channels = await channel_service.get_channels(session, resident_agent_id=agent_id)
    if channels:
        raise HTTPException(
            status_code=400,
            detail=f"Agent is bound to {len(channels)} channel(s). Unbind it first before deleting."
        )

    # Only allow deleting terminated agents
    if agent.status != AgentStatus.TERMINATED:
        raise HTTPException(
            status_code=400,
            detail="Only terminated agents can be deleted. Please terminate the agent first."
        )

    # Ensure agent is not in any running dictionaries
    from backend.main import _resident_agents
    if agent_id in _resident_agents:
        del _resident_agents[agent_id]

    # Unregister from agent registry if still there
    from backend.services.agent_registry import agent_registry
    if agent_registry.has_agent(agent_id):
        agent_registry.unregister_agent(agent_id)

    # Commit before deleting to ensure cleanup is visible
    await session.commit()

    await agent_service.delete_agent(session, agent_id)
    return {"deleted": "true", "agent_id": agent_id}
