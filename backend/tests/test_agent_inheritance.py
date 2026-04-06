"""
Unit tests for Agent inheritance and implementation.

This test suite verifies:
1. All agents correctly inherit from their base classes
2. All abstract methods are properly implemented
3. Import chain works without errors
"""
import pytest
from abc import ABC
from typing import get_type_hints

# Import all agents to verify they can be loaded without errors
from backend.agents.base_agent import BaseAgent
from backend.agents.resident_agent import ResidentAgent
from backend.agents.owner_agent import OwnerAgent
from backend.agents.sub_agent import SubAgent
from backend.agents.worker_agent import WorkerAgent
from backend.agents.reflect_agent import ReflectAgent


class TestAgentInheritance:
    """Test that all agents have correct inheritance."""

    def test_base_agent_is_abstract(self):
        """BaseAgent should be an abstract class."""
        assert ABC in BaseAgent.__bases__ or any(
            ABC in base.__mro__ for base in BaseAgent.__bases__
        )

    def test_resident_agent_inherits_base_agent(self):
        """ResidentAgent should inherit from BaseAgent."""
        assert issubclass(ResidentAgent, BaseAgent)

    def test_owner_agent_inherits_base_agent(self):
        """OwnerAgent should inherit from BaseAgent."""
        assert issubclass(OwnerAgent, BaseAgent)

    def test_sub_agent_inherits_base_agent(self):
        """SubAgent should inherit from BaseAgent."""
        assert issubclass(SubAgent, BaseAgent)

    def test_worker_agent_inherits_sub_agent(self):
        """WorkerAgent should inherit from SubAgent."""
        assert issubclass(WorkerAgent, SubAgent)

    def test_worker_agent_inherits_base_agent(self):
        """WorkerAgent should indirectly inherit from BaseAgent via SubAgent."""
        assert issubclass(WorkerAgent, BaseAgent)

    def test_reflect_agent_is_standalone(self):
        """ReflectAgent is a monitor and does not inherit from BaseAgent."""
        # ReflectAgent is a monitoring agent, intentionally standalone
        assert not issubclass(ReflectAgent, BaseAgent)


class TestAbstractMethodImplementation:
    """Test that all abstract methods are properly implemented."""

    # Abstract methods that BaseAgent subclasses must implement
    REQUIRED_ABSTRACT_METHODS = [
        'on_start',
        'on_stop',
        'on_message',
        'on_idle',
        'generate_summary',
    ]

    def test_resident_agent_implements_abstract_methods(self):
        """ResidentAgent should implement all abstract methods."""
        for method in self.REQUIRED_ABSTRACT_METHODS:
            assert hasattr(ResidentAgent, method), f"ResidentAgent missing {method}"
            # Check it's not still abstract
            assert method not in getattr(ResidentAgent, '__abstractmethods__', set()), \
                f"ResidentAgent.{method} is still abstract"

    def test_owner_agent_implements_abstract_methods(self):
        """OwnerAgent should implement all abstract methods."""
        for method in self.REQUIRED_ABSTRACT_METHODS:
            assert hasattr(OwnerAgent, method), f"OwnerAgent missing {method}"
            assert method not in getattr(OwnerAgent, '__abstractmethods__', set()), \
                f"OwnerAgent.{method} is still abstract"

    def test_sub_agent_implements_abstract_methods(self):
        """SubAgent should implement all abstract methods."""
        for method in self.REQUIRED_ABSTRACT_METHODS:
            assert hasattr(SubAgent, method), f"SubAgent missing {method}"
            assert method not in getattr(SubAgent, '__abstractmethods__', set()), \
                f"SubAgent.{method} is still abstract"

    def test_worker_agent_implements_abstract_methods(self):
        """WorkerAgent should implement all abstract methods (inherited or own)."""
        for method in self.REQUIRED_ABSTRACT_METHODS:
            assert hasattr(WorkerAgent, method), f"WorkerAgent missing {method}"
            assert method not in getattr(WorkerAgent, '__abstractmethods__', set()), \
                f"WorkerAgent.{method} is still abstract"

    def test_can_instantiate_resident_agent(self):
        """ResidentAgent should be instantiable (not abstract)."""
        # This will fail if abstract methods aren't implemented
        agent = ResidentAgent(name="TestResident")
        assert agent is not None
        assert agent._name == "TestResident"

    def test_can_instantiate_owner_agent(self):
        """OwnerAgent should be instantiable (not abstract)."""
        agent = OwnerAgent(task_id="test-task-id")
        assert agent is not None
        assert agent._name == "OwnerAgent"  # OwnerAgent uses fixed name

    def test_can_instantiate_sub_agent(self):
        """SubAgent should be instantiable (not abstract)."""
        agent = SubAgent(name="TestSub")
        assert agent is not None
        assert agent._name == "TestSub"

    def test_can_instantiate_worker_agent(self):
        """WorkerAgent should be instantiable (not abstract)."""
        agent = WorkerAgent(name="TestWorker")
        assert agent is not None
        assert agent._name == "TestWorker"

    def test_can_instantiate_reflect_agent(self):
        """ReflectAgent should be instantiable."""
        agent = ReflectAgent()
        assert agent is not None


class TestAgentProperties:
    """Test that agents have required properties."""

    def test_resident_agent_has_id_property(self):
        """ResidentAgent should have id property."""
        agent = ResidentAgent()
        # Check for _id attribute (id property throws RuntimeError before persist)
        assert hasattr(agent, '_id')

    def test_owner_agent_has_id_property(self):
        """OwnerAgent should have id property."""
        agent = OwnerAgent(task_id="test-task")
        # Check for _id attribute (id property throws RuntimeError before persist)
        assert hasattr(agent, '_id')

    def test_sub_agent_has_id_property(self):
        """SubAgent should have id property."""
        agent = SubAgent()
        # SubAgent generates ID immediately
        assert agent._id is not None
        assert agent._id.startswith("sub_")

    def test_worker_agent_has_id_property(self):
        """WorkerAgent should have id property."""
        agent = WorkerAgent()
        # WorkerAgent ID is set after persist
        assert hasattr(agent, '_id')

    def test_reflect_agent_has_id_property(self):
        """ReflectAgent should have id property."""
        agent = ReflectAgent()
        assert agent._id is not None
        assert agent._id.startswith("reflect-")


class TestAgentImports:
    """Test that all imports work without errors."""

    def test_import_base_agent(self):
        """Should be able to import BaseAgent."""
        from backend.agents.base_agent import BaseAgent
        assert BaseAgent is not None

    def test_import_resident_agent(self):
        """Should be able to import ResidentAgent."""
        from backend.agents.resident_agent import ResidentAgent
        assert ResidentAgent is not None

    def test_import_owner_agent(self):
        """Should be able to import OwnerAgent."""
        from backend.agents.owner_agent import OwnerAgent
        assert OwnerAgent is not None

    def test_import_sub_agent(self):
        """Should be able to import SubAgent."""
        from backend.agents.sub_agent import SubAgent
        assert SubAgent is not None

    def test_import_worker_agent(self):
        """Should be able to import WorkerAgent."""
        from backend.agents.worker_agent import WorkerAgent
        assert WorkerAgent is not None

    def test_import_reflect_agent(self):
        """Should be able to import ReflectAgent."""
        from backend.agents.reflect_agent import ReflectAgent
        assert ReflectAgent is not None

    def test_import_all_agents_together(self):
        """Should be able to import all agents in one go."""
        from backend.agents.base_agent import BaseAgent
        from backend.agents.resident_agent import ResidentAgent
        from backend.agents.owner_agent import OwnerAgent
        from backend.agents.sub_agent import SubAgent
        from backend.agents.worker_agent import WorkerAgent
        from backend.agents.reflect_agent import ReflectAgent

        # Verify all are classes
        assert isinstance(BaseAgent, type)
        assert isinstance(ResidentAgent, type)
        assert isinstance(OwnerAgent, type)
        assert isinstance(SubAgent, type)
        assert isinstance(WorkerAgent, type)
        assert isinstance(ReflectAgent, type)


class TestAgentMethodSignatures:
    """Test that agent methods have correct signatures."""

    def test_resident_agent_on_start_is_async(self):
        """ResidentAgent.on_start should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(ResidentAgent.on_start)

    def test_resident_agent_on_stop_is_async(self):
        """ResidentAgent.on_stop should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(ResidentAgent.on_stop)

    def test_resident_agent_on_message_is_async(self):
        """ResidentAgent.on_message should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(ResidentAgent.on_message)

    def test_resident_agent_on_idle_is_async(self):
        """ResidentAgent.on_idle should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(ResidentAgent.on_idle)

    def test_resident_agent_generate_summary_is_async(self):
        """ResidentAgent.generate_summary should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(ResidentAgent.generate_summary)

    # Similar tests for OwnerAgent
    def test_owner_agent_on_start_is_async(self):
        """OwnerAgent.on_start should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(OwnerAgent.on_start)

    def test_owner_agent_on_stop_is_async(self):
        """OwnerAgent.on_stop should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(OwnerAgent.on_stop)

    def test_owner_agent_on_message_is_async(self):
        """OwnerAgent.on_message should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(OwnerAgent.on_message)

    def test_owner_agent_on_idle_is_async(self):
        """OwnerAgent.on_idle should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(OwnerAgent.on_idle)

    def test_owner_agent_generate_summary_is_async(self):
        """OwnerAgent.generate_summary should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(OwnerAgent.generate_summary)

    # Similar tests for SubAgent
    def test_sub_agent_on_start_is_async(self):
        """SubAgent.on_start should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(SubAgent.on_start)

    def test_sub_agent_on_stop_is_async(self):
        """SubAgent.on_stop should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(SubAgent.on_stop)

    def test_sub_agent_on_message_is_async(self):
        """SubAgent.on_message should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(SubAgent.on_message)

    def test_sub_agent_on_idle_is_async(self):
        """SubAgent.on_idle should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(SubAgent.on_idle)

    def test_sub_agent_generate_summary_is_async(self):
        """SubAgent.generate_summary should be an async method."""
        import inspect
        assert inspect.iscoroutinefunction(SubAgent.generate_summary)


class TestReflectAgentStandalone:
    """Test ReflectAgent as a standalone monitoring agent."""

    def test_reflect_agent_has_check_all_agents(self):
        """ReflectAgent should have check_all_agents method."""
        agent = ReflectAgent()
        assert hasattr(agent, 'check_all_agents')

    def test_reflect_agent_has_send_intervention(self):
        """ReflectAgent should have send_intervention method."""
        agent = ReflectAgent()
        assert hasattr(agent, 'send_intervention')

    def test_reflect_agent_has_start_stop(self):
        """ReflectAgent should have start and stop methods."""
        agent = ReflectAgent()
        assert hasattr(agent, 'start')
        assert hasattr(agent, 'stop')

    def test_reflect_agent_start_is_async(self):
        """ReflectAgent.start should be async."""
        import inspect
        assert inspect.iscoroutinefunction(ReflectAgent.start)

    def test_reflect_agent_stop_is_async(self):
        """ReflectAgent.stop should be async."""
        import inspect
        assert inspect.iscoroutinefunction(ReflectAgent.stop)


class TestAgentTypeAttributes:
    """Test that agents have correct type attributes."""

    def test_resident_agent_type(self):
        """ResidentAgent should have correct agent type."""
        from backend.models.agent import AgentType
        agent = ResidentAgent()
        assert agent._agent_type == AgentType.RESIDENT

    def test_owner_agent_type(self):
        """OwnerAgent should have correct agent type."""
        from backend.models.agent import AgentType
        agent = OwnerAgent(task_id="test")
        assert agent._agent_type == AgentType.OWNER

    def test_sub_agent_type(self):
        """SubAgent should have correct agent type."""
        from backend.models.agent import AgentType
        agent = SubAgent()
        assert agent._agent_type == AgentType.WORKER

    def test_worker_agent_type(self):
        """WorkerAgent should have correct agent type."""
        from backend.models.agent import AgentType
        agent = WorkerAgent()
        assert agent._agent_type == AgentType.WORKER


class TestAgentCancellationAttributes:
    """Test that SubAgent and WorkerAgent have cancellation attributes."""

    def test_sub_agent_has_cancellation_event(self):
        """SubAgent should have _cancellation_event attribute."""
        agent = SubAgent()
        assert hasattr(agent, '_cancellation_event')
        import asyncio
        assert isinstance(agent._cancellation_event, asyncio.Event)

    def test_sub_agent_has_cancel_requested_flag(self):
        """SubAgent should have _cancel_requested flag."""
        agent = SubAgent()
        assert hasattr(agent, '_cancel_requested')
        assert agent._cancel_requested is False

    def test_worker_agent_has_cancellation_event(self):
        """WorkerAgent should have _cancellation_event attribute (inherited)."""
        agent = WorkerAgent()
        assert hasattr(agent, '_cancellation_event')
        import asyncio
        assert isinstance(agent._cancellation_event, asyncio.Event)

    def test_worker_agent_has_cancel_requested_flag(self):
        """WorkerAgent should have _cancel_requested flag (inherited)."""
        agent = WorkerAgent()
        assert hasattr(agent, '_cancel_requested')
        assert agent._cancel_requested is False
