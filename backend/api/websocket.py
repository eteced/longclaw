"""
WebSocket API for LongClaw.
Provides real-time communication for streaming messages and updates.
"""
import asyncio
import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.services.message_service import message_service

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self) -> None:
        """Initialize the connection manager."""
        self._connections: dict[str, WebSocket] = {}
        self._channel_subscriptions: dict[str, set[str]] = {}  # channel_id -> set of connection_ids
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> str:
        """Accept a new WebSocket connection.

        Args:
            websocket: The WebSocket connection.

        Returns:
            Connection ID.
        """
        await websocket.accept()
        connection_id = str(uuid4())
        async with self._lock:
            self._connections[connection_id] = websocket
        logger.info(f"WebSocket connected: {connection_id}")
        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        """Remove a WebSocket connection.

        Args:
            connection_id: The connection ID to remove.
        """
        async with self._lock:
            if connection_id in self._connections:
                del self._connections[connection_id]

            # Remove from all channel subscriptions
            for channel_id, subscribers in list(self._channel_subscriptions.items()):
                subscribers.discard(connection_id)
                if not subscribers:
                    del self._channel_subscriptions[channel_id]

        logger.info(f"WebSocket disconnected: {connection_id}")

    async def subscribe_to_channel(self, connection_id: str, channel_id: str) -> None:
        """Subscribe a connection to a channel.

        Args:
            connection_id: The connection ID.
            channel_id: The channel ID to subscribe to.
        """
        async with self._lock:
            if channel_id not in self._channel_subscriptions:
                self._channel_subscriptions[channel_id] = set()
            self._channel_subscriptions[channel_id].add(connection_id)
        logger.debug(f"Connection {connection_id} subscribed to channel {channel_id}")

    async def unsubscribe_from_channel(self, connection_id: str, channel_id: str) -> None:
        """Unsubscribe a connection from a channel.

        Args:
            connection_id: The connection ID.
            channel_id: The channel ID to unsubscribe from.
        """
        async with self._lock:
            if channel_id in self._channel_subscriptions:
                self._channel_subscriptions[channel_id].discard(connection_id)
                if not self._channel_subscriptions[channel_id]:
                    del self._channel_subscriptions[channel_id]
        logger.debug(f"Connection {connection_id} unsubscribed from channel {channel_id}")

    async def send_to_connection(self, connection_id: str, message: dict[str, Any]) -> None:
        """Send a message to a specific connection.

        Args:
            connection_id: The connection ID.
            message: The message to send.
        """
        async with self._lock:
            websocket = self._connections.get(connection_id)

        if websocket:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to connection {connection_id}: {e}")
                await self.disconnect(connection_id)

    async def broadcast_to_channel(self, channel_id: str, message: dict[str, Any]) -> None:
        """Broadcast a message to all connections subscribed to a channel.

        Args:
            channel_id: The channel ID.
            message: The message to broadcast.
        """
        async with self._lock:
            subscribers = self._channel_subscriptions.get(channel_id, set()).copy()

        for connection_id in subscribers:
            await self.send_to_connection(connection_id, message)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Broadcast a message to all connections.

        Args:
            message: The message to broadcast.
        """
        async with self._lock:
            connection_ids = list(self._connections.keys())

        for connection_id in connection_ids:
            await self.send_to_connection(connection_id, message)

    def get_connection_count(self) -> int:
        """Get the number of active connections.

        Returns:
            Number of active connections.
        """
        return len(self._connections)


# Global connection manager
connection_manager = ConnectionManager()


# Message types
class WSMessageType:
    """WebSocket message types."""

    STREAM_CHUNK = "stream_chunk"
    STREAM_END = "stream_end"
    STREAM_ERROR = "stream_error"
    MESSAGE = "message"
    AGENT_UPDATE = "agent_update"
    TASK_UPDATE = "task_update"
    PONG = "pong"


class WSMessage(BaseModel):
    """WebSocket message schema."""

    type: str
    data: dict[str, Any] | None = None
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "type": self.type,
            "data": self.data,
            "timestamp": self.timestamp or datetime.utcnow().isoformat(),
        }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time communication.

    Handles:
    - subscribe: Subscribe to a channel
    - unsubscribe: Unsubscribe from a channel
    - ping: Ping/pong for connection health
    """
    connection_id = await connection_manager.connect(websocket)

    try:
        while True:
            # Receive message
            try:
                raw_data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0,  # Ping interval
                )
                data = json.loads(raw_data)
            except asyncio.TimeoutError:
                # Send ping on timeout
                await connection_manager.send_to_connection(
                    connection_id,
                    WSMessage(type=WSMessageType.PONG).to_dict(),
                )
                continue
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from connection {connection_id}")
                continue

            action = data.get("action")

            if action == "subscribe":
                channel_id = data.get("channel_id")
                if channel_id:
                    await connection_manager.subscribe_to_channel(connection_id, channel_id)
                    await connection_manager.send_to_connection(
                        connection_id,
                        WSMessage(
                            type="subscribed",
                            data={"channel_id": channel_id},
                        ).to_dict(),
                    )

            elif action == "unsubscribe":
                channel_id = data.get("channel_id")
                if channel_id:
                    await connection_manager.unsubscribe_from_channel(connection_id, channel_id)
                    await connection_manager.send_to_connection(
                        connection_id,
                        WSMessage(
                            type="unsubscribed",
                            data={"channel_id": channel_id},
                        ).to_dict(),
                    )

            elif action == "ping":
                await connection_manager.send_to_connection(
                    connection_id,
                    WSMessage(type=WSMessageType.PONG).to_dict(),
                )

            elif action == "send_message":
                channel_id = data.get("channel_id")
                content = data.get("content")
                if channel_id and content:
                    await _route_message_to_agent(connection_id, channel_id, content)

    except WebSocketDisconnect:
        logger.info(f"WebSocket {connection_id} disconnected")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
    finally:
        await connection_manager.disconnect(connection_id)


async def _route_message_to_agent(connection_id: str, channel_id: str, content: str) -> None:
    """Route a message from WebSocket to the correct agent.

    Args:
        connection_id: The WebSocket connection ID.
        channel_id: The channel ID to send from.
        content: The message content.
    """
    from backend.database import db_manager
    from backend.models.message import MessageType, ReceiverType, SenderType
    from backend.services.agent_registry import agent_registry
    from backend.services.channel_service import channel_service

    try:
        async with db_manager.session() as session:
            # Get the channel
            channel = await channel_service.get_channel(session, channel_id)
            if not channel:
                await connection_manager.send_to_connection(
                    connection_id,
                    WSMessage(type="error", data={"error": "Channel not found"}).to_dict(),
                )
                return

            if not channel.resident_agent_id:
                await connection_manager.send_to_connection(
                    connection_id,
                    WSMessage(type="error", data={"error": "No agent bound to channel"}).to_dict(),
                )
                return

            # Get the agent from registry
            agent = agent_registry.get_agent(channel.resident_agent_id)
            if not agent:
                await connection_manager.send_to_connection(
                    connection_id,
                    WSMessage(type="error", data={"error": "Agent not running"}).to_dict(),
                )
                return

            # Create message in database
            message = await message_service.create_message(
                session,
                sender_type=SenderType.CHANNEL,
                sender_id=channel_id,
                receiver_type=ReceiverType.RESIDENT,
                receiver_id=channel.resident_agent_id,
                content=content,
                message_type=MessageType.TEXT,
            )

        # Deliver message to agent's queue
        await agent.receive_message(message)

        # Confirm message was queued
        await connection_manager.send_to_connection(
            connection_id,
            WSMessage(
                type="message_queued",
                data={"message_id": message.id, "channel_id": channel_id},
            ).to_dict(),
        )

        logger.info(f"Message {message.id} routed to agent {channel.resident_agent_id} for channel {channel_id}")

    except Exception as e:
        logger.exception(f"Error routing message to agent: {e}")
        await connection_manager.send_to_connection(
            connection_id,
            WSMessage(type="error", data={"error": str(e)}).to_dict(),
        )


async def broadcast_stream_chunk(
    channel_id: str,
    content: str,
    message_id: str | None = None,
    is_final: bool = False,
) -> None:
    """Broadcast a streaming chunk to a channel.

    Args:
        channel_id: The channel ID.
        content: The content chunk.
        message_id: Optional message ID.
        is_final: Whether this is the final chunk.
    """
    msg_type = WSMessageType.STREAM_END if is_final else WSMessageType.STREAM_CHUNK
    await connection_manager.broadcast_to_channel(
        channel_id,
        WSMessage(
            type=msg_type,
            data={
                "content": content,
                "message_id": message_id,
            },
        ).to_dict(),
    )


async def broadcast_stream_error(channel_id: str, error: str) -> None:
    """Broadcast a streaming error to a channel.

    Args:
        channel_id: The channel ID.
        error: The error message.
    """
    await connection_manager.broadcast_to_channel(
        channel_id,
        WSMessage(
            type=WSMessageType.STREAM_ERROR,
            data={"error": error},
        ).to_dict(),
    )


async def broadcast_agent_update(
    agent_id: str,
    status: str,
    task_id: str | None = None,
) -> None:
    """Broadcast an agent status update.

    Args:
        agent_id: The agent ID.
        status: The new status.
        task_id: Optional task ID.
    """
    await connection_manager.broadcast(
        WSMessage(
            type=WSMessageType.AGENT_UPDATE,
            data={
                "agent_id": agent_id,
                "status": status,
                "task_id": task_id,
            },
        ).to_dict(),
    )


async def broadcast_task_update(
    task_id: str,
    status: str,
    progress: float | None = None,
) -> None:
    """Broadcast a task status update.

    Args:
        task_id: The task ID.
        status: The new status.
        progress: Optional progress percentage.
    """
    await connection_manager.broadcast(
        WSMessage(
            type=WSMessageType.TASK_UPDATE,
            data={
                "task_id": task_id,
                "status": status,
                "progress": progress,
            },
        ).to_dict(),
    )
