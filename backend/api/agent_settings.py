"""
Agent Settings API for LongClaw.
Manages agent prompts and model assignments.
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.agent import AgentType
from backend.services.agent_settings_service import agent_settings_service

router = APIRouter()


# ==================== Schemas ====================


class TypeSettingsResponse(BaseModel):
    """Schema for type-level settings response."""

    id: str | None = None
    agent_type: str
    system_prompt: str
    provider_name: str | None = None
    model_name: str | None = None
    max_context_tokens: int | None = None
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InstanceSettingsResponse(BaseModel):
    """Schema for instance-level settings response."""

    id: str
    agent_id: str
    system_prompt: str
    provider_name: str | None = None
    model_name: str | None = None
    max_context_tokens: int | None = None
    created_at: datetime
    updated_at: datetime


class AllSettingsResponse(BaseModel):
    """Schema for all settings response."""

    type_settings: dict[str, Any]
    instance_settings: dict[str, Any]


class TypeSettingsUpdate(BaseModel):
    """Schema for updating type-level settings."""

    system_prompt: str | None = Field(None, min_length=1)
    provider_name: str | None = None
    model_name: str | None = None
    # -1 means unlimited, positive values must be at least 1024
    max_context_tokens: int | None = Field(None, ge=-1, le=1000000)


class InstanceSettingsUpdate(BaseModel):
    """Schema for updating instance-level settings."""

    system_prompt: str | None = Field(None, min_length=1)
    provider_name: str | None = None
    model_name: str | None = None
    # -1 means unlimited, positive values must be at least 1024
    max_context_tokens: int | None = Field(None, ge=-1, le=1000000)


class ModelAssignmentUpdate(BaseModel):
    """Schema for updating just the model assignment."""

    provider_name: str
    model_name: str


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency.

    Yields:
        AsyncSession instance.
    """
    async with db_manager.session() as session:
        yield session


# ==================== Endpoints ====================


@router.get("", response_model=AllSettingsResponse)
async def get_all_settings(
    session: AsyncSession = Depends(get_session),
) -> AllSettingsResponse:
    """Get all agent settings.

    Returns both type-level defaults and instance-level overrides.

    Args:
        session: Database session.

    Returns:
        All agent settings.
    """
    return await agent_settings_service.get_all_settings(session)


@router.get("/type/{agent_type}", response_model=TypeSettingsResponse)
async def get_type_settings(
    agent_type: AgentType,
    session: AsyncSession = Depends(get_session),
) -> TypeSettingsResponse:
    """Get the settings for an agent type.

    Args:
        agent_type: Agent type.
        session: Database session.

    Returns:
        Type-level settings.
    """
    settings = await agent_settings_service.get_type_settings(session, agent_type)
    return TypeSettingsResponse(
        id=settings.get("id"),
        agent_type=settings["agent_type"],
        system_prompt=settings["system_prompt"],
        provider_name=settings.get("provider_name"),
        model_name=settings.get("model_name"),
        max_context_tokens=settings.get("max_context_tokens"),
        is_default=settings.get("is_default", False),
        created_at=settings.get("created_at"),
        updated_at=settings.get("updated_at"),
    )


@router.put("/type/{agent_type}", response_model=TypeSettingsResponse)
async def update_type_settings(
    agent_type: AgentType,
    data: TypeSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> TypeSettingsResponse:
    """Update the settings for an agent type.

    Args:
        agent_type: Agent type.
        data: Update data.
        session: Database session.

    Returns:
        Updated settings.
    """
    if not data.system_prompt and not data.provider_name and not data.model_name and data.max_context_tokens is None:
        raise HTTPException(status_code=400, detail="At least one field must be provided")

    setting = await agent_settings_service.update_type_settings(
        session,
        agent_type,
        system_prompt=data.system_prompt,
        provider_name=data.provider_name,
        model_name=data.model_name,
        max_context_tokens=data.max_context_tokens,
    )

    return TypeSettingsResponse(
        id=setting.id,
        agent_type=agent_type.value,
        system_prompt=setting.system_prompt,
        provider_name=setting.provider_name,
        model_name=setting.model_name,
        max_context_tokens=setting.max_context_tokens,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
    )


@router.delete("/type/{agent_type}")
async def reset_type_settings(
    agent_type: AgentType,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Reset the settings for an agent type to default.

    Args:
        agent_type: Agent type.
        session: Database session.

    Returns:
        Success message.
    """
    await agent_settings_service.reset_type_settings(session, agent_type)
    return {"message": f"Settings for type {agent_type.value} reset to default"}


@router.get("/agent/{agent_id}", response_model=InstanceSettingsResponse)
async def get_agent_settings(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> InstanceSettingsResponse:
    """Get the settings for a specific agent.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Agent settings.
    """
    # First check if agent exists
    from backend.models.agent import Agent
    from sqlalchemy import select

    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    settings = await agent_settings_service.get_agent_settings(
        session, agent_id, agent.agent_type
    )

    if not settings.get("id"):
        raise HTTPException(status_code=404, detail="No instance-level settings found")

    return InstanceSettingsResponse(
        id=settings["id"],
        agent_id=agent_id,
        system_prompt=settings["system_prompt"],
        provider_name=settings.get("provider_name"),
        model_name=settings.get("model_name"),
        max_context_tokens=settings.get("max_context_tokens"),
        created_at=settings["created_at"],
        updated_at=settings["updated_at"],
    )


@router.put("/agent/{agent_id}", response_model=InstanceSettingsResponse)
async def update_agent_settings(
    agent_id: str,
    data: InstanceSettingsUpdate,
    session: AsyncSession = Depends(get_session),
) -> InstanceSettingsResponse:
    """Update the settings for a specific agent.

    Args:
        agent_id: Agent ID.
        data: Update data.
        session: Database session.

    Returns:
        Updated settings.
    """
    if not data.system_prompt and not data.provider_name and not data.model_name and data.max_context_tokens is None:
        raise HTTPException(status_code=400, detail="At least one field must be provided")

    # First check if agent exists
    from backend.models.agent import Agent
    from sqlalchemy import select

    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    setting = await agent_settings_service.update_agent_settings(
        session,
        agent_id,
        system_prompt=data.system_prompt,
        provider_name=data.provider_name,
        model_name=data.model_name,
        max_context_tokens=data.max_context_tokens,
    )

    return InstanceSettingsResponse(
        id=setting.id,
        agent_id=agent_id,
        system_prompt=setting.system_prompt,
        provider_name=setting.provider_name,
        model_name=setting.model_name,
        max_context_tokens=setting.max_context_tokens,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
    )


@router.delete("/agent/{agent_id}")
async def delete_agent_settings(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Delete the override settings for a specific agent.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Success message.
    """
    success = await agent_settings_service.delete_agent_settings(session, agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent settings override not found")

    return {"message": f"Settings override for agent {agent_id} deleted"}


@router.put("/type/{agent_type}/model", response_model=TypeSettingsResponse)
async def set_type_model(
    agent_type: AgentType,
    data: ModelAssignmentUpdate,
    session: AsyncSession = Depends(get_session),
) -> TypeSettingsResponse:
    """Set the model assignment for an agent type.

    Args:
        agent_type: Agent type.
        data: Model assignment data.
        session: Database session.

    Returns:
        Updated settings.
    """
    setting = await agent_settings_service.set_type_model(
        session, agent_type, data.provider_name, data.model_name
    )

    return TypeSettingsResponse(
        id=setting.id,
        agent_type=agent_type.value,
        system_prompt=setting.system_prompt,
        provider_name=setting.provider_name,
        model_name=setting.model_name,
        max_context_tokens=setting.max_context_tokens,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
    )


@router.put("/agent/{agent_id}/model", response_model=InstanceSettingsResponse)
async def set_agent_model(
    agent_id: str,
    data: ModelAssignmentUpdate,
    session: AsyncSession = Depends(get_session),
) -> InstanceSettingsResponse:
    """Set the model assignment for a specific agent.

    Args:
        agent_id: Agent ID.
        data: Model assignment data.
        session: Database session.

    Returns:
        Updated settings.
    """
    # First check if agent exists
    from backend.models.agent import Agent
    from sqlalchemy import select

    result = await session.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    setting = await agent_settings_service.set_agent_model(
        session, agent_id, data.provider_name, data.model_name
    )

    return InstanceSettingsResponse(
        id=setting.id,
        agent_id=agent_id,
        system_prompt=setting.system_prompt,
        provider_name=setting.provider_name,
        model_name=setting.model_name,
        max_context_tokens=setting.max_context_tokens,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
    )
