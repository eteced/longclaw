"""
Agent Prompt model for LongClaw.
Stores configurable system prompts for agent types and individual agents.
"""
import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class PromptType(str, enum.Enum):
    """Prompt type enumeration for agent prompts."""

    RESIDENT = "RESIDENT"
    OWNER = "OWNER"
    WORKER = "WORKER"
    SUB = "SUB"


class AgentPrompt(Base):
    """Model for storing configurable system prompts.

    Supports two levels:
    1. Type-level: default prompt for all agents of a specific type
    2. Instance-level: override prompt for a specific agent
    """

    __tablename__ = "agent_prompts"
    __table_args__ = (
        UniqueConstraint("agent_type", name="uk_agent_type"),
        UniqueConstraint("agent_id", name="uk_agent_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_type: Mapped[PromptType | None] = mapped_column(
        Enum(PromptType), nullable=True, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        """String representation of the AgentPrompt."""
        if self.agent_type:
            return f"<AgentPrompt(type={self.agent_type.value})>"
        return f"<AgentPrompt(agent_id={self.agent_id})>"
