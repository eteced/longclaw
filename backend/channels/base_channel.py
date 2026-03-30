"""
Base Channel for LongClaw.
Abstract base class for communication channels.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any

from backend.models.channel import ChannelType
from backend.models.message import Message

logger = logging.getLogger(__name__)


class BaseChannel(ABC):
    """Abstract base class for communication channels.

    Provides:
    - Message receiving and sending
    - Channel lifecycle management
    - Connection to Resident Agent
    """

    def __init__(
        self,
        channel_id: str,
        channel_type: ChannelType,
        config: dict[str, Any] | None = None,
        resident_agent_id: str | None = None,
    ) -> None:
        """Initialize the channel.

        Args:
            channel_id: Channel ID.
            channel_type: Type of channel.
            config: Channel configuration.
            resident_agent_id: ID of the resident agent bound to this channel.
        """
        self._id = channel_id
        self._type = channel_type
        self._config = config or {}
        self._resident_agent_id = resident_agent_id
        self._is_running = False

    @property
    def id(self) -> str:
        """Get channel ID.

        Returns:
            Channel ID.
        """
        return self._id

    @property
    def channel_type(self) -> ChannelType:
        """Get channel type.

        Returns:
            Channel type.
        """
        return self._type

    @property
    def is_running(self) -> bool:
        """Check if channel is running.

        Returns:
            True if running, False otherwise.
        """
        return self._is_running

    async def start(self) -> None:
        """Start the channel."""
        if self._is_running:
            logger.warning(f"Channel {self._id} is already running")
            return

        await self.on_start()
        self._is_running = True
        logger.info(f"Started channel {self._id} ({self._type.value})")

    async def stop(self) -> None:
        """Stop the channel."""
        if not self._is_running:
            return

        await self.on_stop()
        self._is_running = False
        logger.info(f"Stopped channel {self._id}")

    async def send_message(self, message: Message) -> None:
        """Send a message through this channel.

        Args:
            message: Message to send.
        """
        await self.on_send_message(message)

    # ==================== Abstract Methods ====================

    @abstractmethod
    async def on_start(self) -> None:
        """Called when the channel starts.

        Override this to perform initialization.
        """
        pass

    @abstractmethod
    async def on_stop(self) -> None:
        """Called when the channel stops.

        Override this to perform cleanup.
        """
        pass

    @abstractmethod
    async def on_send_message(self, message: Message) -> None:
        """Send a message through the channel.

        Args:
            message: Message to send.

        Override this to implement channel-specific sending.
        """
        pass

    @abstractmethod
    async def on_receive_message(self, raw_message: dict[str, Any]) -> Message:
        """Process a received raw message.

        Args:
            raw_message: Raw message from the channel.

        Returns:
            Processed Message object.

        Override this to implement channel-specific message parsing.
        """
        pass
