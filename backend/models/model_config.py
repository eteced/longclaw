"""
Model configuration for LongClaw.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ModelConfig(Base):
    """Model configuration for LLM providers.

    Providers structure:
    {
        "name": "openai",
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-xxx",
        "service_mode": "parallel",  # Provider-level mode: "parallel" or "serial"
        "models": [
            {
                "name": "gpt-4o",
                "max_context_tokens": 128000
            },
            {
                "name": "gpt-4o-mini",
                "max_context_tokens": 128000
            }
        ]
    }

    Provider fields:
    - name: Provider identifier (e.g., "openai", "deepseek")
    - display_name: Human-readable name for UI
    - base_url: API base URL
    - api_key: API key for authentication
    - service_mode: "parallel" or "serial" - how multiple concurrent requests are handled
    - models: List of available models with their configs

    Model fields:
    - name: Model identifier (e.g., "gpt-4o", "deepseek-chat")
    - max_context_tokens: Maximum context window size for this model
    """

    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True, default="default"
    )
    default_provider: Mapped[str] = mapped_column(String(100), nullable=False, default="openai")
    providers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        """String representation of the ModelConfig."""
        return f"<ModelConfig(id={self.id}, type={self.config_type}, default_provider={self.default_provider})>"
