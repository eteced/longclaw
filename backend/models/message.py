"""
Message model for LongClaw.
"""
import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class SenderType(str, enum.Enum):
    """Message sender type enumeration."""

    CHANNEL = "channel"
    RESIDENT = "resident"
    OWNER = "owner"
    WORKER = "worker"
    SYSTEM = "system"
    AGENT = "agent"


class ReceiverType(str, enum.Enum):
    """Message receiver type enumeration."""

    CHANNEL = "channel"
    RESIDENT = "resident"
    OWNER = "owner"
    WORKER = "worker"
    USER = "user"
    AGENT = "agent"


class MessageType(str, enum.Enum):
    """Message type enumeration."""

    TEXT = "text"
    TASK = "task"
    REPORT = "report"
    ERROR = "error"
    SYSTEM = "system"
    QUESTION = "question"  # Worker asking Owner for clarification


class Message(Base):
    """Message model for storing all communications."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_conversation", "conversation_id"),
        Index("idx_task", "task_id"),
        Index("idx_sender", "sender_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    sender_type: Mapped[SenderType] = mapped_column(
        Enum(SenderType), nullable=False, index=True
    )
    sender_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    receiver_type: Mapped[ReceiverType] = mapped_column(
        Enum(ReceiverType), nullable=False, index=True
    )
    receiver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType), default=MessageType.TEXT, nullable=False
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON, nullable=True)
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    subtask_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("subtasks.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    conversation: Mapped["Conversation | None"] = relationship(
        "Conversation", back_populates="messages"
    )

    def __repr__(self) -> str:
        """String representation of the Message."""
        return f"<Message(id={self.id}, type={self.message_type}, from={self.sender_type})>"
