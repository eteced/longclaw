"""
Agent model for LongClaw.
"""
import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class AgentType(str, enum.Enum):
    """Agent type enumeration."""

    RESIDENT = "resident"
    OWNER = "owner"
    WORKER = "worker"
    SUB = "sub"


class AgentStatus(str, enum.Enum):
    """Agent status enumeration."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"  # Worker waiting for OwnerAgent response
    DONE = "done"  # Agent completed its task normally
    TERMINATED = "terminated"  # Agent was terminated by user or system
    ERROR = "error"  # Agent encountered an error


class Agent(Base):
    """Agent model representing an AI agent in the system."""

    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(AgentType), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus), default=AgentStatus.IDLE, nullable=False, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    model_assignment: Mapped[dict[str, Any] | None] = mapped_column(
        "model_assignment", JSON, nullable=True,
        comment="Model assignment: {'provider': 'openai', 'model': 'gpt-4o'}"
    )
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    # Relationships
    parent: Mapped["Agent | None"] = relationship(
        "Agent", remote_side=[id], backref="children"
    )
    task: Mapped["Task | None"] = relationship(
        "Task", back_populates="assigned_agents", foreign_keys=[task_id]
    )
    owned_tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="owner", foreign_keys="[Task.owner_agent_id]"
    )
    knowledge: Mapped[list["Knowledge"]] = relationship(
        "Knowledge", back_populates="agent", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        """String representation of the Agent."""
        return f"<Agent(id={self.id}, name={self.name}, type={self.agent_type}, status={self.status})>"
