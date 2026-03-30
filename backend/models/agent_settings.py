"""
Agent Settings model for LongClaw.
Stores configurable system prompts and model assignments for agent types and individual agents.
Replaces AgentPrompt with extended functionality.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base
from backend.models.agent import AgentType


class AgentSettings(Base):
    """Model for storing agent settings.

    Supports two levels:
    1. Type-level: default settings for all agents of a specific type
    2. Instance-level: override settings for a specific agent

    Each setting includes:
    - system_prompt: The agent's system prompt
    - provider_name: The LLM provider to use (e.g., "openai", "deepseek")
    - model_name: The specific model to use (e.g., "gpt-4o")
    - max_context_tokens: Maximum context window for this agent type/instance
    """

    __tablename__ = "agent_settings"
    __table_args__ = (
        UniqueConstraint("agent_type", name="uk_agent_settings_type"),
        UniqueConstraint("agent_id", name="uk_agent_settings_agent"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_type: Mapped[AgentType | None] = mapped_column(
        Enum(AgentType), nullable=True, index=True
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )

    # Prompt configuration
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)

    # Model configuration
    provider_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Context limit for this agent type/instance (overrides model's default)
    max_context_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        """String representation of the AgentSettings."""
        if self.agent_type:
            return f"<AgentSettings(type={self.agent_type.value}, provider={self.provider_name}, model={self.model_name})>"
        return f"<AgentSettings(agent_id={self.agent_id}, provider={self.provider_name}, model={self.model_name})>"
