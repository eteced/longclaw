"""
Reflect Service for LongClaw.
Manages the Reflect Agent and integrates with the scheduler.
"""
import asyncio
import logging
from typing import Any

from backend.agents.reflect_agent import reflect_agent
from backend.database import db_manager
from backend.models.agent import Agent, AgentStatus
from backend.services.config_service import config_service

logger = logging.getLogger(__name__)


class ReflectService:
    """Service for managing the Reflect Agent.

    This service:
    - Starts and stops the Reflect Agent
    - Runs periodic checks on all agents
    - Integrates with the scheduler for automatic checks
    """

    def __init__(self) -> None:
        """Initialize the reflect service."""
        self._running: bool = False
        self._check_task: asyncio.Task[Any] | None = None
        self._check_interval: int = 30  # seconds

    async def start(self) -> None:
        """Start the reflect service."""
        if self._running:
            logger.warning("Reflect service already running")
            return

        self._running = True

        # Start the reflect agent
        await reflect_agent.start()

        # Load configuration
        self._check_interval = await config_service.get_int("reflect_check_interval", 30)

        # Start the check loop
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info("Reflect service started")

    async def stop(self) -> None:
        """Stop the reflect service."""
        self._running = False

        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
            self._check_task = None

        await reflect_agent.stop()
        logger.info("Reflect service stopped")

    async def _check_loop(self) -> None:
        """Main check loop."""
        while self._running:
            try:
                await self._run_check()
            except Exception as e:
                logger.exception(f"Error in reflect check: {e}")

            await asyncio.sleep(self._check_interval)

    async def _run_check(self) -> None:
        """Run a single check cycle."""
        logger.debug("Running reflect check...")

        analyses = await reflect_agent.check_all_agents()

        for analysis in analyses:
            if analysis.needs_intervention:
                logger.info(
                    f"Agent {analysis.agent_id} needs intervention: {analysis.reason}"
                )

                if analysis.should_terminate:
                    # Mark agent as error
                    await self._mark_agent_error(analysis.agent_id, analysis.reason or "")

                    # Report to parent if exists
                    await self._report_to_parent_if_needed(
                        analysis.agent_id,
                        analysis.reason or "Agent terminated due to inactivity",
                    )
                else:
                    # Send intervention message
                    if analysis.intervention_message:
                        await reflect_agent.send_intervention(
                            analysis.agent_id,
                            analysis.intervention_message,
                        )

    async def _mark_agent_error(self, agent_id: str, reason: str) -> None:
        """Mark an agent as error.

        Args:
            agent_id: The agent ID.
            reason: The reason for the error.
        """
        try:
            async with db_manager.session() as session:
                from backend.services.agent_service import agent_service

                await agent_service.update_status(session, agent_id, AgentStatus.ERROR)
                await agent_service.update_agent(
                    session,
                    agent_id,
                    personality=f"Terminated: {reason}",
                )
                logger.warning(f"Marked agent {agent_id} as ERROR: {reason}")
        except Exception as e:
            logger.error(f"Failed to mark agent as error: {e}")

    async def _report_to_parent_if_needed(self, agent_id: str, reason: str) -> None:
        """Report failure to parent agent if exists.

        Args:
            agent_id: The failed agent ID.
            reason: The failure reason.
        """
        try:
            async with db_manager.session() as session:
                from sqlalchemy import select

                result = await session.execute(
                    select(Agent).where(Agent.id == agent_id)
                )
                agent = result.scalar_one_or_none()

                if agent and agent.parent_agent_id:
                    await reflect_agent.report_failure_to_parent(
                        agent_id,
                        agent.parent_agent_id,
                        reason,
                    )
        except Exception as e:
            logger.error(f"Failed to report to parent: {e}")

    async def manual_check(self) -> dict[str, Any]:
        """Run a manual check and return results.

        Returns:
            Check results.
        """
        analyses = await reflect_agent.check_all_agents()

        return {
            "checked_count": len(analyses) + len(reflect_agent._agent_states),
            "interventions": [
                {
                    "agent_id": a.agent_id,
                    "needs_intervention": a.needs_intervention,
                    "is_truly_stuck": a.is_truly_stuck,
                    "should_terminate": a.should_terminate,
                    "reason": a.reason,
                }
                for a in analyses
            ],
        }


# Global reflect service instance
reflect_service = ReflectService()
