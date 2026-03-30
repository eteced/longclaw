"""
Messages API for LongClaw.
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.message import Message, MessageType, SenderType, ReceiverType
from backend.services.message_service import message_service

router = APIRouter()


# ==================== Schemas ====================


class MessageCreate(BaseModel):
    """Schema for creating a message."""

    sender_type: SenderType
    sender_id: str | None = None
    receiver_type: ReceiverType
    receiver_id: str | None = None
    content: str
    message_type: MessageType = MessageType.TEXT
    conversation_id: str | None = None
    task_id: str | None = None
    subtask_id: str | None = None
    metadata: dict[str, Any] | None = None


class MessageResponse(BaseModel):
    """Schema for message response."""

    id: str
    conversation_id: str | None
    sender_type: SenderType
    sender_id: str | None
    receiver_type: ReceiverType
    receiver_id: str | None
    message_type: MessageType
    content: str | None
    metadata: dict[str, Any] | None = None  # Maps to message_metadata in ORM
    task_id: str | None
    subtask_id: str | None
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True

    @classmethod
    def model_validate(cls, obj: Any) -> "MessageResponse":
        """Custom validation to handle the metadata field mapping.

        The ORM model has 'message_metadata' attribute but we want to expose it as 'metadata'.
        """
        if hasattr(obj, 'message_metadata'):
            # Create a dict with the correct field name
            data = {
                'id': obj.id,
                'conversation_id': obj.conversation_id,
                'sender_type': obj.sender_type,
                'sender_id': obj.sender_id,
                'receiver_type': obj.receiver_type,
                'receiver_id': obj.receiver_id,
                'message_type': obj.message_type,
                'content': obj.content,
                'metadata': obj.message_metadata,
                'task_id': obj.task_id,
                'subtask_id': obj.subtask_id,
                'created_at': obj.created_at,
            }
            return cls(**data)
        return super().model_validate(obj)


class MessageListResponse(BaseModel):
    """Schema for message list response."""

    items: list[MessageResponse]
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


@router.get("/task/{task_id}", response_model=MessageListResponse)
async def get_task_messages(
    task_id: str,
    limit: int = Query(50, ge=1, le=200, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> MessageListResponse:
    """Get messages for a task.

    Args:
        task_id: Task ID.
        limit: Maximum number of results.
        offset: Offset for pagination.
        session: Database session.

    Returns:
        List of messages.
    """
    messages = await message_service.get_task_messages(
        session, task_id, limit=limit, offset=offset
    )

    return MessageListResponse(
        items=[MessageResponse.model_validate(m) for m in messages],
        limit=limit,
        offset=offset,
    )


@router.get("/conversation/{conversation_id}", response_model=MessageListResponse)
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200, description="Number of results"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    session: AsyncSession = Depends(get_session),
) -> MessageListResponse:
    """Get messages for a conversation.

    Args:
        conversation_id: Conversation ID.
        limit: Maximum number of results.
        offset: Offset for pagination.
        session: Database session.

    Returns:
        List of messages.
    """
    messages = await message_service.get_conversation_messages(
        session, conversation_id, limit=limit, offset=offset
    )

    return MessageListResponse(
        items=[MessageResponse.model_validate(m) for m in messages],
        limit=limit,
        offset=offset,
    )


@router.get("/{message_id}", response_model=MessageResponse)
async def get_message(
    message_id: str,
    session: AsyncSession = Depends(get_session),
) -> Message:
    """Get a message by ID.

    Args:
        message_id: Message ID.
        session: Database session.

    Returns:
        Message details.

    Raises:
        HTTPException: If message not found.
    """
    message = await message_service.get_message(session, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    return message


@router.post("", response_model=MessageResponse, status_code=201)
async def create_message(
    data: MessageCreate,
    session: AsyncSession = Depends(get_session),
) -> Message:
    """Create a new message.

    Args:
        data: Message creation data.
        session: Database session.

    Returns:
        Created message.
    """
    message = await message_service.create_message(
        session,
        sender_type=data.sender_type,
        sender_id=data.sender_id,
        receiver_type=data.receiver_type,
        receiver_id=data.receiver_id,
        content=data.content,
        message_type=data.message_type,
        conversation_id=data.conversation_id,
        task_id=data.task_id,
        subtask_id=data.subtask_id,
        metadata=data.metadata,
    )

    # Publish notification
    await message_service.publish_message(message)

    return message
