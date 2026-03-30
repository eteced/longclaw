"""
Tests for LongClaw API endpoints.
Tests the fixed bugs:
- BUG-A: /api/messages/task/{id} 500 error
- BUG-B: Tasks PROGRESS column display error
- BUG-D: Agents page All Types filter
- BUG-E: Subtask progress always 0%
"""
import asyncio
import os
import sys
from datetime import datetime
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import select

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.database import Base, db_manager
from backend.models.agent import Agent, AgentType, AgentStatus
from backend.models.task import Task, TaskStatus
from backend.models.subtask import Subtask, SubtaskStatus
from backend.models.message import Message, SenderType, ReceiverType, MessageType
from backend.config import get_settings
from backend.main import app  # Import the FastAPI app


# Use SQLite in-memory database for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(TEST_DB_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = async_sessionmaker(test_engine, expire_on_commit=False)

    async with async_session() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_engine) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""
    # Override db_manager's engine for tests
    db_manager._engine = test_engine
    db_manager._session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Set API key header
        settings = get_settings()
        ac.headers["X-API-Key"] = settings.api_key
        yield ac


@pytest_asyncio.fixture
async def sample_task(test_session: AsyncSession) -> Task:
    """Create a sample task with subtasks."""
    now = datetime.utcnow()
    task = Task(
        id=str(uuid4()),
        title="Test Task",
        description="A test task for API testing",
        status=TaskStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    test_session.add(task)
    await test_session.flush()

    # Create subtasks with different statuses
    subtasks = []
    for i, status in enumerate([
        SubtaskStatus.COMPLETED,
        SubtaskStatus.COMPLETED,
        SubtaskStatus.RUNNING,
        SubtaskStatus.PENDING,
        SubtaskStatus.FAILED,
    ]):
        subtask = Subtask(
            id=str(uuid4()),
            task_id=task.id,
            title=f"Subtask {i}",
            status=status,
            order_index=i,
            created_at=now,
        )
        subtasks.append(subtask)
    test_session.add_all(subtasks)
    await test_session.commit()

    return task


@pytest_asyncio.fixture
async def sample_agents(test_session: AsyncSession) -> dict:
    """Create sample agents for testing."""
    now = datetime.utcnow()

    # Create Resident Agent
    resident = Agent(
        id=str(uuid4()),
        agent_type=AgentType.RESIDENT,
        name="Test Resident",
        status=AgentStatus.RUNNING,
        created_at=now,
        updated_at=now,
    )
    test_session.add(resident)
    await test_session.flush()

    # Create Owner Agent with parent
    owner = Agent(
        id=str(uuid4()),
        agent_type=AgentType.OWNER,
        name="Test Owner",
        status=AgentStatus.RUNNING,
        parent_agent_id=resident.id,
        created_at=now,
        updated_at=now,
    )
    test_session.add(owner)
    await test_session.flush()

    # Create Worker Agents with parent
    workers = []
    for i in range(2):
        worker = Agent(
            id=str(uuid4()),
            agent_type=AgentType.WORKER,
            name=f"Test Worker {i}",
            status=AgentStatus.RUNNING,
            parent_agent_id=owner.id,
            created_at=now,
            updated_at=now,
        )
        test_session.add(worker)
        workers.append(worker)

    await test_session.commit()

    return {
        "resident": resident,
        "owner": owner,
        "workers": workers,
    }


@pytest_asyncio.fixture
async def sample_messages(test_session: AsyncSession, sample_task: Task) -> list:
    """Create sample messages for testing."""
    now = datetime.utcnow()
    messages = [
        Message(
            id=str(uuid4()),
            sender_type=SenderType.OWNER,
            sender_id="owner-1",
            receiver_type=ReceiverType.WORKER,
            receiver_id="worker-1",
            message_type=MessageType.TEXT,
            content="Test message 1",
            task_id=sample_task.id,
            created_at=now,
        ),
        Message(
            id=str(uuid4()),
            sender_type=SenderType.WORKER,
            sender_id="worker-1",
            receiver_type=ReceiverType.OWNER,
            receiver_id="owner-1",
            message_type=MessageType.TEXT,
            content="Test message 2",
            task_id=sample_task.id,
            created_at=now,
        ),
    ]
    test_session.add_all(messages)
    await test_session.commit()

    return messages


class TestMessagesAPI:
    """Tests for Messages API (BUG-A fix)."""

    @pytest.mark.asyncio
    async def test_get_task_messages_success(
        self,
        client: AsyncClient,
        sample_task: Task,
        sample_messages: list,
    ):
        """Test that /api/messages/task/{id} returns 200, not 500."""
        response = await client.get(f"/api/messages/task/{sample_task.id}")

        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

        data = response.json()
        assert "items" in data
        assert "limit" in data
        assert "offset" in data
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_message_metadata_field(
        self,
        client: AsyncClient,
        sample_task: Task,
        test_session: AsyncSession,
    ):
        """Test that message metadata field is properly serialized."""
        now = datetime.utcnow()
        # Create message with metadata
        msg = Message(
            id=str(uuid4()),
            sender_type=SenderType.OWNER,
            sender_id="owner-1",
            receiver_type=ReceiverType.WORKER,
            receiver_id="worker-1",
            message_type=MessageType.TEXT,
            content="Test message with metadata",
            task_id=sample_task.id,
            message_metadata={"key": "value", "nested": {"a": 1}},
            created_at=now,
        )
        test_session.add(msg)
        await test_session.commit()

        response = await client.get(f"/api/messages/task/{sample_task.id}")

        assert response.status_code == 200
        data = response.json()

        # Find the message with metadata
        msg_data = next((m for m in data["items"] if "metadata" in m.get("content", "") or m.get("metadata")), None)
        if msg_data:
            assert "metadata" in msg_data, "metadata field should be present in response"


class TestTasksAPI:
    """Tests for Tasks API (BUG-B, BUG-E fixes)."""

    @pytest.mark.asyncio
    async def test_task_list_includes_subtask_stats(
        self,
        client: AsyncClient,
        sample_task: Task,
    ):
        """Test that task list includes subtask_stats field."""
        response = await client.get("/api/tasks")

        assert response.status_code == 200
        data = response.json()

        assert "items" in data
        if len(data["items"]) > 0:
            task = data["items"][0]
            assert "subtask_stats" in task, "subtask_stats field should be present"

            stats = task["subtask_stats"]
            assert "total" in stats
            assert "completed" in stats
            assert "running" in stats
            assert "failed" in stats
            assert "pending" in stats

    @pytest.mark.asyncio
    async def test_subtask_stats_correct_values(
        self,
        client: AsyncClient,
        sample_task: Task,
    ):
        """Test that subtask_stats returns correct values."""
        response = await client.get(f"/api/tasks/{sample_task.id}")

        assert response.status_code == 200
        data = response.json()

        stats = data.get("subtask_stats", {})

        # Based on sample_task fixture:
        # 2 completed, 1 running, 1 pending, 1 failed, 5 total
        assert stats.get("total") == 5, f"Expected total=5, got {stats.get('total')}"
        assert stats.get("completed") == 2, f"Expected completed=2, got {stats.get('completed')}"
        assert stats.get("running") == 1, f"Expected running=1, got {stats.get('running')}"
        assert stats.get("pending") == 1, f"Expected pending=1, got {stats.get('pending')}"
        assert stats.get("failed") == 1, f"Expected failed=1, got {stats.get('failed')}"

    @pytest.mark.asyncio
    async def test_task_detail_includes_subtask_stats(
        self,
        client: AsyncClient,
        sample_task: Task,
    ):
        """Test that task detail includes subtask_stats field."""
        response = await client.get(f"/api/tasks/{sample_task.id}")

        assert response.status_code == 200
        data = response.json()

        assert "subtask_stats" in data, "subtask_stats field should be present in task detail"
        assert "subtasks" in data, "subtasks field should be present in task detail"


class TestAgentsAPI:
    """Tests for Agents API (BUG-D fix)."""

    @pytest.mark.asyncio
    async def test_all_types_returns_all_agents(
        self,
        client: AsyncClient,
        sample_agents: dict,
    ):
        """Test that All Types filter returns all agent types."""
        response = await client.get("/api/agents")

        assert response.status_code == 200
        data = response.json()

        agent_types = {a["agent_type"] for a in data["items"]}

        # Should include all agent types: resident, owner, worker
        assert "resident" in agent_types, "Resident agent should be in results"
        assert "owner" in agent_types, "Owner agent should be in results"
        assert "worker" in agent_types, "Worker agent should be in results"

    @pytest.mark.asyncio
    async def test_filter_by_type_works(
        self,
        client: AsyncClient,
        sample_agents: dict,
    ):
        """Test that filtering by agent_type works correctly."""
        # Filter by owner
        response = await client.get("/api/agents?agent_type=owner")

        assert response.status_code == 200
        data = response.json()

        for agent in data["items"]:
            assert agent["agent_type"] == "owner"

    @pytest.mark.asyncio
    async def test_agent_parent_child_relationship(
        self,
        client: AsyncClient,
        sample_agents: dict,
    ):
        """Test that parent_agent_id is correctly returned."""
        response = await client.get("/api/agents?agent_type=owner")

        assert response.status_code == 200
        data = response.json()

        if len(data["items"]) > 0:
            owner = data["items"][0]
            assert owner["parent_agent_id"] is not None, "Owner should have parent_agent_id"


class TestSchedulerService:
    """Tests for Scheduler Service (BUG-C fix)."""

    @pytest.mark.asyncio
    async def test_stale_agent_marked_error(
        self,
        test_session: AsyncSession,
        test_engine,
    ):
        """Test that stale agents are marked as ERROR."""
        from datetime import timedelta
        from backend.services.scheduler_service import scheduler_service

        # Override db_manager for scheduler service
        db_manager._engine = test_engine
        db_manager._session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        # Create a stale owner agent
        old_time = datetime.utcnow() - timedelta(hours=1)
        owner = Agent(
            id=str(uuid4()),
            agent_type=AgentType.OWNER,
            name="Stale Owner",
            status=AgentStatus.RUNNING,
            created_at=old_time,
            updated_at=old_time,
        )
        test_session.add(owner)
        await test_session.commit()

        # Run health check
        await scheduler_service._check_agent_health()

        # Refresh and check status
        await test_session.refresh(owner)

        # Owner SHOULD be marked as ERROR (stale)
        assert owner.status == AgentStatus.ERROR, "Owner agent should be marked as ERROR when stale"

    @pytest.mark.asyncio
    async def test_active_agent_not_marked_error(
        self,
        test_session: AsyncSession,
        test_engine,
    ):
        """Test that active agents are not marked as ERROR."""
        from backend.services.scheduler_service import scheduler_service

        # Override db_manager for scheduler service
        db_manager._engine = test_engine
        db_manager._session_factory = async_sessionmaker(test_engine, expire_on_commit=False)

        # Create an active agent (recently updated)
        now = datetime.utcnow()
        agent = Agent(
            id=str(uuid4()),
            agent_type=AgentType.RESIDENT,
            name="Active Resident",
            status=AgentStatus.RUNNING,
            created_at=now,
            updated_at=now,
        )
        test_session.add(agent)
        await test_session.commit()

        # Run health check
        await scheduler_service._check_agent_health()

        # Refresh and check status
        await test_session.refresh(agent)

        # Agent should NOT be marked as ERROR
        assert agent.status == AgentStatus.RUNNING, "Active agent should not be marked as ERROR"


class TestTaskService:
    """Tests for Task Service."""

    @pytest.mark.asyncio
    async def test_get_subtask_stats(
        self,
        test_session: AsyncSession,
        sample_task: Task,
    ):
        """Test that get_subtask_stats returns correct counts."""
        from backend.services.task_service import task_service

        stats = await task_service.get_subtask_stats(test_session, sample_task.id)

        assert stats["total"] == 5
        assert stats["completed"] == 2
        assert stats["running"] == 1
        assert stats["pending"] == 1
        assert stats["failed"] == 1


# Run tests with: pytest -v backend/tests/test_api.py
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
