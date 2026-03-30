"""
Agent Registry for LongClaw.
Manages all active agent instances in memory.
"""
import logging
from typing import Any

from backend.models.agent import AgentStatus

logger = logging.getLogger(__name__)


class AgentRegistry:
    """Registry for managing active agent instances.

    Provides:
    - Agent registration and unregistration
    - Agent lookup by ID
    - List all or running agents
    """

    def __init__(self) -> None:
        """Initialize the agent registry."""
        self._agents: dict[str, Any] = {}  # agent_id -> agent instance

    def register_agent(self, agent: Any) -> None:
        """Register an agent instance.

        Args:
            agent: Agent instance to register.
        """
        if agent.id in self._agents:
            logger.warning(f"Agent {agent.id} already registered, updating reference")
        self._agents[agent.id] = agent
        logger.info(f"Registered agent {agent.id} ({agent.agent_type.value}): {agent.name}")

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent by ID.

        Args:
            agent_id: ID of agent to unregister.

        Returns:
            True if agent was unregistered, False if not found.
        """
        if agent_id in self._agents:
            del self._agents[agent_id]
            logger.info(f"Unregistered agent {agent_id}")
            return True
        logger.warning(f"Agent {agent_id} not found in registry")
        return False

    def get_agent(self, agent_id: str) -> Any | None:
        """Get an agent instance by ID.

        Args:
            agent_id: Agent ID to look up.

        Returns:
            Agent instance if found, None otherwise.
        """
        return self._agents.get(agent_id)

    def get_all_agents(self) -> list[Any]:
        """Get all registered agent instances.

        Returns:
            List of all agent instances.
        """
        return list(self._agents.values())

    def get_running_agents(self) -> list[Any]:
        """Get all running agent instances.

        Returns:
            List of running agent instances.
        """
        return [
            agent for agent in self._agents.values()
            if agent.status == AgentStatus.RUNNING
        ]

    def has_agent(self, agent_id: str) -> bool:
        """Check if an agent is registered.

        Args:
            agent_id: Agent ID to check.

        Returns:
            True if agent is registered, False otherwise.
        """
        return agent_id in self._agents

    def count(self) -> int:
        """Get the number of registered agents.

        Returns:
            Number of registered agents.
        """
        return len(self._agents)

    def clear(self) -> None:
        """Clear all registered agents."""
        self._agents.clear()
        logger.info("Cleared agent registry")


# Global agent registry instance
agent_registry = AgentRegistry()
