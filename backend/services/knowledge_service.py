"""
Knowledge Service for LongClaw.
Manages agent memory storage and retrieval.
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

logger = logging.getLogger(__name__)


class KnowledgeService:
    """Service for managing agent knowledge/memory.

    Features:
    - Store key-value memories
    - Search by keywords
    - Tag-based organization
    - Category-based organization
    """

    async def create_knowledge(
        self,
        session: AsyncSession,
        agent_id: str,
        key: str,
        value: str,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> Knowledge:
        """Create a new knowledge entry.

        Args:
            session: Database session.
            agent_id: Agent ID that owns this knowledge.
            key: Short description/key for lookup.
            value: Full memory content.
            category: Optional category.
            tags: Optional list of tags.

        Returns:
            Created knowledge entry.
        """
        knowledge = Knowledge(
            id=str(uuid4()),
            agent_id=agent_id,
            key=key,
            value=value,
            category=category,
            tags=json.dumps(tags) if tags else None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(knowledge)
        await session.flush()

        logger.info(f"Created knowledge for agent {agent_id}: {key[:50]}...")
        return knowledge

    async def get_knowledge(
        self,
        session: AsyncSession,
        knowledge_id: str,
    ) -> Knowledge | None:
        """Get a knowledge entry by ID.

        Args:
            session: Database session.
            knowledge_id: Knowledge ID.

        Returns:
            Knowledge entry if found, None otherwise.
        """
        result = await session.execute(
            select(Knowledge).where(Knowledge.id == knowledge_id)
        )
        return result.scalar_one_or_none()

    async def get_agent_knowledge(
        self,
        session: AsyncSession,
        agent_id: str,
        limit: int = 100,
    ) -> list[Knowledge]:
        """Get all knowledge entries for an agent.

        Args:
            session: Database session.
            agent_id: Agent ID.
            limit: Maximum number of results.

        Returns:
            List of knowledge entries.
        """
        result = await session.execute(
            select(Knowledge)
            .where(Knowledge.agent_id == agent_id)
            .order_by(Knowledge.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_knowledge(
        self,
        session: AsyncSession,
        agent_id: str,
        query: str,
        limit: int = 5,
    ) -> list[Knowledge]:
        """Search knowledge entries by keyword.

        Args:
            session: Database session.
            agent_id: Agent ID.
            query: Search query (searches in key and value).
            limit: Maximum number of results.

        Returns:
            List of matching knowledge entries.
        """
        # Simple text search in key and value
        search_pattern = f"%{query}%"
        result = await session.execute(
            select(Knowledge)
            .where(Knowledge.agent_id == agent_id)
            .where(
                or_(
                    Knowledge.key.ilike(search_pattern),
                    Knowledge.value.ilike(search_pattern),
                )
            )
            .order_by(Knowledge.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_by_tags(
        self,
        session: AsyncSession,
        agent_id: str,
        tags: list[str],
        limit: int = 10,
    ) -> list[Knowledge]:
        """Search knowledge entries by tags.

        Args:
            session: Database session.
            agent_id: Agent ID.
            tags: List of tags to search for.
            limit: Maximum number of results.

        Returns:
            List of matching knowledge entries.
        """
        # Search for any matching tag
        conditions = [Knowledge.tags.ilike(f'%{tag}%') for tag in tags]
        result = await session.execute(
            select(Knowledge)
            .where(Knowledge.agent_id == agent_id)
            .where(or_(*conditions))
            .order_by(Knowledge.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def search_by_category(
        self,
        session: AsyncSession,
        agent_id: str,
        category: str,
        limit: int = 50,
    ) -> list[Knowledge]:
        """Get knowledge entries by category.

        Args:
            session: Database session.
            agent_id: Agent ID.
            category: Category to filter by.
            limit: Maximum number of results.

        Returns:
            List of knowledge entries.
        """
        result = await session.execute(
            select(Knowledge)
            .where(Knowledge.agent_id == agent_id)
            .where(Knowledge.category == category)
            .order_by(Knowledge.updated_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_knowledge(
        self,
        session: AsyncSession,
        knowledge_id: str,
        key: str | None = None,
        value: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> Knowledge | None:
        """Update a knowledge entry.

        Args:
            session: Database session.
            knowledge_id: Knowledge ID.
            key: Optional new key.
            value: Optional new value.
            category: Optional new category.
            tags: Optional new tags.

        Returns:
            Updated knowledge entry if found, None otherwise.
        """
        knowledge = await self.get_knowledge(session, knowledge_id)
        if not knowledge:
            return None

        if key is not None:
            knowledge.key = key
        if value is not None:
            knowledge.value = value
        if category is not None:
            knowledge.category = category
        if tags is not None:
            knowledge.tags = json.dumps(tags)

        knowledge.updated_at = datetime.utcnow()
        await session.flush()

        logger.debug(f"Updated knowledge {knowledge_id}")
        return knowledge

    async def delete_knowledge(
        self,
        session: AsyncSession,
        knowledge_id: str,
    ) -> bool:
        """Delete a knowledge entry.

        Args:
            session: Database session.
            knowledge_id: Knowledge ID.

        Returns:
            True if deleted, False if not found.
        """
        knowledge = await self.get_knowledge(session, knowledge_id)
        if not knowledge:
            return False

        await session.delete(knowledge)
        await session.flush()

        logger.info(f"Deleted knowledge {knowledge_id}")
        return True

    async def delete_agent_knowledge(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> int:
        """Delete all knowledge entries for an agent.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            Number of deleted entries.
        """
        knowledges = await self.get_agent_knowledge(session, agent_id)
        count = 0
        for knowledge in knowledges:
            await session.delete(knowledge)
            count += 1

        await session.flush()
        logger.info(f"Deleted {count} knowledge entries for agent {agent_id}")
        return count

    async def save_conversation_summary(
        self,
        session: AsyncSession,
        agent_id: str,
        summary: str,
        date_range: str | None = None,
    ) -> Knowledge:
        """Save a conversation summary as knowledge.

        Args:
            session: Database session.
            agent_id: Agent ID.
            summary: Summary content.
            date_range: Optional date range string.

        Returns:
            Created knowledge entry.
        """
        key = f"对话摘要: {date_range or datetime.utcnow().strftime('%Y-%m-%d')}"
        return await self.create_knowledge(
            session,
            agent_id,
            key=key,
            value=summary,
            category="conversation_summary",
            tags=["summary", "conversation"],
        )

    async def save_important_fact(
        self,
        session: AsyncSession,
        agent_id: str,
        fact: str,
        source: str | None = None,
    ) -> Knowledge:
        """Save an important fact as knowledge.

        Args:
            session: Database session.
            agent_id: Agent ID.
            fact: The fact content.
            source: Optional source of the fact.

        Returns:
            Created knowledge entry.
        """
        key = fact[:100] + ("..." if len(fact) > 100 else "")
        tags = ["fact"]
        if source:
            tags.append(source)

        return await self.create_knowledge(
            session,
            agent_id,
            key=key,
            value=fact,
            category="important_fact",
            tags=tags,
        )

    async def get_context_with_memory(
        self,
        session: AsyncSession,
        agent_id: str,
        query: str | None = None,
        max_memories: int | None = 5,
    ) -> str:
        """Get context including relevant memories.

        Args:
            session: Database session.
            agent_id: Agent ID.
            query: Optional query to search for relevant memories.
            max_memories: Maximum number of memories to include. None means unlimited.

        Returns:
            Context string with relevant memories.
        """
        memories = []

        if query:
            # Search for relevant memories
            memories = await self.search_knowledge(
                session, agent_id, query, limit=max_memories
            )

        if not memories:
            # Get recent memories
            memories = await self.get_agent_knowledge(
                session, agent_id, limit=max_memories
            )

        if not memories:
            return ""

        context_parts = ["## 相关记忆\n"]
        for i, memory in enumerate(memories, 1):
            context_parts.append(f"{i}. **{memory.key}**")
            if len(memory.value) > 200:
                context_parts.append(f"   {memory.value[:200]}...")
            else:
                context_parts.append(f"   {memory.value}")
            context_parts.append("")

        return "\n".join(context_parts)


# Global knowledge service instance
knowledge_service = KnowledgeService()
