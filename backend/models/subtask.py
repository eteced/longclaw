"""
Subtask model for LongClaw.
"""
import enum
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class SubtaskStatus(str, enum.Enum):
    """Subtask status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Subtask(Base):
    """Subtask model representing a subtask within a task."""

    __tablename__ = "subtasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_subtask_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("subtasks.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[SubtaskStatus] = mapped_column(
        Enum(SubtaskStatus), default=SubtaskStatus.PENDING, nullable=False, index=True
    )
    worker_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    order_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Priority: higher number = higher priority (executed first among parallel tasks)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Dependencies: list of subtask IDs (within the same task) that must complete first
    # Stored as JSON array of subtask spec IDs (e.g., ["1", "2"])
    depends_on: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    task: Mapped["Task"] = relationship("Task", back_populates="subtasks")
    parent_subtask: Mapped["Subtask | None"] = relationship(
        "Subtask", remote_side=[id], backref="child_subtasks"
    )
    worker_agent: Mapped["Agent | None"] = relationship("Agent")

    def __repr__(self) -> str:
        """String representation of the Subtask."""
        return f"<Subtask(id={self.id}, title={self.title}, status={self.status})>"
