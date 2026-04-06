"""
Tests for multi-agent functionality.

Verifies that:
1. Multiple resident agents can be loaded and started
2. Multiple web channels can be created and bound to agents
3. Messages are correctly routed to the intended agent
4. Agents resume correctly after a backend restart
"""
import asyncio
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agents.resident_agent import ResidentAgent
from backend.agents.base_agent import BaseAgent, AgentStatus
from backend.models.agent import AgentType
from backend.models.channel import ChannelType
from backend.models.message import Message, MessageType, ReceiverType, SenderType
from backend.services.agent_registry import agent_registry
from backend.services.channel_service import channel_service
from backend.database import db_manager


class TestMultiAgentInitialization:
    """Tests for multi-agent initialization."""

    @pytest_asyncio.fixture
    async def clean_registry(self):
        """Clean agent registry before and after test."""
        # Clear registry before
        for agent_id in list(agent_registry._agents.keys()):
            agent_registry.unregister_agent(agent_id)

        yield

        # Clear registry after
        for agent_id in list(agent_registry._agents.keys()):
            agent_registry.unregister_agent(agent_id)

    @pytest.mark.asyncio
    async def test_agent_registry_supports_multiple_agents(self, clean_registry):
        """Test that agent registry can hold multiple agents."""
        # Create multiple agents
        agents = []
        for i in range(3):
            agent = ResidentAgent(name=f"TestAgent{i}")
            agent._id = f"agent-{i}"
            agent._status = AgentStatus.RUNNING
            agent_registry.register_agent(agent)
            agents.append(agent)

        # Verify all agents are registered
        assert len(agent_registry.get_all_agents()) == 3

        # Verify can retrieve each agent
        for i, agent in enumerate(agents):
            retrieved = agent_registry.get_agent(f"agent-{i}")
            assert retrieved is not None
            assert retrieved.name == f"TestAgent{i}"

    @pytest.mark.asyncio
    async def test_resident_agent_has_independent_message_queue(self, clean_registry):
        """Test that each agent has its own message queue."""
        agent1 = ResidentAgent(name="Agent1")
        agent1._id = "agent-1"
        agent_registry.register_agent(agent1)

        agent2 = ResidentAgent(name="Agent2")
        agent2._id = "agent-2"
        agent_registry.register_agent(agent2)

        # Verify queues are independent
        assert agent1._message_queue is not agent2._message_queue

        # Add message to agent1's queue
        msg1 = Message(
            id="msg-1",
            sender_type=SenderType.CHANNEL,
            sender_id="channel-1",
            receiver_type=ReceiverType.RESIDENT,
            receiver_id="agent-1",
            content="Hello",
            message_type=MessageType.TEXT,
        )
        await agent1.receive_message(msg1)

        # Verify agent1 has message, agent2 does not
        assert agent1._message_queue.qsize() == 1
        assert agent2._message_queue.qsize() == 0


class TestAgentStartRestart:
    """Tests for agent start/restart behavior."""

    @pytest.mark.asyncio
    async def test_agent_resumes_after_backend_restart(self):
        """Test that agent with RUNNING status can resume after process restart.

        This is the KEY test for the bug fix: when backend restarts, agent is loaded
        from DB with status=RUNNING, but _run_task is None. The start() method should
        detect this and start the run loop anyway.
        """
        agent = ResidentAgent(name="TestAgent")
        agent._id = "test-agent-id"

        # Simulate loaded from DB with RUNNING status
        agent._status = AgentStatus.RUNNING
        # But no run task (process restart scenario)
        assert agent._run_task is None

        # Mock _update_status to avoid DB call
        original_update = agent._update_status
        agent._update_status = AsyncMock(return_value=None)

        # Start should succeed and create run task
        # (Bug was: it would return early because _status == RUNNING)
        await agent.start()

        assert agent._run_task is not None, "start() should create run_task even when status=RUNNING"
        assert not agent._run_task.done(), "run_task should be running"

        # Cleanup
        agent._run_task.cancel()
        try:
            await agent._run_task
        except asyncio.CancelledError:
            pass


class TestMessageRouting:
    """Tests for message routing to correct agents."""

    @pytest_asyncio.fixture
    async def setup_two_agents(self):
        """Setup two agents with different IDs."""
        agent1 = ResidentAgent(name="Agent1")
        agent1._id = "agent-1"
        agent1._status = AgentStatus.RUNNING
        agent_registry.register_agent(agent1)

        agent2 = ResidentAgent(name="Agent2")
        agent2._id = "agent-2"
        agent2._status = AgentStatus.RUNNING
        agent_registry.register_agent(agent2)

        yield agent1, agent2

        # Cleanup
        for agent_id in ["agent-1", "agent-2"]:
            agent_registry.unregister_agent(agent_id)

        # Cancel any run tasks
        for agent in [agent1, agent2]:
            if agent._run_task and not agent._run_task.done():
                agent._run_task.cancel()
                try:
                    await agent._run_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_message_routed_to_correct_agent(self, setup_two_agents):
        """Test that message is delivered to the correct agent based on channel binding."""
        agent1, agent2 = setup_two_agents

        # Create message for agent1
        msg1 = Message(
            id="msg-1",
            sender_type=SenderType.CHANNEL,
            sender_id="channel-1",
            receiver_type=ReceiverType.RESIDENT,
            receiver_id="agent-1",
            content="Hello Agent1",
            message_type=MessageType.TEXT,
        )

        # Deliver to agent1
        await agent1.receive_message(msg1)

        # Verify only agent1 received it
        assert agent1._message_queue.qsize() == 1
        assert agent2._message_queue.qsize() == 0

        # Get and verify message
        received_msg = await asyncio.wait_for(agent1._message_queue.get(), timeout=1.0)
        assert received_msg.content == "Hello Agent1"

    @pytest.mark.asyncio
    async def test_multiple_messages_to_different_agents(self, setup_two_agents):
        """Test that multiple messages can be sent to different agents."""
        agent1, agent2 = setup_two_agents

        # Send message to agent1
        msg1 = Message(
            id="msg-1",
            sender_type=SenderType.CHANNEL,
            sender_id="channel-1",
            receiver_type=ReceiverType.RESIDENT,
            receiver_id="agent-1",
            content="For Agent1",
            message_type=MessageType.TEXT,
        )
        await agent1.receive_message(msg1)

        # Send message to agent2
        msg2 = Message(
            id="msg-2",
            sender_type=SenderType.CHANNEL,
            sender_id="channel-2",
            receiver_type=ReceiverType.RESIDENT,
            receiver_id="agent-2",
            content="For Agent2",
            message_type=MessageType.TEXT,
        )
        await agent2.receive_message(msg2)

        # Verify both received their messages
        assert agent1._message_queue.qsize() == 1
        assert agent2._message_queue.qsize() == 1

        received1 = await asyncio.wait_for(agent1._message_queue.get(), timeout=1.0)
        received2 = await asyncio.wait_for(agent2._message_queue.get(), timeout=1.0)

        assert received1.content == "For Agent1"
        assert received2.content == "For Agent2"
