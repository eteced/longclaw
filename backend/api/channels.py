"""
Channels API for LongClaw.
"""
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.channel import Channel, ChannelType
from backend.services.channel_service import channel_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Schemas ====================


class ChannelCreate(BaseModel):
    """Schema for creating a channel."""

    channel_type: ChannelType
    config: dict[str, Any] | None = None
    resident_agent_id: str | None = None


class ChannelUpdate(BaseModel):
    """Schema for updating a channel."""

    config: dict[str, Any] | None = None
    resident_agent_id: str | None = None
    is_active: bool | None = None


class ChannelResponse(BaseModel):
    """Schema for channel response."""

    id: str
    channel_type: ChannelType
    config: dict[str, Any] | None
    resident_agent_id: str | None
    target_agent_id: str | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class ChannelListResponse(BaseModel):
    """Schema for channel list response."""

    items: list[ChannelResponse]
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


@router.get("", response_model=ChannelListResponse)
async def list_channels(
    channel_type: ChannelType | None = Query(None, description="Filter by channel type"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    limit: int = Query(20, ge=1, le=100, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> ChannelListResponse:
    """List channels with optional filtering.

    Args:
        channel_type: Optional channel type filter.
        is_active: Optional active status filter.
        limit: Maximum number of results.
        offset: Offset for pagination.
        session: Database session.

    Returns:
        List of channels.
    """
    channels = await channel_service.get_channels(
        session,
        channel_type=channel_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )

    return ChannelListResponse(
        items=[ChannelResponse.model_validate(c) for c in channels],
        limit=limit,
        offset=offset,
    )


@router.get("/{channel_id}", response_model=ChannelResponse)
async def get_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_session),
) -> Channel:
    """Get a channel by ID.

    Args:
        channel_id: Channel ID.
        session: Database session.

    Returns:
        Channel details.

    Raises:
        HTTPException: If channel not found.
    """
    channel = await channel_service.get_channel(session, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    return channel


@router.post("", response_model=ChannelResponse, status_code=201)
async def create_channel(
    data: ChannelCreate,
    session: AsyncSession = Depends(get_session),
) -> ChannelResponse:
    """Create a new channel.

    Args:
        data: Channel creation data.
        session: Database session.

    Returns:
        Created channel.
    """
    channel = await channel_service.create_channel(
        session,
        channel_type=data.channel_type,
        config=data.config,
        resident_agent_id=data.resident_agent_id,
    )

    # Commit the transaction so channel is visible to other sessions
    await session.commit()

    # Refresh the channel to ensure all attributes are loaded in the async context
    await session.refresh(channel)

    # Dynamically start web channel if agent is bound
    if channel.channel_type == ChannelType.WEB and channel.resident_agent_id:
        from backend.services.agent_registry import register_and_start_resident_agent
        from backend.channels.web_channel import WebChannel

        # Ensure agent is started
        await register_and_start_resident_agent(channel.resident_agent_id)

        # Start web channel
        from backend.main import _web_channels
        web_channel = WebChannel(
            channel_id=channel.id,
            resident_agent_id=channel.resident_agent_id,
            config=channel.config,
        )
        await web_channel.start()
        _web_channels[channel.id] = web_channel

    return ChannelResponse.model_validate(channel)


@router.put("/{channel_id}", response_model=ChannelResponse)
async def update_channel(
    channel_id: str,
    data: ChannelUpdate,
    session: AsyncSession = Depends(get_session),
) -> Channel:
    """Update a channel.

    Args:
        channel_id: Channel ID.
        data: Channel update data.
        session: Database session.

    Returns:
        Updated channel.

    Raises:
        HTTPException: If channel not found.
    """
    from backend.main import _web_channels
    from backend.services.agent_registry import register_and_start_resident_agent
    from backend.channels.web_channel import WebChannel

    channel = await channel_service.get_channel(session, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Store old values to detect changes
    old_is_active = channel.is_active
    old_resident_agent_id = channel.resident_agent_id

    update_data = data.model_dump(exclude_unset=True)
    channel = await channel_service.update_channel(
        session, channel_id, **update_data
    )

    # Refresh the channel to ensure all attributes are loaded in the async context
    await session.refresh(channel)

    # Handle web channel activation/deactivation
    if channel.channel_type == ChannelType.WEB:
        new_is_active = channel.is_active
        new_resident_agent_id = channel.resident_agent_id

        # If channel is now active and has an agent, start it
        if new_is_active and new_resident_agent_id:
            # Start agent if needed
            await register_and_start_resident_agent(new_resident_agent_id)

            # Start or restart channel
            if channel_id in _web_channels:
                # Stop existing channel
                old_channel = _web_channels.pop(channel_id)
                await old_channel.stop()

            # Start new channel
            web_channel = WebChannel(
                channel_id=channel.id,
                resident_agent_id=new_resident_agent_id,
                config=channel.config,
            )
            await web_channel.start()
            _web_channels[channel.id] = web_channel

        # If channel was deactivated, stop it
        elif old_is_active and not new_is_active:
            if channel_id in _web_channels:
                old_channel = _web_channels.pop(channel_id)
                await old_channel.stop()

    return ChannelResponse.model_validate(channel)


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Delete a channel.

    Args:
        channel_id: Channel ID.
        session: Database session.

    Returns:
        Success message.

    Raises:
        HTTPException: If channel not found.
    """
    # Stop web channel if running
    from backend.main import _web_channels
    if channel_id in _web_channels:
        web_channel = _web_channels.pop(channel_id)
        await web_channel.stop()

    deleted = await channel_service.delete_channel(session, channel_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Commit to ensure delete is persisted
    await session.commit()

    return {"status": "deleted", "channel_id": channel_id}


@router.post("/{channel_id}/switch-agent", response_model=ChannelResponse)
async def switch_target_agent(
    channel_id: str,
    target_agent_id: str,
    session: AsyncSession = Depends(get_session),
) -> Channel:
    """Switch the target agent for a channel.

    This allows a channel to communicate with a different agent
    without changing the resident agent binding.

    Args:
        channel_id: Channel ID.
        target_agent_id: Target agent ID to switch to.
        session: Database session.

    Returns:
        Updated channel.

    Raises:
        HTTPException: If channel or agent not found.
    """
    from backend.services.agent_service import agent_service

    # Check channel exists
    channel = await channel_service.get_channel(session, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")

    # Check agent exists
    agent = await agent_service.get_agent(session, target_agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Update target agent
    channel.target_agent_id = target_agent_id
    channel.updated_at = datetime.utcnow()
    await session.flush()

    return channel
