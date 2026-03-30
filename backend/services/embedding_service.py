"""
Embedding Service for LongClaw.
Generates vector embeddings for semantic search.
"""
import json
import logging
from typing import Any

import httpx

from backend.config import get_settings
from backend.services.llm_service import get_db_config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Service for generating text embeddings.

    Uses the configured LLM provider's embedding API.
    Supports OpenAI-compatible embedding endpoints.
    """

    def __init__(self) -> None:
        """Initialize the embedding service."""
        self._http_client: httpx.AsyncClient | None = None
        self._embedding_model: str = "text-embedding-3-small"
        self._embedding_dimension: int = 1536

    async def init(self) -> None:
        """Initialize the HTTP client."""
        self._http_client = httpx.AsyncClient(timeout=30.0)

        # Get embedding model from config
        db_config = get_db_config()
        if db_config:
            providers = db_config.get("providers", {})
            for name, provider in providers.items():
                embedding_model = provider.get("embedding_model")
                if embedding_model:
                    self._embedding_model = embedding_model
                    break

        logger.info(f"Embedding service initialized with model: {self._embedding_model}")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

    def _get_config(self) -> tuple[str, str]:
        """Get embedding API configuration.

        Returns:
            Tuple of (base_url, api_key).
        """
        db_config = get_db_config()
        if db_config:
            providers = db_config.get("providers", {})
            default_provider = db_config.get("default_provider", "openai")

            if default_provider in providers:
                p = providers[default_provider]
                return (
                    p.get("base_url", "https://api.openai.com/v1"),
                    p.get("api_key", ""),
                )

        # Fallback to settings
        settings = get_settings()
        return settings.openai_base_url, settings.openai_api_key

    async def embed(self, text: str) -> list[float] | None:
        """Generate embedding for text.

        Args:
            text: Text to embed.

        Returns:
            Embedding vector or None if failed.
        """
        if not self._http_client:
            return None

        if not text or not text.strip():
            return None

        base_url, api_key = self._get_config()
        url = f"{base_url.rstrip('/')}/embeddings"

        try:
            response = await self._http_client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": text[:8000],  # Limit input length
                    "model": self._embedding_model,
                },
            )
            response.raise_for_status()

            data = response.json()
            if "data" in data and len(data["data"]) > 0:
                return data["data"][0]["embedding"]

            logger.warning(f"No embedding in response: {data}")
            return None

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            return None

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embeddings for multiple texts.

        Args:
            texts: Texts to embed.

        Returns:
            List of embedding vectors (or None for failed items).
        """
        if not self._http_client:
            return [None] * len(texts)

        # Filter empty texts
        valid_texts = [t[:8000] if t else "" for t in texts]
        valid_texts = [t if t.strip() else "empty" for t in valid_texts]

        base_url, api_key = self._get_config()
        url = f"{base_url.rstrip('/')}/embeddings"

        try:
            response = await self._http_client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": valid_texts,
                    "model": self._embedding_model,
                },
            )
            response.raise_for_status()

            data = response.json()
            if "data" in data:
                # Sort by index to maintain order
                sorted_data = sorted(data["data"], key=lambda x: x.get("index", 0))
                return [item.get("embedding") for item in sorted_data]

            return [None] * len(texts)

        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            return [None] * len(texts)

    def cosine_similarity(
        self,
        vec1: list[float],
        vec2: list[float],
    ) -> float:
        """Calculate cosine similarity between two vectors.

        Args:
            vec1: First vector.
            vec2: Second vector.

        Returns:
            Similarity score between -1 and 1.
        """
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


# Global embedding service instance
embedding_service = EmbeddingService()
