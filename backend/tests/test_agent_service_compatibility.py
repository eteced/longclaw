"""
Unit tests for Agent-Service parameter compatibility.

This test suite verifies:
1. Agent parameters match Service expectations
2. Agent persist() calls Service with correct arguments
3. Message creation for agent actions works correctly
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY
import inspect

from backend.agents.base_agent import BaseAgent
from backend.agents.resident_agent import ResidentAgent
from backend.agents.owner_agent import OwnerAgent
from backend.agents.sub_agent import SubAgent
from backend.agents.worker_agent import WorkerAgent
from backend.models.agent import AgentType, AgentStatus
from backend.models.message import SenderType, ReceiverType, MessageType
from backend.services.agent_service import AgentService


class TestAgentServiceParameterCompatibility:
    """Test that Agent parameters match AgentService expectations."""

    @pytest.fixture
    def agent_service(self):
        """Create an AgentService instance."""
        return AgentService()

    def test_agent_service_create_agent_signature(self):
        """Verify AgentService.create_agent signature."""
        sig = inspect.signature(AgentService.create_agent)
        params = list(sig.parameters.keys())

        expected_params = [
            'self', 'session', 'agent_type', 'name',
            'personality', 'parent_agent_id', 'task_id',
            'model_assignment', 'system_prompt'
        ]

        for param in expected_params:
            assert param in params, f"Missing parameter: {param}"

        # Ensure llm_config is NOT in signature
        assert 'llm_config' not in params, "llm_config should not be in create_agent signature"

    def test_base_agent_init_signature(self):
        """Verify BaseAgent.__init__ signature."""
        sig = inspect.signature(BaseAgent.__init__)
        params = list(sig.parameters.keys())

        expected_params = [
            'self', 'agent_id', 'name', 'agent_type',
            'personality', 'system_prompt', 'llm_config',
            'parent_agent_id', 'task_id', 'timeout'
        ]

        for param in expected_params:
            assert param in params, f"Missing parameter: {param}"

    def test_resident_agent_init_signature(self):
        """Verify ResidentAgent.__init__ signature."""
        sig = inspect.signature(ResidentAgent.__init__)
        params = list(sig.parameters.keys())

        # ResidentAgent should accept standard BaseAgent params
        assert 'name' in params
        assert 'personality' in params
        assert 'system_prompt' in params
        assert 'llm_config' in params

    def test_owner_agent_init_signature(self):
        """Verify OwnerAgent.__init__ signature."""
        sig = inspect.signature(OwnerAgent.__init__)
        params = list(sig.parameters.keys())

        # OwnerAgent specific params
        assert 'task_id' in params
        assert 'parent_agent_id' in params
        assert 'timeout' in params
        assert 'max_subagents' in params

        # Should NOT have 'name' param (uses fixed name)
        assert 'name' not in params

    def test_sub_agent_init_signature(self):
        """Verify SubAgent.__init__ signature."""
        sig = inspect.signature(SubAgent.__init__)
        params = list(sig.parameters.keys())

        expected = ['self', 'name', 'task_id', 'parent_agent_id',
                    'description', 'tools', 'timeout']
        for param in expected:
            assert param in params, f"Missing parameter: {param}"

    def test_worker_agent_init_signature(self):
        """Verify WorkerAgent.__init__ signature."""
        sig = inspect.signature(WorkerAgent.__init__)
        params = list(sig.parameters.keys())

        expected = ['self', 'name', 'task_id', 'subtask_id', 'parent_agent_id',
                    'description', 'tools', 'timeout']
        for param in expected:
            assert param in params, f"Missing parameter: {param}"


class TestAgentPersistCompatibility:
    """Test that Agent.persist() calls AgentService with correct parameters."""

    @pytest.mark.asyncio
    async def test_base_agent_persist_uses_model_assignment(self):
        """BaseAgent.persist() should pass llm_config as model_assignment."""
        agent = ResidentAgent()

        with patch('backend.agents.base_agent.db_manager') as mock_db, \
             patch('backend.agents.base_agent.agent_service') as mock_service:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_agent = MagicMock()
            mock_agent.id = "test-agent-id"
            mock_service.create_agent = AsyncMock(return_value=mock_agent)

            # Agent with llm_config
            agent._llm_config = {"provider": "openai", "model": "gpt-4"}
            await agent.persist()

            # Verify create_agent was called with model_assignment, not llm_config
            mock_service.create_agent.assert_called_once()
            call_kwargs = mock_service.create_agent.call_args[1]

            assert 'model_assignment' in call_kwargs, "Should pass model_assignment"
            assert 'llm_config' not in call_kwargs, "Should NOT pass llm_config"
            assert call_kwargs['model_assignment'] == {"provider": "openai", "model": "gpt-4"}

    @pytest.mark.asyncio
    async def test_base_agent_persist_handles_none_llm_config(self):
        """BaseAgent.persist() should handle None llm_config."""
        agent = ResidentAgent()

        with patch('backend.agents.base_agent.db_manager') as mock_db, \
             patch('backend.agents.base_agent.agent_service') as mock_service:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_agent = MagicMock()
            mock_agent.id = "test-agent-id"
            mock_service.create_agent = AsyncMock(return_value=mock_agent)

            # Agent without llm_config
            agent._llm_config = None
            await agent.persist()

            call_kwargs = mock_service.create_agent.call_args[1]
            assert call_kwargs['model_assignment'] is None

    @pytest.mark.asyncio
    async def test_base_agent_persist_all_required_params(self):
        """BaseAgent.persist() should pass all required parameters."""
        agent = ResidentAgent()
        agent._personality = "test personality"
        agent._system_prompt = "test prompt"
        agent._parent_agent_id = "parent-123"
        agent._task_id = "task-456"

        with patch('backend.agents.base_agent.db_manager') as mock_db, \
             patch('backend.agents.base_agent.agent_service') as mock_service:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_agent = MagicMock()
            mock_agent.id = "test-agent-id"
            mock_service.create_agent = AsyncMock(return_value=mock_agent)

            await agent.persist()

            call_kwargs = mock_service.create_agent.call_args[1]

            # Verify all expected params
            assert call_kwargs['agent_type'] == AgentType.RESIDENT
            assert call_kwargs['name'] == "老六"
            assert call_kwargs['personality'] == "test personality"
            assert call_kwargs['parent_agent_id'] == "parent-123"
            assert call_kwargs['task_id'] == "task-456"
            assert call_kwargs['system_prompt'] == "test prompt"


class TestOwnerAgentPersist:
    """Test OwnerAgent persist behavior."""

    @pytest.mark.asyncio
    async def test_owner_agent_persist_updates_task(self):
        """OwnerAgent.persist() should update task.owner_agent_id."""
        agent = OwnerAgent(task_id="task-123")

        async def mock_persist():
            agent._id = "owner-agent-id"
            return "owner-agent-id"

        with patch('backend.agents.owner_agent.db_manager') as mock_db, \
             patch('backend.agents.owner_agent.task_service') as mock_task_service, \
             patch.object(OwnerAgent.__bases__[0], 'persist', new_callable=AsyncMock) as mock_base_persist:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_task_service.update_task = AsyncMock()
            mock_base_persist.side_effect = mock_persist

            # Call OwnerAgent's persist
            result = await agent.persist()

            # Verify task was updated with owner_agent_id
            mock_task_service.update_task.assert_called_once_with(
                mock_session,
                "task-123",
                owner_agent_id="owner-agent-id"
            )
            assert result == "owner-agent-id"


class TestAgentMessageRecording:
    """Test that agents record their actions to messages."""

    @pytest.mark.asyncio
    async def test_base_agent_send_message_creates_record(self):
        """BaseAgent.send_message() should create a message record."""
        agent = ResidentAgent()
        agent._id = "agent-123"

        with patch('backend.agents.base_agent.db_manager') as mock_db, \
             patch('backend.agents.base_agent.message_service') as mock_msg_service:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_message = MagicMock()
            mock_message.id = "msg-123"
            mock_msg_service.create_message = AsyncMock(return_value=mock_message)
            mock_msg_service.publish_message = AsyncMock()

            result = await agent.send_message(
                receiver_type=ReceiverType.CHANNEL,
                receiver_id="channel-456",
                content="Test message",
                message_type=MessageType.TEXT,
            )

            # Verify message was created with correct params
            mock_msg_service.create_message.assert_called_once()
            call_kwargs = mock_msg_service.create_message.call_args[1]

            assert call_kwargs['sender_type'] == SenderType.RESIDENT
            assert call_kwargs['sender_id'] == "agent-123"
            assert call_kwargs['receiver_type'] == ReceiverType.CHANNEL
            assert call_kwargs['receiver_id'] == "channel-456"
            assert call_kwargs['content'] == "Test message"
            assert call_kwargs['message_type'] == MessageType.TEXT

    @pytest.mark.asyncio
    async def test_owner_agent_records_worker_dispatch(self):
        """OwnerAgent should record message when dispatching to WorkerAgent."""
        from backend.agents.owner_agent import SubtaskSpec

        agent = OwnerAgent(task_id="task-123")
        agent._id = "owner-123"

        with patch('backend.agents.owner_agent.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            # Mock WorkerAgent
            mock_worker = MagicMock()
            mock_worker.id = "worker-456"
            mock_worker._name = "Worker-1"
            mock_worker._subtask_id = "subtask-789"
            mock_worker.status = AgentStatus.IDLE
            mock_worker.execute = AsyncMock(return_value="Task result")

            # Mock message_service imported inside _run_worker
            with patch('backend.services.message_service.message_service') as mock_msg_service:
                mock_msg_service.create_message = AsyncMock(return_value=MagicMock())

                spec = SubtaskSpec(
                    id="1",
                    description="Test subtask",
                    tools_needed=["web_search"],
                    priority=0,
                    depends_on=[]
                )

                result = await agent._run_worker(spec, mock_worker)

                # Verify dispatch message was created
                assert mock_msg_service.create_message.call_count >= 1

                # Check first call (dispatch message)
                first_call = mock_msg_service.create_message.call_args_list[0]
                dispatch_kwargs = first_call[1]

                assert dispatch_kwargs['sender_type'] == SenderType.OWNER
                assert dispatch_kwargs['sender_id'] == "owner-123"
                assert dispatch_kwargs['receiver_type'] == ReceiverType.WORKER
                assert dispatch_kwargs['task_id'] == "task-123"

    @pytest.mark.asyncio
    async def test_owner_agent_records_worker_result(self):
        """OwnerAgent should record message when WorkerAgent returns result."""
        from backend.agents.owner_agent import SubtaskSpec

        agent = OwnerAgent(task_id="task-123")
        agent._id = "owner-123"

        with patch('backend.agents.owner_agent.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            # Mock WorkerAgent
            mock_worker = MagicMock()
            mock_worker.id = "worker-456"
            mock_worker._name = "Worker-1"
            mock_worker._subtask_id = "subtask-789"
            mock_worker.status = AgentStatus.IDLE
            mock_worker.execute = AsyncMock(return_value="Task completed successfully")

            with patch('backend.services.message_service.message_service') as mock_msg_service:
                mock_msg_service.create_message = AsyncMock(return_value=MagicMock())

                spec = SubtaskSpec(
                    id="1",
                    description="Test subtask",
                    tools_needed=["web_search"],
                    priority=0,
                    depends_on=[]
                )

                result = await agent._run_worker(spec, mock_worker)

                # Verify result message was created (second call)
                assert mock_msg_service.create_message.call_count >= 2

                # Check second call (result message)
                result_call = mock_msg_service.create_message.call_args_list[1]
                result_kwargs = result_call[1]

                assert result_kwargs['sender_type'] == SenderType.WORKER
                assert result_kwargs['sender_id'] == "worker-456"
                assert result_kwargs['receiver_type'] == ReceiverType.OWNER
                assert result_kwargs['task_id'] == "task-123"

    @pytest.mark.asyncio
    async def test_owner_agent_records_error(self):
        """OwnerAgent should record message when WorkerAgent fails."""
        from backend.agents.owner_agent import SubtaskSpec

        agent = OwnerAgent(task_id="task-123")
        agent._id = "owner-123"

        with patch('backend.agents.owner_agent.db_manager') as mock_db, \
             patch.object(agent, '_update_subtask_status', AsyncMock()):

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            # Mock WorkerAgent that throws error
            mock_worker = MagicMock()
            mock_worker.id = "worker-456"
            mock_worker._name = "Worker-1"
            mock_worker._subtask_id = "subtask-789"
            mock_worker.status = AgentStatus.ERROR
            mock_worker.execute = AsyncMock(side_effect=Exception("Test error"))

            with patch('backend.services.message_service.message_service') as mock_msg_service:
                mock_msg_service.create_message = AsyncMock(return_value=MagicMock())

                spec = SubtaskSpec(
                    id="1",
                    description="Test subtask",
                    tools_needed=["web_search"],
                    priority=0,
                    depends_on=[]
                )

                result = await agent._run_worker(spec, mock_worker)

                # Verify error message was created
                error_calls = [
                    call for call in mock_msg_service.create_message.call_args_list
                    if call[1].get('message_type') == MessageType.ERROR
                ]
                assert len(error_calls) >= 1


class TestAgentStatusManagement:
    """Test agent status management."""

    def test_agent_initial_status(self):
        """Agents should start with IDLE status."""
        resident = ResidentAgent()
        assert resident._status == AgentStatus.IDLE

        owner = OwnerAgent(task_id="test")
        assert owner._status == AgentStatus.IDLE

        sub = SubAgent()
        assert sub._status == AgentStatus.IDLE

        worker = WorkerAgent()
        assert worker._status == AgentStatus.IDLE

    @pytest.mark.asyncio
    async def test_base_agent_update_status(self):
        """BaseAgent._update_status should update status and database."""
        agent = ResidentAgent()
        agent._id = "agent-123"

        with patch('backend.agents.base_agent.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            # Create a proper mock agent for the query result
            mock_db_agent = MagicMock()
            mock_db_agent.status = AgentStatus.IDLE

            # Mock the query chain properly
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_db_agent
            mock_session.execute.return_value = mock_result
            mock_session.commit = AsyncMock()

            await agent._update_status(AgentStatus.RUNNING)

            assert agent._status == AgentStatus.RUNNING
            assert mock_db_agent.status == AgentStatus.RUNNING


class TestAgentTermination:
    """Test agent termination logic."""

    @pytest.mark.asyncio
    async def test_base_agent_check_terminated(self):
        """BaseAgent._check_terminated should check database status."""
        agent = ResidentAgent()
        agent._id = "agent-123"

        with patch('backend.agents.base_agent.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            # Mock terminated status in database
            mock_result = MagicMock()
            mock_db_agent = MagicMock()
            mock_db_agent.status = AgentStatus.TERMINATED
            mock_result.scalar_one_or_none.return_value = mock_db_agent
            mock_session.execute.return_value = mock_result

            is_terminated = await agent._check_terminated()

            assert is_terminated is True

    @pytest.mark.asyncio
    async def test_base_agent_check_not_terminated(self):
        """BaseAgent._check_terminated should return False for running agent."""
        agent = ResidentAgent()
        agent._id = "agent-123"

        with patch('backend.agents.base_agent.db_manager') as mock_db:
            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session

            # Mock running status in database
            mock_result = MagicMock()
            mock_db_agent = MagicMock()
            mock_db_agent.status = AgentStatus.RUNNING
            mock_result.scalar_one_or_none.return_value = mock_db_agent
            mock_session.execute.return_value = mock_result

            is_terminated = await agent._check_terminated()

            assert is_terminated is False

    @pytest.mark.asyncio
    async def test_base_agent_terminate(self):
        """BaseAgent.terminate should set status to TERMINATED."""
        agent = ResidentAgent()
        agent._id = "agent-123"
        agent._run_task = None  # No running task

        with patch.object(agent, '_update_status', AsyncMock()) as mock_update:
            await agent.terminate()

            mock_update.assert_called_once_with(AgentStatus.TERMINATED)


class TestReflectAgentMessageCreation:
    """Test ReflectAgent message creation for interventions."""

    @pytest.mark.asyncio
    async def test_reflect_agent_send_intervention(self):
        """ReflectAgent.send_intervention should create message."""
        from backend.agents.reflect_agent import ReflectAgent

        agent = ReflectAgent()

        with patch('backend.agents.reflect_agent.db_manager') as mock_db, \
             patch('backend.agents.reflect_agent.message_service') as mock_msg_service:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_message = MagicMock()
            mock_msg_service.create_message = AsyncMock(return_value=mock_message)
            mock_msg_service.publish_message = AsyncMock()

            result = await agent.send_intervention(
                agent_id="agent-456",
                message="Are you stuck?"
            )

            call_kwargs = mock_msg_service.create_message.call_args[1]

            assert call_kwargs['sender_type'] == SenderType.SYSTEM
            assert call_kwargs['sender_id'] == agent._id
            assert call_kwargs['receiver_type'] == ReceiverType.AGENT
            assert call_kwargs['receiver_id'] == "agent-456"
            assert call_kwargs['content'] == "Are you stuck?"

    @pytest.mark.asyncio
    async def test_reflect_agent_report_failure_to_parent(self):
        """ReflectAgent.report_failure_to_parent should create message."""
        from backend.agents.reflect_agent import ReflectAgent

        agent = ReflectAgent()

        with patch('backend.agents.reflect_agent.db_manager') as mock_db, \
             patch('backend.agents.reflect_agent.message_service') as mock_msg_service:

            mock_session = AsyncMock()
            mock_db.session.return_value.__aenter__.return_value = mock_session
            mock_message = MagicMock()
            mock_msg_service.create_message = AsyncMock(return_value=mock_message)
            mock_msg_service.publish_message = AsyncMock()

            await agent.report_failure_to_parent(
                agent_id="child-456",
                parent_agent_id="parent-789",
                reason="Timeout exceeded"
            )

            call_kwargs = mock_msg_service.create_message.call_args[1]

            assert call_kwargs['sender_type'] == SenderType.SYSTEM
            assert call_kwargs['receiver_type'] == ReceiverType.AGENT
            assert call_kwargs['receiver_id'] == "parent-789"
            assert "child-456" in call_kwargs['content']
            assert "Timeout exceeded" in call_kwargs['content']
