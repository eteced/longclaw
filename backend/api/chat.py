"""
Chat API for LongClaw.
Endpoints for web-based chat with resident agents.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select

from backend.agents.resident_agent import ResidentAgent
from backend.database import db_manager
from backend.models.agent import Agent, AgentType
from backend.models.channel import Channel, ChannelType
from backend.models.conversation import Conversation
from backend.models.message import Message, MessageType, SenderType, ReceiverType
from backend.models.subtask import Subtask
from backend.models.task import Task
from backend.services.agent_registry import agent_registry
from backend.services.agent_service import agent_service
from backend.services.channel_service import channel_service
from backend.services.config_service import config_service
from backend.services.message_service import message_service

logger = logging.getLogger(__name__)

router = APIRouter()


# ==================== Request/Response Models ====================

class SendMessageRequest(BaseModel):
    """Request model for sending a message."""

    channel_id: str
    content: str


class SendMessageResponse(BaseModel):
    """Response model for send message."""

    message_id: str
    reply: str
    created_at: str


class ChatMessage(BaseModel):
    """Chat message model."""

    id: str
    sender_type: str
    sender_id: str | None
    content: str | None
    created_at: str


class ChatHistoryResponse(BaseModel):
    """Response model for chat history."""

    channel_id: str
    messages: list[ChatMessage]
    total: int


# ==================== Endpoints ====================

@router.post("/send", response_model=SendMessageResponse)
async def send_message(request: SendMessageRequest) -> SendMessageResponse:
    """Send a message to the resident agent.

    Args:
        request: Send message request.

    Returns:
        Message response with reply from agent.

    Raises:
        HTTPException: If channel not found or agent not available.
    """
    async with db_manager.session() as session:
        # Get the channel
        channel = await channel_service.get_channel(session, request.channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        if not channel.is_active:
            raise HTTPException(status_code=400, detail="Channel is not active")

        if not channel.resident_agent_id:
            raise HTTPException(status_code=400, detail="No resident agent bound to channel")

        # Get the resident agent instance
        agent = agent_registry.get_agent(channel.resident_agent_id)
        if not agent:
            raise HTTPException(status_code=400, detail="Resident agent not running")

        # Create user message
        message_id = str(uuid4())
        user_message = await message_service.create_message(
            session,
            sender_type=SenderType.CHANNEL,
            sender_id=request.channel_id,
            receiver_type=ReceiverType.RESIDENT,
            receiver_id=channel.resident_agent_id,
            content=request.content,
            message_type=MessageType.TEXT,
        )

        logger.info(f"Created user message {user_message.id} for channel {request.channel_id}")

    # Deliver message to agent
    await agent.receive_message(user_message)

    # Get timeout from config
    chat_timeout = await config_service.get_float("resident_chat_timeout", 600.0)

    # Wait for reply (with extended timeout for complex tasks)
    try:
        reply = await agent.wait_for_reply(user_message.id, timeout=chat_timeout)
    except asyncio.TimeoutError:
        logger.warning(f"Timeout waiting for reply to message {user_message.id}")
        reply = "抱歉，我处理时间有点长，请稍后再试~"
    except Exception as e:
        logger.exception(f"Error waiting for reply: {e}")
        reply = f"处理消息时出错: {str(e)}"

    return SendMessageResponse(
        message_id=user_message.id,
        reply=reply,
        created_at=user_message.created_at.isoformat(),
    )


@router.get("/messages/{channel_id}", response_model=ChatHistoryResponse)
async def get_chat_messages(
    channel_id: str,
    limit: int = 50,
    offset: int = 0,
) -> ChatHistoryResponse:
    """Get chat history for a channel.

    Args:
        channel_id: Channel ID.
        limit: Maximum number of messages.
        offset: Offset for pagination.

    Returns:
        Chat history with messages.

    Raises:
        HTTPException: If channel not found.
    """
    async with db_manager.session() as session:
        # Get the channel
        channel = await channel_service.get_channel(session, channel_id)
        if not channel:
            raise HTTPException(status_code=404, detail="Channel not found")

        # Get messages for this channel
        from sqlalchemy import select, desc, or_

        query = (
            select(Message)
            .where(
                or_(
                    Message.sender_id == channel_id,
                    Message.receiver_id == channel_id,
                )
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
            .offset(offset)
        )

        result = await session.execute(query)
        messages = list(result.scalars().all())

        # Get total count
        from sqlalchemy import func
        count_query = select(func.count(Message.id)).where(
            or_(
                Message.sender_id == channel_id,
                Message.receiver_id == channel_id,
            )
        )
        count_result = await session.execute(count_query)
        total = count_result.scalar_one()

        # Convert to response format
        chat_messages = [
            ChatMessage(
                id=msg.id,
                sender_type=msg.sender_type.value,
                sender_id=msg.sender_id,
                content=msg.content,
                created_at=msg.created_at.isoformat(),
            )
            for msg in reversed(messages)  # Reverse to get chronological order
        ]

        return ChatHistoryResponse(
            channel_id=channel_id,
            messages=chat_messages,
            total=total,
        )


@router.get("/web-channel")
async def get_web_channel() -> dict[str, Any]:
    """Get or create the default web channel.

    If no web channel exists, automatically creates one with a resident agent.
    This ensures the system can recover from database cleanup.

    Returns:
        Web channel info.
    """
    async with db_manager.session() as session:
        # Look for existing web channel
        channels = await channel_service.get_channels(
            session,
            channel_type=ChannelType.WEB,
            is_active=True,
            limit=1,
        )

        if channels:
            channel = channels[0]
            # Ensure resident agent is running
            if channel.resident_agent_id:
                await _ensure_resident_agent_running(channel.resident_agent_id)
            return {
                "id": channel.id,
                "channel_type": channel.channel_type.value,
                "resident_agent_id": channel.resident_agent_id,
                "is_active": channel.is_active,
                "created_at": channel.created_at.isoformat(),
            }

        # No web channel found - auto-initialize
        logger.info("No web channel found, auto-initializing...")
        channel = await _auto_initialize_channel_and_agent(session)

        return {
            "id": channel.id,
            "channel_type": channel.channel_type.value,
            "resident_agent_id": channel.resident_agent_id,
            "is_active": channel.is_active,
            "created_at": channel.created_at.isoformat(),
        }


async def _auto_initialize_channel_and_agent(session) -> Any:
    """Auto-initialize web channel and resident agent if missing.

    This is called when the database was cleaned and no channel exists.
    It creates a new resident agent and web channel, then starts the agent.

    Args:
        session: Database session.

    Returns:
        Created channel.
    """
    # Check for existing resident agent in database
    agents = await agent_service.get_agents(
        session,
        agent_type=AgentType.RESIDENT,
        limit=1,
    )

    if agents:
        # Use existing agent
        agent_model = agents[0]
        resident_agent_id = agent_model.id
        logger.info(f"Using existing resident agent: {resident_agent_id}")
    else:
        # Create new resident agent
        resident_agent = ResidentAgent(name="老六")
        await resident_agent.persist()
        resident_agent_id = resident_agent.id
        logger.info(f"Created new resident agent: {resident_agent_id}")

        # Register and start the agent
        agent_registry.register_agent(resident_agent)
        await resident_agent.start()
        logger.info("Resident agent started and registered")

    # Create new web channel
    channel = await channel_service.create_channel(
        session,
        channel_type=ChannelType.WEB,
        resident_agent_id=resident_agent_id,
    )
    logger.info(f"Created new web channel: {channel.id}")

    return channel


async def _ensure_resident_agent_running(agent_id: str) -> None:
    """Ensure the resident agent is running in memory.

    If the agent is not in the registry (e.g., after database cleanup
    while server is running), create and start it.

    Args:
        agent_id: Agent ID to check/start.
    """
    # Check if agent is already running
    if agent_registry.has_agent(agent_id):
        return

    logger.info(f"Resident agent {agent_id} not in registry, starting...")

    try:
        # Create agent instance and load from database
        resident_agent = ResidentAgent(agent_id=agent_id)
        await resident_agent.load(agent_id)

        # Register and start
        agent_registry.register_agent(resident_agent)
        await resident_agent.start()
        logger.info(f"Resident agent {agent_id} started and registered")
    except Exception as e:
        logger.exception(f"Failed to start resident agent {agent_id}: {e}")


# ==================== Initialization Endpoints ====================


class InitResponse(BaseModel):
    """Response model for initialization."""

    success: bool
    message: str
    agent_id: str | None = None
    channel_id: str | None = None


class InitStatusResponse(BaseModel):
    """Response model for initialization status check."""

    initialized: bool
    has_channel: bool
    has_resident_agent: bool


@router.get("/init/status", response_model=InitStatusResponse)
async def check_init_status() -> InitStatusResponse:
    """Check if the database is initialized.

    Returns:
        Status indicating if the database has required data.
    """
    async with db_manager.session() as session:
        # Check if any channel exists
        channel_count = await session.execute(
            select(func.count(Channel.id))
        )
        has_channel = channel_count.scalar_one() > 0

        # Check if any resident agent exists
        agent_count = await session.execute(
            select(func.count(Agent.id)).where(Agent.agent_type == AgentType.RESIDENT)
        )
        has_resident_agent = agent_count.scalar_one() > 0

        return InitStatusResponse(
            initialized=has_channel and has_resident_agent,
            has_channel=has_channel,
            has_resident_agent=has_resident_agent,
        )


@router.post("/init", response_model=InitResponse)
async def initialize_database() -> InitResponse:
    """Initialize the database with default configuration.

    This endpoint clears all data and creates:
    - A default resident agent
    - A default web channel bound to the agent

    WARNING: All existing data will be permanently deleted!

    Returns:
        Initialization result with created resource IDs.
    """
    logger.info("Received database initialization request")

    try:
        async with db_manager.session() as session:
            # Step 1: Clear all tables (respecting foreign key constraints)
            logger.info("Clearing all tables...")

            # Delete in order of dependencies (children first)
            await session.execute(delete(Message))
            await session.execute(delete(Subtask))
            await session.execute(delete(Task))
            await session.execute(delete(Channel))
            await session.execute(delete(Conversation))
            await session.execute(delete(Agent))

            logger.info("All tables cleared")

            # Step 2: Create resident agent
            logger.info("Creating resident agent...")
            agent = await agent_service.create_agent(
                session,
                agent_type=AgentType.RESIDENT,
                name="老六",
                personality="靠谱、友好、有点皮的AI助手",
            )
            logger.info(f"Created resident agent: {agent.id}")

            # Step 3: Create web channel bound to agent
            logger.info("Creating web channel...")
            channel = await channel_service.create_channel(
                session,
                channel_type=ChannelType.WEB,
                resident_agent_id=agent.id,
            )
            logger.info(f"Created web channel: {channel.id}")

            # Step 4: Start the resident agent in memory
            resident_agent = ResidentAgent(agent_id=agent.id, name="老六")
            agent_registry.register_agent(resident_agent)
            await resident_agent.start()
            logger.info(f"Resident agent {agent.id} started")

        return InitResponse(
            success=True,
            message="Database initialized successfully",
            agent_id=agent.id,
            channel_id=channel.id,
        )

    except Exception as e:
        logger.exception(f"Database initialization failed: {e}")
        return InitResponse(
            success=False,
            message=f"Initialization failed: {str(e)}",
        )
