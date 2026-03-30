"""
System Configuration Model for LongClaw.
Stores configurable system parameters like timeouts.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class SystemConfig(Base):
    """Model for storing system configuration key-value pairs."""

    __tablename__ = "system_configs"

    config_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    config_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def get_typed_value(self) -> Any:
        """Get the typed value based on the config key.

        Returns:
            Typed value (int, float, bool, or str).
        """
        # Try to parse as int first
        try:
            return int(self.config_value)
        except ValueError:
            pass

        # Try to parse as float
        try:
            return float(self.config_value)
        except ValueError:
            pass

        # Check for boolean
        if self.config_value.lower() in ("true", "yes", "1"):
            return True
        if self.config_value.lower() in ("false", "no", "0"):
            return False

        # Return as string
        return self.config_value
