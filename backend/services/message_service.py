"""
Message Service for LongClaw.
Handles message storage and Redis pub/sub for real-time notifications.
"""
import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_settings
from backend.models.message import Message, MessageType, SenderType, ReceiverType

logger = logging.getLogger(__name__)

# Redis channel names
REDIS_CHANNEL_MESSAGES = "longclaw:messages"
REDIS_CHANNEL_AGENT_UPDATES = "longclaw:agent_updates"
REDIS_CHANNEL_TASK_UPDATES = "longclaw:task_updates"


class MessageService:
    """Service for managing messages and real-time notifications."""

    def __init__(self) -> None:
        """Initialize the message service."""
        self._redis: Redis | None = None
        self._pubsub: Any = None

    async def init(self) -> None:
        """Initialize Redis connection."""
        settings = get_settings()
        try:
            self._redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
            )
            # Test connection
            await self._redis.ping()
            logger.info("Message service Redis connection initialized")
        except Exception as e:
            logger.warning(f"Redis not available, running without pub/sub: {e}")
            self._redis = None

    async def close(self) -> None:
        """Close Redis connection."""
        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None
        if self._redis:
            await self._redis.close()
            logger.info("Message service Redis connection closed")

    @property
    def redis(self) -> Redis:
        """Get Redis client.

        Returns:
            Redis client instance.

        Raises:
            RuntimeError: If service is not initialized.
        """
        if not self._redis:
            raise RuntimeError("Message service not initialized")
        return self._redis

    # ==================== Database Operations ====================

    async def create_message(
        self,
        session: AsyncSession,
        sender_type: SenderType,
        sender_id: str | None,
        receiver_type: ReceiverType,
        receiver_id: str | None,
        content: str,
        message_type: MessageType = MessageType.TEXT,
        conversation_id: str | None = None,
        task_id: str | None = None,
        subtask_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """Create a new message in the database.

        Args:
            session: Database session.
            sender_type: Type of sender.
            sender_id: ID of sender.
            receiver_type: Type of receiver.
            receiver_id: ID of receiver.
            content: Message content.
            message_type: Type of message.
            conversation_id: Optional conversation ID.
            task_id: Optional task ID.
            subtask_id: Optional subtask ID.
            metadata: Optional metadata.

        Returns:
            Created message.
        """
        message = Message(
            id=str(uuid4()),
            conversation_id=conversation_id,
            sender_type=sender_type,
            sender_id=sender_id,
            receiver_type=receiver_type,
            receiver_id=receiver_id,
            message_type=message_type,
            content=content,
            message_metadata=metadata,
            task_id=task_id,
            subtask_id=subtask_id,
            created_at=datetime.utcnow(),
        )
        session.add(message)
        await session.flush()

        logger.debug(
            f"Created message {message.id} from {sender_type}:{sender_id} "
            f"to {receiver_type}:{receiver_id}"
        )
        return message

    async def get_message(
        self, session: AsyncSession, message_id: str
    ) -> Message | None:
        """Get a message by ID.

        Args:
            session: Database session.
            message_id: Message ID.

        Returns:
            Message if found, None otherwise.
        """
        result = await session.execute(
            select(Message).where(Message.id == message_id)
        )
        return result.scalar_one_or_none()

    async def get_task_messages(
        self,
        session: AsyncSession,
        task_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """Get messages for a task.

        Args:
            session: Database session.
            task_id: Task ID.
            limit: Maximum number of messages.
            offset: Offset for pagination.

        Returns:
            List of messages.
        """
        result = await session.execute(
            select(Message)
            .where(Message.task_id == task_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_conversation_messages(
        self,
        session: AsyncSession,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """Get messages for a conversation.

        Args:
            session: Database session.
            conversation_id: Conversation ID.
            limit: Maximum number of messages.
            offset: Offset for pagination.

        Returns:
            List of messages.
        """
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_agent_messages(
        self,
        session: AsyncSession,
        agent_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Message]:
        """Get messages involving an agent.

        Args:
            session: Database session.
            agent_id: Agent ID.
            limit: Maximum number of messages.
            offset: Offset for pagination.

        Returns:
            List of messages.
        """
        result = await session.execute(
            select(Message)
            .where(
                (Message.sender_id == agent_id)
                | (Message.receiver_id == agent_id)
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # ==================== Redis Pub/Sub Operations ====================

    async def publish_message(self, message: Message) -> None:
        """Publish a message notification to Redis.

        Args:
            message: Message to publish.
        """
        if not self._redis:
            return
        data = {
            "id": message.id,
            "sender_type": message.sender_type.value,
            "sender_id": message.sender_id,
            "receiver_type": message.receiver_type.value,
            "receiver_id": message.receiver_id,
            "message_type": message.message_type.value,
            "task_id": message.task_id,
            "created_at": message.created_at.isoformat(),
        }
        await self.redis.publish(REDIS_CHANNEL_MESSAGES, json.dumps(data))
        logger.debug(f"Published message notification: {message.id}")

    async def publish_agent_update(
        self, agent_id: str, status: str, task_id: str | None = None
    ) -> None:
        """Publish an agent status update to Redis.

        Args:
            agent_id: Agent ID.
            status: New status.
            task_id: Optional associated task ID.
        """
        if not self._redis:
            return
        data = {
            "agent_id": agent_id,
            "status": status,
            "task_id": task_id,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.redis.publish(REDIS_CHANNEL_AGENT_UPDATES, json.dumps(data))
        logger.debug(f"Published agent update: {agent_id} -> {status}")

    async def publish_task_update(
        self, task_id: str, status: str, progress: float | None = None
    ) -> None:
        """Publish a task status update to Redis.

        Args:
            task_id: Task ID.
            status: New status.
            progress: Optional progress percentage.
        """
        if not self._redis:
            return
        data = {
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await self.redis.publish(REDIS_CHANNEL_TASK_UPDATES, json.dumps(data))
        logger.debug(f"Published task update: {task_id} -> {status}")

    async def subscribe_to_messages(self) -> Any:
        """Subscribe to message notifications.

        Returns:
            PubSub object.
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL_MESSAGES)
        return pubsub

    async def subscribe_to_agent_updates(self) -> Any:
        """Subscribe to agent update notifications.

        Returns:
            PubSub object.
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL_AGENT_UPDATES)
        return pubsub

    async def subscribe_to_task_updates(self) -> Any:
        """Subscribe to task update notifications.

        Returns:
            PubSub object.
        """
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(REDIS_CHANNEL_TASK_UPDATES)
        return pubsub

    async def get_recent_channel_messages(
        self,
        session: AsyncSession,
        channel_id: str,
        limit: int = 20,
        exclude_types: list[MessageType] | None = None,
        after_time: datetime | None = None,
    ) -> list[Message]:
        """Get recent messages from a channel for context building.

        Returns messages where sender is CHANNEL (user) or receiver is CHANNEL (resident reply),
        ordered from oldest to newest (chronological).

        Args:
            session: Database session.
            channel_id: Channel ID to get messages from.
            limit: Maximum number of messages to return.
            exclude_types: Message types to exclude (e.g., TASK, ERROR).
            after_time: Only return messages created after this time (for context reset).

        Returns:
            List of recent messages in chronological order.
        """
        from datetime import datetime as dt
        from sqlalchemy import or_

        # Query for channel-user messages and resident-channel messages (chat pairs)
        query = (
            select(Message)
            .where(
                or_(
                    (Message.sender_type == SenderType.CHANNEL) & (Message.sender_id == channel_id),
                    (Message.receiver_type == ReceiverType.CHANNEL) & (Message.receiver_id == channel_id),
                )
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )

        if exclude_types:
            query = query.where(Message.message_type.not_in(exclude_types))

        if after_time:
            query = query.where(Message.created_at > after_time)

        result = await session.execute(query)
        messages = list(result.scalars().all())

        # Reverse to get chronological order (oldest first)
        messages.reverse()
        return messages


# Global message service instance
message_service = MessageService()
