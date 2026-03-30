"""
Web Channel for LongClaw.
Handles web-based communication between users and agents.
"""
import logging
from typing import Any

from backend.channels.base_channel import BaseChannel
from backend.models.channel import ChannelType
from backend.models.message import Message, MessageType, SenderType, ReceiverType
from backend.services.message_service import message_service

logger = logging.getLogger(__name__)


class WebChannel(BaseChannel):
    """Web channel for browser-based communication.

    This channel:
    - Receives messages from the web API
    - Delivers messages to the resident agent
    - Sends agent replies back to the web interface
    """

    def __init__(
        self,
        channel_id: str,
        resident_agent_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the web channel.

        Args:
            channel_id: Channel ID.
            resident_agent_id: ID of the resident agent bound to this channel.
            config: Channel configuration.
        """
        super().__init__(
            channel_id=channel_id,
            channel_type=ChannelType.WEB,
            config=config,
            resident_agent_id=resident_agent_id,
        )
        self._pending_messages: dict[str, Message] = {}

    async def on_start(self) -> None:
        """Called when the channel starts."""
        logger.info(f"Web channel {self._id} started")

    async def on_stop(self) -> None:
        """Called when the channel stops."""
        logger.info(f"Web channel {self._id} stopped")

    async def on_send_message(self, message: Message) -> None:
        """Send a message through this channel.

        For web channel, this stores the message for retrieval by the frontend.

        Args:
            message: Message to send.
        """
        # Store message for frontend retrieval
        self._pending_messages[message.id] = message
        logger.debug(f"Web channel stored message {message.id}")

        # Also publish to Redis for real-time notification
        await message_service.publish_message(message)

    async def on_receive_message(self, raw_message: dict[str, Any]) -> Message:
        """Process a received raw message from the web interface.

        Args:
            raw_message: Raw message from the web interface.

        Returns:
            Processed Message object.
        """
        # Create message from raw data
        content = raw_message.get("content", "")

        message = Message(
            id=raw_message.get("id"),
            sender_type=SenderType.CHANNEL,
            sender_id=self._id,
            receiver_type=ReceiverType.RESIDENT,
            receiver_id=self._resident_agent_id,
            message_type=MessageType.TEXT,
            content=content,
            created_at=raw_message.get("created_at"),
        )

        return message

    def get_pending_messages(self) -> list[Message]:
        """Get all pending messages.

        Returns:
            List of pending messages.
        """
        return list(self._pending_messages.values())

    def clear_pending_messages(self) -> None:
        """Clear all pending messages."""
        self._pending_messages.clear()
