"""
Knowledge model for LongClaw.
Stores key memories that can be retrieved by agents.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class Knowledge(Base):
    """Knowledge model for storing retrievable memories.

    Key features:
    - key: Short description for quick lookup
    - value: Full memory content
    - embedding: Vector embedding for semantic search
    - agent_id: Agent that owns this knowledge
    """

    __tablename__ = "knowledge"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    key: Mapped[str] = mapped_column(String(500), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[str | None] = mapped_column(String(500), nullable=True)  # JSON array
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    agent: Mapped["Agent | None"] = relationship(
        "Agent", back_populates="knowledge"
    )

    def __repr__(self) -> str:
        """String representation of the Knowledge."""
        return f"<Knowledge(id={self.id}, key={self.key[:30]}...)>"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary.

        Returns:
            Dictionary representation.
        """
        import json

        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "tags": json.loads(self.tags) if self.tags else [],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
