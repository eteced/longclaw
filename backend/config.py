"""
Configuration management for LongClaw.
"""
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> Path | None:
    """Find .env file in current directory or parent directories.

    Returns:
        Path to .env file or None if not found.
    """
    # Start from current working directory
    current = Path.cwd()

    # Check current directory and parent directories
    for _ in range(5):  # Max 5 levels up
        env_path = current / ".env"
        if env_path.exists():
            return env_path

        # Also check backend subdirectory if we're at project root
        backend_env = current / "backend" / ".env"
        if backend_env.exists():
            return backend_env

        parent = current.parent
        if parent == current:
            break
        current = parent

    return None


# Find the .env file path
_ENV_FILE = _find_env_file()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        # Use the found .env file, or fall back to .env in current directory
        env_file=str(_ENV_FILE) if _ENV_FILE else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8001, description="Server port")
    debug: bool = Field(default=False, description="Debug mode")

    # Database
    db_host: str = Field(default="localhost", description="Database host")
    db_port: int = Field(default=3306, description="Database port")
    db_name: str = Field(default="longclaw", description="Database name")
    db_user: str = Field(default="longclaw", description="Database user")
    db_password: str = Field(default="", description="Database password")

    # Redis
    redis_host: str = Field(default="localhost", description="Redis host")
    redis_port: int = Field(default=6379, description="Redis port")
    redis_db: int = Field(default=0, description="Redis database number")

    # Auth
    api_key: str = Field(
        default="", description="API key for authentication (set via API_KEY env var)"
    )

    # LLM
    llm_default_provider: str = Field(
        default="openai", description="Default LLM provider"
    )
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", description="OpenAI base URL"
    )
    openai_model: str = Field(default="gpt-4o", description="OpenAI model name")
    deepseek_api_key: str = Field(default="", description="DeepSeek API key")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com/v1", description="DeepSeek base URL"
    )
    deepseek_model: str = Field(
        default="deepseek-chat", description="DeepSeek model name"
    )

    @property
    def database_url(self) -> str:
        """Get the async database URL.

        Returns:
            Async database connection URL.
        """
        return (
            f"mysql+aiomysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def database_url_sync(self) -> str:
        """Get the sync database URL for migrations.

        Returns:
            Sync database connection URL.
        """
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def redis_url(self) -> str:
        """Get the Redis URL.

        Returns:
            Redis connection URL.
        """
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def get_llm_config(self, provider: str | None = None) -> dict[str, Any]:
        """Get LLM configuration for a provider.

        Args:
            provider: Provider name, defaults to default provider.

        Returns:
            LLM configuration dictionary.

        Raises:
            ValueError: If provider is not configured.
        """
        provider = provider or self.llm_default_provider

        if provider == "openai":
            return {
                "api_key": self.openai_api_key,
                "base_url": self.openai_base_url,
                "model": self.openai_model,
            }
        elif provider == "deepseek":
            return {
                "api_key": self.deepseek_api_key,
                "base_url": self.deepseek_base_url,
                "model": self.deepseek_model,
            }
        else:
            raise ValueError(f"Unknown LLM provider: {provider}")


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Returns:
        Settings instance.
    """
    return Settings()
