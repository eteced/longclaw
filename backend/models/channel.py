"""
Channel model for LongClaw.
"""
import enum
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class ChannelType(str, enum.Enum):
    """Channel type enumeration."""

    QQBOT = "qqbot"
    TELEGRAM = "telegram"
    WEB = "web"
    API = "api"


class Channel(Base):
    """Channel model for communication channels."""

    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    channel_type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType), nullable=False, index=True
    )
    config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    resident_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    # Target agent for the current conversation (can be switched)
    target_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    resident_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[resident_agent_id]
    )
    target_agent: Mapped["Agent | None"] = relationship(
        "Agent", foreign_keys=[target_agent_id]
    )
    tasks: Mapped[list["Task"]] = relationship("Task", back_populates="channel")

    def __repr__(self) -> str:
        """String representation of the Channel."""
        return f"<Channel(id={self.id}, type={self.channel_type}, active={self.is_active})>"
