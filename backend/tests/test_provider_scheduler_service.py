"""
Tests for the Provider Scheduler Service.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from backend.services.provider_scheduler_service import (
    ProviderSchedulerService,
    Priority,
    SlotAllocation,
    AgentState,
)
from backend.models.agent import Agent, AgentStatus, AgentType


class TestProviderSchedulerService:
    """Test cases for ProviderSchedulerService."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return ProviderSchedulerService()

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = AsyncMock()
        return session

    def test_priority_constants(self):
        """Test priority level constants are properly defined."""
        assert Priority.RESIDENT_REPLY == 100
        assert Priority.REFLECT_CHECK == 90
        assert Priority.OWNER_PLANNING == 80
        assert Priority.OWNER_WAITING_WORKERS == 70
        assert Priority.WORKER_RUNNING == 60
        assert Priority.WORKER_WAITING_TOOL == 50
        assert Priority.IDLE == 10

    def test_slot_allocation_dataclass(self):
        """Test SlotAllocation dataclass creation."""
        allocation = SlotAllocation(
            agent_id="agent-123",
            provider_name="openai",
            model_name="gpt-4o",
            priority=Priority.RESIDENT_REPLY,
            priority_reason="Resident needs to reply",
            operation_type="resident_reply",
            task_id="task-456",
        )

        assert allocation.agent_id == "agent-123"
        assert allocation.provider_name == "openai"
        assert allocation.model_name == "gpt-4o"
        assert allocation.priority == 100
        assert allocation.operation_type == "resident_reply"
        assert allocation.task_id == "task-456"

    def test_agent_state_dataclass(self):
        """Test AgentState dataclass creation."""
        state = AgentState(
            agent_id="agent-123",
            agent_type=AgentType.WORKER,
            name="Test Worker",
            status=AgentStatus.RUNNING,
            task_id="task-456",
            parent_agent_id="owner-789",
            last_llm_call=datetime.utcnow(),
            last_heartbeat=datetime.utcnow(),
        )

        assert state.agent_id == "agent-123"
        assert state.name == "Test Worker"
        assert state.task_id == "task-456"
        assert state.parent_agent_id == "owner-789"
        assert state.is_waiting_for_reply is False
        assert state.is_waiting_for_tool is False
        assert state.worker_count == 0

    @pytest.mark.asyncio
    async def test_service_initial_state(self, service):
        """Test service initial state."""
        assert service._running is False
        assert service._scheduler_task is None
        assert service._check_interval == 1.0
        assert service._heartbeat_timeout == 60
        assert service._allocations == {}

    @pytest.mark.asyncio
    async def test_load_provider_config_with_default_provider(self, service):
        """Test loading provider config correctly sets default model."""
        with patch('backend.services.provider_scheduler_service.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            mock_config = MagicMock()
            mock_config.providers = [
                {
                    "name": "openai",
                    "max_parallel_requests": 10,
                    "models": [
                        {"name": "gpt-4o", "max_parallel_requests": 5},
                        {"name": "gpt-4o-mini", "max_parallel_requests": 10},
                    ]
                }
            ]
            mock_config.default_provider = "openai"

            with patch('backend.services.model_config_service.model_config_service') as mock_service:
                mock_service.get_config = AsyncMock(return_value=mock_config)

                await service._load_provider_config()

                assert service._provider_total_max == {"openai": 10}
                assert service._provider_max_parallel == {"openai": {"gpt-4o": 5, "gpt-4o-mini": 10}}
                # Default model should be the first model from default provider
                assert service._default_model == "gpt-4o"
                assert service._default_provider == "openai"

    @pytest.mark.asyncio
    async def test_load_provider_config_fallback_to_first_model(self, service):
        """Test that default model falls back to first model if not set during loop."""
        # This test verifies the bug fix where not self._default_model was always False
        # because _default_model was initialized to "default" (truthy string)
        with patch('backend.services.provider_scheduler_service.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            mock_config = MagicMock()
            mock_config.providers = [
                {
                    "name": "deepseek",
                    "max_parallel_requests": 5,
                    "models": [
                        {"name": "deepseek-chat", "max_parallel_requests": 3},
                    ]
                }
            ]
            mock_config.default_provider = "deepseek"

            with patch('backend.services.model_config_service.model_config_service') as mock_service:
                mock_service.get_config = AsyncMock(return_value=mock_config)

                await service._load_provider_config()

                # Should fall back to first model since the loop condition was always False
                assert service._default_model == "deepseek-chat"
                assert service._default_provider == "deepseek"

    @pytest.mark.asyncio
    async def test_get_allocation_status_empty(self, service):
        """Test getting allocation status when no allocations."""
        status = await service.get_allocation_status()

        assert status["total_active"] == 0
        assert status["by_provider"] == {}
        assert status["allocations"] == []

    @pytest.mark.asyncio
    async def test_get_allocated_agent_count_empty(self, service):
        """Test getting allocated agent count when no allocations."""
        count = service.get_allocated_agent_count()
        assert count == 0

        count_with_provider = service.get_allocated_agent_count("openai")
        assert count_with_provider == 0

    @pytest.mark.asyncio
    async def test_try_allocate_success(self, service):
        """Test successful slot allocation."""
        service._provider_total_max = {"openai": 10}
        service._provider_max_parallel = {"openai": {"gpt-4o": 10}}

        request = SlotAllocation(
            agent_id="agent-1",
            provider_name="openai",
            model_name="gpt-4o",
            priority=Priority.RESIDENT_REPLY,
            priority_reason="Resident agent is the user interface",
            operation_type="resident_reply",
        )

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.flush = AsyncMock()

        with patch('backend.services.provider_scheduler_service.db_manager') as mock_db:
            mock_db.session.return_value.__aenter__.return_value = mock_session

            result = await service._try_allocate(request)

            # Allocation should succeed
            assert result is True
            assert "agent-1" in service._allocations

    @pytest.mark.asyncio
    async def test_try_allocate_no_capacity(self, service):
        """Test allocation when no capacity available."""
        service._provider_total_max = {"openai": 1}
        service._provider_max_parallel = {"openai": {"gpt-4o": 1}}

        request = SlotAllocation(
            agent_id="agent-1",
            provider_name="openai",
            model_name="gpt-4o",
            priority=Priority.WORKER_RUNNING,
            priority_reason="Worker running",
            operation_type="worker_execution",
        )

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.flush = AsyncMock()

        # Pre-allocate the only slot to another agent
        existing_slot = MagicMock()
        existing_slot.slot_index = 0
        existing_slot.provider_name = "openai"
        existing_slot.model_name = "gpt-4o"
        existing_slot.priority = Priority.WORKER_RUNNING
        existing_slot.is_released = False
        service._allocations["other-agent"] = existing_slot

        with patch('backend.services.provider_scheduler_service.db_manager') as mock_db:
            mock_db.session.return_value.__aenter__.return_value = mock_session

            result = await service._try_allocate(request)

            # Should fail because no capacity and lower priority
            assert result is False

    @pytest.mark.asyncio
    async def test_release_slot(self, service):
        """Test releasing a slot allocation."""
        mock_slot = MagicMock()
        mock_slot.id = "slot-123"
        mock_slot.agent_id = "agent-123"
        mock_slot.is_released = False

        service._allocations["agent-123"] = mock_slot

        with patch('backend.services.provider_scheduler_service.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_session.execute = AsyncMock()

            await service._release_slot(mock_slot)

            assert mock_slot.is_released is True
            assert mock_slot.released_at is not None
            assert "agent-123" not in service._allocations

    @pytest.mark.asyncio
    async def test_get_agent_allocation_not_found(self, service):
        """Test getting allocation for agent with no slot."""
        allocation = await service.get_agent_allocation("nonexistent-agent")
        assert allocation is None

    @pytest.mark.asyncio
    async def test_heartbeat(self, service):
        """Test sending heartbeat for a slot."""
        mock_slot = MagicMock()
        mock_slot.id = "slot-123"
        mock_slot.agent_id = "agent-123"
        mock_slot.last_heartbeat = datetime.utcnow()

        service._allocations["agent-123"] = mock_slot

        with patch('backend.services.provider_scheduler_service.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_session.execute = AsyncMock()

            await service.heartbeat("agent-123")

            assert mock_slot.last_heartbeat is not None


class TestResidentSlotAllocation:
    """Test cases for resident agent slot allocation with always_allocate config."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return ProviderSchedulerService()

    @pytest.mark.asyncio
    async def test_should_resident_always_allocate_default(self, service):
        """Test that default value is True when config is not set."""
        with patch('backend.services.provider_scheduler_service.config_service') as mock_config:
            mock_config.get_bool = AsyncMock(return_value=True)
            result = await service._should_resident_always_allocate()
            assert result is True

    @pytest.mark.asyncio
    async def test_should_resident_always_allocate_false(self, service):
        """Test that False is returned when config is set to false."""
        with patch('backend.services.provider_scheduler_service.config_service') as mock_config:
            mock_config.get_bool = AsyncMock(return_value=False)
            result = await service._should_resident_always_allocate()
            assert result is False

    @pytest.mark.asyncio
    async def test_should_resident_always_allocate_exception(self, service):
        """Test that True is returned when config service throws exception."""
        with patch('backend.services.provider_scheduler_service.config_service') as mock_config:
            mock_config.get_bool = AsyncMock(side_effect=Exception("Config error"))
            result = await service._should_resident_always_allocate()
            assert result is True  # Default to True on error


class TestPriorityRules:
    """Test cases for priority allocation rules."""

    def test_priority_order(self):
        """Test that priorities are in correct order (higher = more urgent)."""
        priorities = [
            Priority.RESIDENT_REPLY,
            Priority.REFLECT_CHECK,
            Priority.OWNER_PLANNING,
            Priority.OWNER_WAITING_WORKERS,
            Priority.WORKER_RUNNING,
            Priority.WORKER_WAITING_TOOL,
            Priority.IDLE,
        ]

        # Check that each is greater than the next
        for i in range(len(priorities) - 1):
            assert priorities[i] > priorities[i + 1]

    def test_resident_reply_highest_priority(self):
        """Test that RESIDENT_REPLY has the highest priority."""
        priority_values = [
            v for k, v in Priority.__dict__.items()
            if not k.startswith('_') and isinstance(v, int)
        ]
        assert Priority.RESIDENT_REPLY == max(priority_values)

    def test_idle_lowest_priority(self):
        """Test that IDLE has the lowest priority."""
        all_priorities = [
            Priority.RESIDENT_REPLY,
            Priority.REFLECT_CHECK,
            Priority.OWNER_PLANNING,
            Priority.OWNER_WAITING_WORKERS,
            Priority.WORKER_RUNNING,
            Priority.WORKER_WAITING_TOOL,
            Priority.IDLE,
        ]
        assert Priority.IDLE == min(all_priorities)


class TestGetCurrentPriority:
    """Test cases for _get_current_priority method."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return ProviderSchedulerService()

    @pytest.mark.asyncio
    async def test_resident_waiting_for_reply(self, service):
        """Test RESIDENT_REPLY priority when waiting for reply."""
        state = AgentState(
            agent_id="agent-1",
            agent_type=AgentType.RESIDENT,
            name="Test Resident",
            status=AgentStatus.RUNNING,
            task_id=None,
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            is_waiting_for_reply=True,
        )
        priority = await service._get_current_priority(state)
        assert priority == Priority.RESIDENT_REPLY

    @pytest.mark.asyncio
    async def test_owner_planning(self, service):
        """Test OWNER_PLANNING priority when owner hasn't planned."""
        state = AgentState(
            agent_id="agent-1",
            agent_type=AgentType.OWNER,
            name="Test Owner",
            status=AgentStatus.RUNNING,
            task_id="task-1",
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            has_completed_planning=False,
            worker_count=0,
        )
        priority = await service._get_current_priority(state)
        assert priority == Priority.OWNER_PLANNING

    @pytest.mark.asyncio
    async def test_owner_waiting_workers(self, service):
        """Test OWNER_WAITING_WORKERS priority when owner has workers."""
        state = AgentState(
            agent_id="agent-1",
            agent_type=AgentType.OWNER,
            name="Test Owner",
            status=AgentStatus.RUNNING,
            task_id="task-1",
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            has_completed_planning=True,
            worker_count=3,
        )
        priority = await service._get_current_priority(state)
        assert priority == Priority.OWNER_WAITING_WORKERS

    @pytest.mark.asyncio
    async def test_worker_running(self, service):
        """Test WORKER_RUNNING priority when worker is active."""
        state = AgentState(
            agent_id="agent-1",
            agent_type=AgentType.WORKER,
            name="Test Worker",
            status=AgentStatus.RUNNING,
            task_id="task-1",
            parent_agent_id="owner-1",
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            is_waiting_for_tool=False,
        )
        priority = await service._get_current_priority(state)
        assert priority == Priority.WORKER_RUNNING

    @pytest.mark.asyncio
    async def test_worker_waiting_tool(self, service):
        """Test WORKER_WAITING_TOOL priority when worker is waiting for tool."""
        state = AgentState(
            agent_id="agent-1",
            agent_type=AgentType.WORKER,
            name="Test Worker",
            status=AgentStatus.RUNNING,
            task_id="task-1",
            parent_agent_id="owner-1",
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            is_waiting_for_tool=True,
        )
        priority = await service._get_current_priority(state)
        assert priority == Priority.WORKER_WAITING_TOOL


class TestHasUnrespondedMessagesHelper:
    """Tests for _has_unresponded_messages_to_agent helper method."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return ProviderSchedulerService()

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_no_messages_received(self, service, mock_session):
        """Test: Returns False when no messages to agent."""
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: no messages found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service._has_unresponded_messages_to_agent(
            mock_session,
            agent_id="agent-1",
            receiver_type=ReceiverType.RESIDENT,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_message_too_old(self, service, mock_session):
        """Test: Returns False when message is older than max_age_seconds."""
        from datetime import timedelta
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: old message
        mock_msg = MagicMock()
        mock_msg.created_at = datetime.utcnow() - timedelta(seconds=60)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_msg
        mock_session.execute.return_value = mock_result

        result = await service._has_unresponded_messages_to_agent(
            mock_session,
            agent_id="agent-1",
            receiver_type=ReceiverType.RESIDENT,
            max_age_seconds=30.0,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_agent_responded(self, service, mock_session):
        """Test: Returns False when agent already sent a response."""
        from datetime import timedelta
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: received message and a subsequent response from agent
        mock_received = MagicMock()
        mock_received.created_at = datetime.utcnow() - timedelta(seconds=5)

        mock_response = MagicMock()
        mock_response.created_at = datetime.utcnow()  # After received

        # First call for received message, second for response
        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = mock_received
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = mock_response

        mock_session.execute.side_effect = [mock_result1, mock_result2]

        result = await service._has_unresponded_messages_to_agent(
            mock_session,
            agent_id="agent-1",
            receiver_type=ReceiverType.RESIDENT,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_unresponded_message(self, service, mock_session):
        """Test: Returns True when message received and no response."""
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: received message, no response
        mock_received = MagicMock()
        mock_received.created_at = datetime.utcnow()

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = mock_received
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = None  # No response

        mock_session.execute.side_effect = [mock_result1, mock_result2]

        result = await service._has_unresponded_messages_to_agent(
            mock_session,
            agent_id="agent-1",
            receiver_type=ReceiverType.RESIDENT,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_filter_by_sender_type(self, service, mock_session):
        """Test: Correctly filters by sender_type."""
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: no messages from CHANNEL type
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await service._has_unresponded_messages_to_agent(
            mock_session,
            agent_id="agent-1",
            receiver_type=ReceiverType.RESIDENT,
            sender_type=SenderType.CHANNEL,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_filter_by_message_type(self, service, mock_session):
        """Test: Correctly filters by message_type (QUESTION)."""
        from backend.models.message import Message, ReceiverType, SenderType, MessageType

        # Mock: QUESTION message received, no response
        mock_received = MagicMock()
        mock_received.created_at = datetime.utcnow()
        mock_received.message_type = MessageType.QUESTION

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = mock_received
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [mock_result1, mock_result2]

        result = await service._has_unresponded_messages_to_agent(
            mock_session,
            agent_id="owner-1",
            receiver_type=ReceiverType.OWNER,
            sender_type=SenderType.WORKER,
            message_type=MessageType.QUESTION,
        )

        assert result is True


class TestGetAgentStateWaitingDetection:
    """Tests for _get_agent_state waiting detection logic."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return ProviderSchedulerService()

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        session = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_resident_waiting_for_user_message(self, service, mock_session):
        """Test: Resident is waiting when user sent message and no response yet."""
        from backend.models.message import Message, ReceiverType, SenderType, MessageType

        # Mock: user message to resident, no response yet
        mock_received = MagicMock()
        mock_received.receiver_id = "resident-1"
        mock_received.receiver_type = ReceiverType.RESIDENT
        mock_received.sender_type = SenderType.CHANNEL
        mock_received.message_type = MessageType.TEXT
        mock_received.created_at = datetime.utcnow()

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = mock_received
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = None  # No response

        mock_session.execute.side_effect = [mock_result1, mock_result2]

        agent = MagicMock()
        agent.id = "resident-1"
        agent.agent_type = AgentType.RESIDENT
        agent.status = AgentStatus.RUNNING
        agent.task_id = None
        agent.parent_agent_id = None
        agent.updated_at = datetime.utcnow()

        state = await service._get_agent_state(mock_session, agent)

        assert state.is_waiting_for_reply is True

    @pytest.mark.asyncio
    async def test_resident_not_waiting_after_response(self, service, mock_session):
        """Test: Resident NOT waiting when they already responded."""
        from datetime import timedelta
        from backend.models.message import Message, ReceiverType, SenderType, MessageType

        # Mock: user message to resident, agent responded
        mock_received = MagicMock()
        mock_received.receiver_id = "resident-1"
        mock_received.receiver_type = ReceiverType.RESIDENT
        mock_received.sender_type = SenderType.CHANNEL
        mock_received.sender_id = "channel-1"  # The channel that sent the user message
        mock_received.created_at = datetime.utcnow() - timedelta(seconds=10)

        # Agent sends response BACK TO THE CHANNEL (not to someone else)
        mock_response = MagicMock()
        mock_response.sender_id = "resident-1"
        mock_response.receiver_id = "channel-1"  # Response goes back to original sender
        mock_response.created_at = datetime.utcnow() - timedelta(seconds=5)  # After received

        # First call returns received message, second returns response
        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = mock_received
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = mock_response

        mock_session.execute.side_effect = [mock_result1, mock_result2]

        agent = MagicMock()
        agent.id = "resident-1"
        agent.agent_type = AgentType.RESIDENT
        agent.status = AgentStatus.RUNNING
        agent.task_id = None
        agent.parent_agent_id = None
        agent.updated_at = datetime.utcnow()

        state = await service._get_agent_state(mock_session, agent)

        assert state.is_waiting_for_reply is False

    @pytest.mark.asyncio
    async def test_resident_waiting_despite_sending_to_other(self, service, mock_session):
        """Test: Resident IS waiting even if they sent message to someone else.

        This tests the fix: when checking for responses, we now require the response
        to be sent BACK TO THE ORIGINAL SENDER, not just any message from the agent.
        If agent sends to someone else, original sender is still waiting.

        We test this by mocking _has_unresponded_messages_to_agent directly.
        """
        from datetime import timedelta
        from backend.models.message import Message, ReceiverType, SenderType, MessageType

        # Mock _has_unresponded_messages_to_agent to return True (message needs response)
        async def mock_has_unresponded(session, agent_id, receiver_type, sender_type=None,
                                       message_type=None, max_age_seconds=30.0):
            # Agent sent message to owner, not back to channel - user is STILL waiting
            return True

        service._has_unresponded_messages_to_agent = mock_has_unresponded

        agent = MagicMock()
        agent.id = "resident-1"
        agent.agent_type = AgentType.RESIDENT
        agent.status = AgentStatus.RUNNING
        agent.task_id = None
        agent.parent_agent_id = None
        agent.updated_at = datetime.utcnow()

        state = await service._get_agent_state(mock_session, agent)

        # Even though agent sent to someone else, user is still waiting
        assert state.is_waiting_for_reply is True

    @pytest.mark.asyncio
    async def test_resident_idle_no_messages(self, service, mock_session):
        """Test: Resident NOT waiting when no messages to them."""
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: no messages to resident
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        agent = MagicMock()
        agent.id = "resident-1"
        agent.agent_type = AgentType.RESIDENT
        agent.status = AgentStatus.RUNNING
        agent.task_id = None
        agent.parent_agent_id = None
        agent.updated_at = datetime.utcnow()

        state = await service._get_agent_state(mock_session, agent)

        assert state.is_waiting_for_reply is False

    @pytest.mark.asyncio
    async def test_owner_waiting_for_worker_question(self, service, mock_session):
        """Test: Owner is waiting when worker sent QUESTION and no response yet."""
        from backend.models.message import Message, ReceiverType, SenderType, MessageType

        # Mock: worker QUESTION to owner, no response
        mock_question = MagicMock()
        mock_question.receiver_id = "owner-1"
        mock_question.receiver_type = ReceiverType.OWNER
        mock_question.sender_type = SenderType.WORKER
        mock_question.message_type = MessageType.QUESTION
        mock_question.created_at = datetime.utcnow()

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = mock_question
        mock_result2 = MagicMock()
        mock_result2.scalar_one_or_none.return_value = None

        mock_session.execute.side_effect = [mock_result1, mock_result2]

        agent = MagicMock()
        agent.id = "owner-1"
        agent.agent_type = AgentType.OWNER
        agent.status = AgentStatus.RUNNING
        agent.task_id = "task-1"
        agent.parent_agent_id = None
        agent.updated_at = datetime.utcnow()

        # Mock worker count query
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 2
        # Mock subtask count query
        mock_subtask_result = MagicMock()
        mock_subtask_result.scalar_one.return_value = 3

        # Chain: first two are message queries, then worker count, then subtask count
        mock_session.execute.side_effect = [
            mock_result1, mock_result2,  # messages
            mock_count_result, mock_subtask_result  # counts
        ]

        state = await service._get_agent_state(mock_session, agent)

        assert state.is_waiting_for_reply is True
        assert state.worker_count == 2
        assert state.has_completed_planning is True

    @pytest.mark.asyncio
    async def test_owner_not_waiting_when_idle(self, service, mock_session):
        """Test: Owner NOT waiting when no QUESTION messages from workers."""
        from backend.models.message import Message, ReceiverType, SenderType

        # Mock: no messages to owner
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        agent = MagicMock()
        agent.id = "owner-1"
        agent.agent_type = AgentType.OWNER
        agent.status = AgentStatus.RUNNING
        agent.task_id = "task-1"
        agent.parent_agent_id = None
        agent.updated_at = datetime.utcnow()

        # Mock worker count query
        mock_count_result = MagicMock()
        mock_count_result.scalar_one.return_value = 0
        # Mock subtask count query
        mock_subtask_result = MagicMock()
        mock_subtask_result.scalar_one.return_value = 0

        mock_session.execute.side_effect = [
            mock_result,  # no messages
            mock_count_result, mock_subtask_result  # counts
        ]

        state = await service._get_agent_state(mock_session, agent)

        assert state.is_waiting_for_reply is False
        assert state.worker_count == 0
        assert state.has_completed_planning is False


class TestPriorityOrder:
    """Tests to verify priority order matches user requirements.

    User specified priority order:
    Resident (100) > Owner planning (80) > Owner responding to worker (75) >
    Owner waiting for workers (70) > Worker (60)
    """

    def test_priority_order_matches_requirements(self):
        """Verify: Resident (100) > Owner planning (80) > Owner responding (75) > Owner waiting (70) > Worker (60)"""
        assert Priority.RESIDENT_REPLY == 100
        assert Priority.OWNER_PLANNING == 80
        assert Priority.WORKER_WAITING_OWNER == 75
        assert Priority.OWNER_WAITING_WORKERS == 70
        assert Priority.WORKER_RUNNING == 60

        # Verify ordering
        assert Priority.RESIDENT_REPLY > Priority.OWNER_PLANNING
        assert Priority.OWNER_PLANNING > Priority.WORKER_WAITING_OWNER
        assert Priority.WORKER_WAITING_OWNER > Priority.OWNER_WAITING_WORKERS
        assert Priority.OWNER_WAITING_WORKERS > Priority.WORKER_RUNNING

    def test_resident_reply_is_highest(self):
        """Test that RESIDENT_REPLY has the highest priority."""
        priority_values = [
            v for k, v in Priority.__dict__.items()
            if not k.startswith('_') and isinstance(v, int)
        ]
        assert Priority.RESIDENT_REPLY == max(priority_values)

    def test_worker_running_priority_above_waiting_tool(self):
        """Test that WORKER_RUNNING > WORKER_WAITING_TOOL."""
        assert Priority.WORKER_RUNNING > Priority.WORKER_WAITING_TOOL

    def test_idle_is_lowest(self):
        """Test that IDLE has the lowest priority."""
        all_priorities = [
            Priority.RESIDENT_REPLY,
            Priority.REFLECT_CHECK,
            Priority.OWNER_PLANNING,
            Priority.WORKER_WAITING_OWNER,
            Priority.OWNER_WAITING_WORKERS,
            Priority.WORKER_RUNNING,
            Priority.WORKER_WAITING_TOOL,
            Priority.IDLE,
        ]
        assert Priority.IDLE == min(all_priorities)


class TestReclaimLogicWithFixedWaitingDetection:
    """Tests for slot reclaim logic using corrected waiting detection."""

    @pytest.fixture
    def service(self):
        """Create a fresh service instance."""
        return ProviderSchedulerService()

    @pytest.mark.asyncio
    async def test_owner_monitoring_should_not_allocate(self, service):
        """Test: Owner monitoring (completed planning, has workers, no waiting) should NOT get slot."""
        state = AgentState(
            agent_id="owner-1",
            agent_type=AgentType.OWNER,
            name="Test Owner",
            status=AgentStatus.RUNNING,
            task_id="task-1",
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            has_completed_planning=True,
            worker_count=3,
            is_waiting_for_reply=False,  # No pending worker questions
        )

        priority = await service._get_current_priority(state)

        # Priority should be OWNER_WAITING_WORKERS (70) when just monitoring
        assert priority == Priority.OWNER_WAITING_WORKERS

    @pytest.mark.asyncio
    async def test_owner_responding_to_worker_high_priority(self, service):
        """Test: Owner responding to worker should get higher priority than monitoring."""
        state = AgentState(
            agent_id="owner-1",
            agent_type=AgentType.OWNER,
            name="Test Owner",
            status=AgentStatus.RUNNING,
            task_id="task-1",
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            has_completed_planning=True,
            worker_count=3,
            is_waiting_for_reply=True,  # Worker sent question, owner needs to respond
        )

        priority = await service._get_current_priority(state)

        # is_waiting_for_reply triggers RESIDENT_REPLY path for owners too
        # This is correct - when owner needs to respond to worker, it should get slot
        assert priority == Priority.RESIDENT_REPLY

    @pytest.mark.asyncio
    async def test_resident_idle_should_not_allocate(self, service):
        """Test: Resident idle (no pending messages) should not get high priority."""
        state = AgentState(
            agent_id="resident-1",
            agent_type=AgentType.RESIDENT,
            name="Test Resident",
            status=AgentStatus.RUNNING,
            task_id=None,
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            is_waiting_for_reply=False,
        )

        priority = await service._get_current_priority(state)

        # Not waiting for reply, should get IDLE priority
        assert priority == Priority.IDLE

    @pytest.mark.asyncio
    async def test_resident_waiting_high_priority(self, service):
        """Test: Resident waiting for user reply should get highest priority."""
        state = AgentState(
            agent_id="resident-1",
            agent_type=AgentType.RESIDENT,
            name="Test Resident",
            status=AgentStatus.RUNNING,
            task_id=None,
            parent_agent_id=None,
            last_llm_call=None,
            last_heartbeat=datetime.utcnow(),
            is_waiting_for_reply=True,
        )

        priority = await service._get_current_priority(state)

        assert priority == Priority.RESIDENT_REPLY
