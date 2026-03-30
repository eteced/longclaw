"""
Channel Service for LongClaw.
Manages communication channels.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.channel import Channel, ChannelType

logger = logging.getLogger(__name__)


class ChannelService:
    """Service for managing communication channels."""

    async def create_channel(
        self,
        session: AsyncSession,
        channel_type: ChannelType,
        config: dict[str, Any] | None = None,
        resident_agent_id: str | None = None,
    ) -> Channel:
        """Create a new channel.

        Args:
            session: Database session.
            channel_type: Type of channel.
            config: Optional channel configuration.
            resident_agent_id: Optional resident agent ID to bind.

        Returns:
            Created channel.
        """
        channel = Channel(
            id=str(uuid4()),
            channel_type=channel_type,
            config=config,
            resident_agent_id=resident_agent_id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        session.add(channel)
        await session.flush()

        logger.info(f"Created channel {channel.id} ({channel_type.value})")
        return channel

    async def get_channel(
        self, session: AsyncSession, channel_id: str
    ) -> Channel | None:
        """Get a channel by ID.

        Args:
            session: Database session.
            channel_id: Channel ID.

        Returns:
            Channel if found, None otherwise.
        """
        result = await session.execute(
            select(Channel).where(Channel.id == channel_id)
        )
        return result.scalar_one_or_none()

    async def get_channels(
        self,
        session: AsyncSession,
        channel_type: ChannelType | None = None,
        is_active: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Channel]:
        """Get channels with optional filtering.

        Args:
            session: Database session.
            channel_type: Optional channel type filter.
            is_active: Optional active status filter.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of channels.
        """
        query = select(Channel)

        if channel_type:
            query = query.where(Channel.channel_type == channel_type)
        if is_active is not None:
            query = query.where(Channel.is_active == is_active)

        query = query.order_by(Channel.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_channel(
        self,
        session: AsyncSession,
        channel_id: str,
        **kwargs: Any,
    ) -> Channel | None:
        """Update a channel's attributes.

        Args:
            session: Database session.
            channel_id: Channel ID.
            **kwargs: Attributes to update.

        Returns:
            Updated channel if found, None otherwise.
        """
        channel = await self.get_channel(session, channel_id)
        if not channel:
            return None

        for key, value in kwargs.items():
            if hasattr(channel, key):
                setattr(channel, key, value)

        await session.flush()
        logger.debug(f"Updated channel {channel_id}: {list(kwargs.keys())}")
        return channel

    async def bind_resident_agent(
        self,
        session: AsyncSession,
        channel_id: str,
        resident_agent_id: str,
    ) -> Channel | None:
        """Bind a resident agent to a channel.

        Args:
            session: Database session.
            channel_id: Channel ID.
            resident_agent_id: Resident agent ID.

        Returns:
            Updated channel if found, None otherwise.
        """
        return await self.update_channel(
            session, channel_id, resident_agent_id=resident_agent_id
        )

    async def set_active(
        self,
        session: AsyncSession,
        channel_id: str,
        is_active: bool,
    ) -> Channel | None:
        """Set channel active status.

        Args:
            session: Database session.
            channel_id: Channel ID.
            is_active: Active status.

        Returns:
            Updated channel if found, None otherwise.
        """
        return await self.update_channel(session, channel_id, is_active=is_active)

    async def delete_channel(
        self, session: AsyncSession, channel_id: str
    ) -> bool:
        """Delete a channel.

        Args:
            session: Database session.
            channel_id: Channel ID.

        Returns:
            True if deleted, False if not found.
        """
        channel = await self.get_channel(session, channel_id)
        if not channel:
            return False

        await session.delete(channel)
        await session.flush()
        logger.info(f"Deleted channel {channel_id}")
        return True


# Global channel service instance
channel_service = ChannelService()
