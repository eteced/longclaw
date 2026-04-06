"""
Agent Service for LongClaw.
Manages agent lifecycle and persistence.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import Agent, AgentStatus, AgentType

logger = logging.getLogger(__name__)


class AgentService:
    """Service for managing agent lifecycle."""

    async def create_agent(
        self,
        session: AsyncSession,
        agent_type: AgentType,
        name: str,
        personality: str | None = None,
        parent_agent_id: str | None = None,
        task_id: str | None = None,
        model_assignment: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> Agent:
        """Create a new agent.

        Args:
            session: Database session.
            agent_type: Type of agent.
            name: Agent name.
            personality: Optional personality description.
            parent_agent_id: Optional parent agent ID.
            task_id: Optional associated task ID.
            model_assignment: Optional model assignment {'provider': 'openai', 'model': 'gpt-4o'}.
            system_prompt: Optional system prompt.

        Returns:
            Created agent.
        """
        agent = Agent(
            id=str(uuid4()),
            agent_type=agent_type,
            name=name,
            personality=personality,
            status=AgentStatus.IDLE,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            model_assignment=model_assignment,
            system_prompt=system_prompt,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(agent)
        await session.flush()

        logger.info(f"Created agent {agent.id} ({agent_type.value}): {name}")
        return agent

    async def get_agent(self, session: AsyncSession, agent_id: str) -> Agent | None:
        """Get an agent by ID.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            Agent if found, None otherwise.
        """
        result = await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        return result.scalar_one_or_none()

    async def get_agents(
        self,
        session: AsyncSession,
        agent_type: AgentType | None = None,
        status: AgentStatus | None = None,
        parent_agent_id: str | None = None,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Agent]:
        """Get agents with optional filtering.

        Args:
            session: Database session.
            agent_type: Optional agent type filter.
            status: Optional status filter.
            parent_agent_id: Optional parent agent ID filter.
            task_id: Optional task ID filter.
            limit: Maximum number of results.
            offset: Offset for pagination.

        Returns:
            List of agents.
        """
        query = select(Agent)

        if agent_type:
            query = query.where(Agent.agent_type == agent_type)
        if status:
            query = query.where(Agent.status == status)
        if parent_agent_id is not None:
            query = query.where(Agent.parent_agent_id == parent_agent_id)
        if task_id is not None:
            query = query.where(Agent.task_id == task_id)

        query = query.order_by(Agent.created_at.desc()).limit(limit).offset(offset)

        result = await session.execute(query)
        return list(result.scalars().all())

    async def update_status(
        self,
        session: AsyncSession,
        agent_id: str,
        status: AgentStatus,
        error_message: str | None = None,
    ) -> Agent | None:
        """Update an agent's status.

        Args:
            session: Database session.
            agent_id: Agent ID.
            status: New status.
            error_message: Optional error message when status is ERROR.

        Returns:
            Updated agent if found, None otherwise.
        """
        agent = await self.get_agent(session, agent_id)
        if not agent:
            return None

        agent.status = status
        agent.error_message = error_message
        agent.updated_at = datetime.utcnow()

        if status == AgentStatus.TERMINATED:
            agent.terminated_at = datetime.utcnow()

        await session.flush()
        logger.info(f"Updated agent {agent_id} status to {status.value}")
        return agent

    async def update_agent(
        self,
        session: AsyncSession,
        agent_id: str,
        **kwargs: Any,
    ) -> Agent | None:
        """Update an agent's attributes.

        Args:
            session: Database session.
            agent_id: Agent ID.
            **kwargs: Attributes to update.

        Returns:
            Updated agent if found, None otherwise.
        """
        agent = await self.get_agent(session, agent_id)
        if not agent:
            return None

        for key, value in kwargs.items():
            if hasattr(agent, key):
                setattr(agent, key, value)

        agent.updated_at = datetime.utcnow()
        await session.flush()
        logger.debug(f"Updated agent {agent_id}: {list(kwargs.keys())}")
        return agent

    async def terminate_agent(self, session: AsyncSession, agent_id: str) -> Agent | None:
        """Terminate an agent.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            Terminated agent if found, None otherwise.
        """
        return await self.update_status(session, agent_id, AgentStatus.TERMINATED)

    async def get_active_agents(self, session: AsyncSession) -> list[Agent]:
        """Get all active (non-terminated) agents.

        Args:
            session: Database session.

        Returns:
            List of active agents.
        """
        result = await session.execute(
            select(Agent)
            .where(Agent.status != AgentStatus.TERMINATED)
            .order_by(Agent.updated_at.desc())
        )
        return list(result.scalars().all())

    async def get_child_agents(
        self, session: AsyncSession, parent_agent_id: str
    ) -> list[Agent]:
        """Get all child agents of a parent agent.

        Args:
            session: Database session.
            parent_agent_id: Parent agent ID.

        Returns:
            List of child agents.
        """
        result = await session.execute(
            select(Agent).where(Agent.parent_agent_id == parent_agent_id)
        )
        return list(result.scalars().all())

    async def count_agents(
        self,
        session: AsyncSession,
        agent_type: AgentType | None = None,
        status: AgentStatus | None = None,
        task_id: str | None = None,
    ) -> int:
        """Count agents with optional filtering.

        Args:
            session: Database session.
            agent_type: Optional agent type filter.
            status: Optional status filter.
            task_id: Optional task ID filter.

        Returns:
            Count of agents.
        """
        from sqlalchemy import func

        query = select(func.count(Agent.id))

        if agent_type:
            query = query.where(Agent.agent_type == agent_type)
        if status:
            query = query.where(Agent.status == status)
        if task_id is not None:
            query = query.where(Agent.task_id == task_id)

        result = await session.execute(query)
        return result.scalar_one()

    async def touch(self, session: AsyncSession, agent_id: str) -> bool:
        """Update agent's updated_at timestamp without changing status.

        This is used to signal that the agent is still active and processing.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            True if agent was found and updated, False otherwise.
        """
        from sqlalchemy import text

        # Use database's NOW() function to ensure consistent timezone
        result = await session.execute(
            text("UPDATE agents SET updated_at = NOW() WHERE id = :agent_id"),
            {"agent_id": agent_id}
        )
        await session.flush()
        return result.rowcount > 0

    async def delete_agent(self, session: AsyncSession, agent_id: str) -> bool:
        """Delete an agent from the database.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            True if deleted, False otherwise.
        """
        result = await session.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return False
        await session.delete(agent)
        await session.flush()
        logger.info(f"Deleted agent {agent_id}")
        return True


# Global agent service instance
agent_service = AgentService()
