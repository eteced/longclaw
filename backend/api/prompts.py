"""
Agent Prompts API for LongClaw.
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.agent_prompt import PromptType
from backend.services.agent_prompt_service import agent_prompt_service

router = APIRouter()


# ==================== Schemas ====================


class TypePromptResponse(BaseModel):
    """Schema for type-level prompt response."""

    id: str | None = None
    agent_type: str
    system_prompt: str
    is_default: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class InstancePromptResponse(BaseModel):
    """Schema for instance-level prompt response."""

    id: str
    agent_id: str
    system_prompt: str
    created_at: datetime
    updated_at: datetime


class AllPromptsResponse(BaseModel):
    """Schema for all prompts response."""

    type_prompts: dict[str, Any]
    instance_prompts: dict[str, Any]


class TypePromptUpdate(BaseModel):
    """Schema for updating type-level prompt."""

    system_prompt: str = Field(..., min_length=1)


class InstancePromptUpdate(BaseModel):
    """Schema for updating instance-level prompt."""

    system_prompt: str = Field(..., min_length=1)


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency.

    Yields:
        AsyncSession instance.
    """
    async with db_manager.session() as session:
        yield session


# ==================== Endpoints ====================


@router.get("", response_model=AllPromptsResponse)
async def get_all_prompts(
    session: AsyncSession = Depends(get_session),
) -> AllPromptsResponse:
    """Get all prompt configurations.

    Returns both type-level defaults and instance-level overrides.

    Args:
        session: Database session.

    Returns:
        All prompt configurations.
    """
    return await agent_prompt_service.get_all_prompts(session)


@router.get("/type/{agent_type}", response_model=TypePromptResponse)
async def get_type_prompt(
    agent_type: PromptType,
    session: AsyncSession = Depends(get_session),
) -> TypePromptResponse:
    """Get the default prompt for an agent type.

    Args:
        agent_type: Agent type.
        session: Database session.

    Returns:
        Type-level prompt configuration.
    """
    prompts = await agent_prompt_service.get_all_prompts(session)
    type_prompts = prompts["type_prompts"]

    if agent_type.value not in type_prompts:
        raise HTTPException(status_code=404, detail="Prompt type not found")

    prompt_data = type_prompts[agent_type.value]
    return TypePromptResponse(
        id=prompt_data.get("id"),
        agent_type=prompt_data["agent_type"],
        system_prompt=prompt_data["system_prompt"],
        is_default=prompt_data.get("is_default", False),
        created_at=prompt_data.get("created_at"),
        updated_at=prompt_data.get("updated_at"),
    )


@router.put("/type/{agent_type}", response_model=TypePromptResponse)
async def update_type_prompt(
    agent_type: PromptType,
    data: TypePromptUpdate,
    session: AsyncSession = Depends(get_session),
) -> TypePromptResponse:
    """Update the default prompt for an agent type.

    Args:
        agent_type: Agent type.
        data: Update data.
        session: Database session.

    Returns:
        Updated prompt configuration.
    """
    prompt = await agent_prompt_service.set_type_prompt(
        session, agent_type, data.system_prompt
    )

    return TypePromptResponse(
        id=prompt.id,
        agent_type=agent_type.value,
        system_prompt=prompt.system_prompt,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )


@router.delete("/type/{agent_type}")
async def reset_type_prompt(
    agent_type: PromptType,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Reset the prompt for an agent type to default.

    Args:
        agent_type: Agent type.
        session: Database session.

    Returns:
        Success message.
    """
    success = await agent_prompt_service.reset_type_prompt(session, agent_type)
    if not success:
        # Already using default, that's fine
        pass

    return {"message": f"Prompt for type {agent_type.value} reset to default"}


@router.put("/agent/{agent_id}", response_model=InstancePromptResponse)
async def set_agent_prompt(
    agent_id: str,
    data: InstancePromptUpdate,
    session: AsyncSession = Depends(get_session),
) -> InstancePromptResponse:
    """Set the override prompt for a specific agent.

    Args:
        agent_id: Agent ID.
        data: Update data.
        session: Database session.

    Returns:
        Created or updated prompt configuration.
    """
    prompt = await agent_prompt_service.set_agent_prompt(
        session, agent_id, data.system_prompt
    )

    return InstancePromptResponse(
        id=prompt.id,
        agent_id=agent_id,
        system_prompt=prompt.system_prompt,
        created_at=prompt.created_at,
        updated_at=prompt.updated_at,
    )


@router.delete("/agent/{agent_id}")
async def delete_agent_prompt(
    agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Delete the override prompt for a specific agent.

    Args:
        agent_id: Agent ID.
        session: Database session.

    Returns:
        Success message.
    """
    success = await agent_prompt_service.delete_agent_prompt(session, agent_id)
    if not success:
        raise HTTPException(status_code=404, detail="Prompt override not found")

    return {"message": f"Prompt override for agent {agent_id} deleted"}
