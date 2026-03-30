"""
Retrieval Service for LongClaw.
Provides knowledge retrieval for agents.
"""
import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.knowledge import Knowledge
from backend.services.config_service import config_service
from backend.services.embedding_service import embedding_service

logger = logging.getLogger(__name__)


class RetrievalService:
    """Service for retrieving knowledge from the database.

    Features:
    - Keyword search
    - Semantic search (with embeddings)
    - Tag-based filtering
    - Agent-scoped knowledge
    """

    def __init__(self) -> None:
        """Initialize the retrieval service."""
        self._max_results: int = 10
        self._similarity_threshold: float = 0.7

    async def init(self) -> None:
        """Initialize the retrieval service."""
        self._max_results = await config_service.get_int("knowledge_max_results", 10)
        self._similarity_threshold = await config_service.get_float(
            "knowledge_similarity_threshold", 0.7
        )
        logger.info(f"Retrieval service initialized: max_results={self._max_results}")

    async def search(
        self,
        query: str,
        agent_id: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        use_semantic: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search for knowledge matching a query.

        Args:
            query: Search query.
            agent_id: Optional agent ID to scope search.
            category: Optional category filter.
            tags: Optional tag filters.
            use_semantic: Whether to use semantic search.
            limit: Maximum results.

        Returns:
            List of matching knowledge items.
        """
        limit = limit or self._max_results

        async with db_manager.session() as session:
            # Build base query
            stmt = select(Knowledge)

            if agent_id:
                stmt = stmt.where(Knowledge.agent_id == agent_id)

            if category:
                stmt = stmt.where(Knowledge.category == category)

            if tags:
                # Simple tag matching (check if any tag is in the tags string)
                for tag in tags:
                    stmt = stmt.where(Knowledge.tags.contains(tag))

            # Keyword search
            keyword_conditions = []
            for word in query.split()[:5]:  # Limit to 5 keywords
                if len(word) >= 2:  # Skip very short words
                    keyword_conditions.append(
                        or_(
                            Knowledge.key.contains(word),
                            Knowledge.value.contains(word),
                        )
                    )

            if keyword_conditions:
                stmt = stmt.where(or_(*keyword_conditions))

            stmt = stmt.limit(limit * 2)  # Get extra for semantic filtering

            result = await session.execute(stmt)
            knowledge_items = list(result.scalars().all())

            # Semantic search if enabled
            if use_semantic and len(knowledge_items) > 0:
                knowledge_items = await self._semantic_filter(
                    query, knowledge_items, limit
                )

            return [k.to_dict() for k in knowledge_items[:limit]]

    async def _semantic_filter(
        self,
        query: str,
        items: list[Knowledge],
        limit: int,
    ) -> list[Knowledge]:
        """Filter results using semantic similarity.

        Args:
            query: Search query.
            items: Items to filter.
            limit: Maximum results.

        Returns:
            Filtered and sorted items.
        """
        # Get query embedding
        query_embedding = await embedding_service.embed(query)
        if not query_embedding:
            return items[:limit]

        # Calculate similarities
        scored_items = []
        for item in items:
            if item.embedding:
                try:
                    item_embedding = json.loads(item.embedding)
                    similarity = embedding_service.cosine_similarity(
                        query_embedding, item_embedding
                    )
                    if similarity >= self._similarity_threshold:
                        scored_items.append((item, similarity))
                except (json.JSONDecodeError, TypeError):
                    # Invalid embedding, skip semantic scoring
                    scored_items.append((item, 0.0))
            else:
                scored_items.append((item, 0.0))

        # Sort by similarity (descending)
        scored_items.sort(key=lambda x: x[1], reverse=True)
        return [item for item, _ in scored_items[:limit]]

    async def store(
        self,
        key: str,
        value: str,
        agent_id: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        generate_embedding: bool = True,
    ) -> Knowledge:
        """Store a new knowledge item.

        Args:
            key: Short description/key.
            value: Full content.
            agent_id: Optional agent ID.
            category: Optional category.
            tags: Optional tags.
            generate_embedding: Whether to generate embedding.

        Returns:
            Created knowledge item.
        """
        async with db_manager.session() as session:
            knowledge_id = str(uuid4())

            # Generate embedding
            embedding_json = None
            if generate_embedding:
                embedding = await embedding_service.embed(f"{key}\n{value}")
                if embedding:
                    embedding_json = json.dumps(embedding)

            knowledge = Knowledge(
                id=knowledge_id,
                agent_id=agent_id,
                key=key,
                value=value,
                embedding=embedding_json,
                category=category,
                tags=json.dumps(tags) if tags else None,
            )

            session.add(knowledge)
            await session.flush()

            logger.info(f"Stored knowledge: {key[:50]}...")
            return knowledge

    async def delete(self, knowledge_id: str) -> bool:
        """Delete a knowledge item.

        Args:
            knowledge_id: Knowledge ID to delete.

        Returns:
            True if deleted.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(Knowledge).where(Knowledge.id == knowledge_id)
            )
            knowledge = result.scalar_one_or_none()

            if knowledge:
                await session.delete(knowledge)
                await session.flush()
                logger.info(f"Deleted knowledge: {knowledge_id}")
                return True

            return False

    async def get_by_id(self, knowledge_id: str) -> dict[str, Any] | None:
        """Get a knowledge item by ID.

        Args:
            knowledge_id: Knowledge ID.

        Returns:
            Knowledge dict or None.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(Knowledge).where(Knowledge.id == knowledge_id)
            )
            knowledge = result.scalar_one_or_none()
            return knowledge.to_dict() if knowledge else None

    async def get_agent_knowledge(
        self,
        agent_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get all knowledge for an agent.

        Args:
            agent_id: Agent ID.
            limit: Maximum results.

        Returns:
            List of knowledge items.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(Knowledge)
                .where(Knowledge.agent_id == agent_id)
                .order_by(Knowledge.updated_at.desc())
                .limit(limit)
            )
            items = list(result.scalars().all())
            return [k.to_dict() for k in items]

    async def update(
        self,
        knowledge_id: str,
        key: str | None = None,
        value: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        regenerate_embedding: bool = False,
    ) -> Knowledge | None:
        """Update a knowledge item.

        Args:
            knowledge_id: Knowledge ID.
            key: New key.
            value: New value.
            category: New category.
            tags: New tags.
            regenerate_embedding: Whether to regenerate embedding.

        Returns:
            Updated knowledge or None.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(Knowledge).where(Knowledge.id == knowledge_id)
            )
            knowledge = result.scalar_one_or_none()

            if not knowledge:
                return None

            if key:
                knowledge.key = key
            if value:
                knowledge.value = value
            if category:
                knowledge.category = category
            if tags is not None:
                knowledge.tags = json.dumps(tags) if tags else None

            # Regenerate embedding if needed
            if regenerate_embedding or (key or value):
                embedding = await embedding_service.embed(
                    f"{knowledge.key}\n{knowledge.value}"
                )
                if embedding:
                    knowledge.embedding = json.dumps(embedding)

            knowledge.updated_at = datetime.utcnow()
            await session.flush()

            logger.info(f"Updated knowledge: {knowledge_id}")
            return knowledge


# Global retrieval service instance
retrieval_service = RetrievalService()
