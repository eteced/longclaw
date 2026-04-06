"""
Model Slot tracking for LongClaw Provider Scheduler.
Tracks which agent is using which model slot at any given time.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, JSON, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ModelSlot(Base):
    """Model slot allocation tracking.

    This table tracks which agent is currently allocated to which model slot,
    allowing the ProviderScheduler to manage LLM inference resources efficiently.

    A "slot" represents the capacity to run one LLM inference at a time on a specific model.
    The total slots for a model is determined by max_parallel_requests in model config.

    Table tracks:
    - Which agent currently holds a slot
    - What provider/model the slot is for
    - When the slot was allocated
    - Priority level of the allocation
    - Whether the slot is currently active or released
    """

    __tablename__ = "model_slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agents.id"), nullable=False, index=True
    )
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    priority: Mapped[int] = mapped_column(default=0)  # Higher = more priority
    priority_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    is_released: Mapped[bool] = mapped_column(default=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    slot_index: Mapped[int] = mapped_column(default=0)  # Which slot index (0 to max-1)

    # Context about the agent's current operation
    operation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # e.g., "resident_reply", "reflect_check", "owner_planning", "worker_execution"

    task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tasks.id"), nullable=True, index=True
    )
    subtask_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("subtasks.id"), nullable=True
    )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "priority": self.priority,
            "priority_reason": self.priority_reason,
            "allocated_at": self.allocated_at.isoformat() if self.allocated_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "is_active": self.is_active,
            "is_released": self.is_released,
            "released_at": self.released_at.isoformat() if self.released_at else None,
            "slot_index": self.slot_index,
            "operation_type": self.operation_type,
            "task_id": self.task_id,
            "subtask_id": self.subtask_id,
        }

    def __repr__(self) -> str:
        """String representation."""
        status = "active" if self.is_active and not self.is_released else "released"
        return f"<ModelSlot(agent={self.agent_id}, model={self.provider_name}/{self.model_name}, slot={self.slot_index}, status={status})>"