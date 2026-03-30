"""
WorkerAgent for LongClaw.
An agent that executes subtasks with tool calling capability.
"""
import asyncio
import logging
import uuid
from typing import Any

from backend.agents.sub_agent import SubAgent
from backend.agents.base_agent import TimeoutManager
from backend.database import db_manager
from backend.models.agent import AgentType, AgentStatus
from backend.models.message import Message
from backend.models.subtask import SubtaskStatus
from backend.services.agent_settings_service import agent_settings_service
from backend.services.config_service import config_service
from backend.services.llm_service import ChatMessage
from backend.services.task_service import task_service
from backend.services.tool_service import tool_service

logger = logging.getLogger(__name__)

# System prompt for WorkerAgent
WORKER_AGENT_SYSTEM_PROMPT = """你是一个执行型 Agent，负责完成特定的子任务。

## 时间认知
系统消息中已包含当前日期和时间。当任务涉及时间范围时，根据当前时间计算具体日期范围。

## 可用工具
- web_search(query): 搜索互联网信息，返回编号结果列表（含标题、URL、摘要）
- web_fetch(url): 抓取网页详细内容

## 🚨 执行流程（必须严格遵守）

**步骤 1：搜索一次**
- 调用 web_search，使用精确的搜索关键词

**步骤 2：分析搜索结果**
- 仔细阅读每条结果的【摘要】部分
- 摘要通常包含：价格、日期、名称、数量等关键信息
- 如果摘要中已有你需要的数据 → 直接进入步骤 5

**步骤 3：判断是否需要详情**
- 摘要信息足够回答问题？→ 进入步骤 5
- 摘要信息不完整？→ 对最相关的 1-2 个 URL 调用 web_fetch

**步骤 4：获取详情（仅在必要时）**
- 从搜索结果中选择最相关的 URL
- 调用 web_fetch 获取完整内容
- 最多抓取 2 个页面

**步骤 5：整理输出**
- 汇总所有获取到的信息
- 给出简洁、准确的回答
- 标注信息来源

## 📋 搜索结果格式示例
```
搜索 '比特币价格' 找到 5 个结果:
1. 比特币实时价格 - 币安
   URL: https://www.binance.com/...
   摘要: 比特币当前价格 $67,234.50，24小时涨幅 2.3%
2. ...
```
↑ 看到这个结果，你应该直接从摘要提取 "$67,234.50"，不需要再 web_fetch！

## ⚠️ 关键规则

**禁止行为：**
- ❌ 搜索超过 3 次（换关键词最多重试 1 次）
- ❌ 不读摘要就重新搜索
- ❌ 不尝试 web_fetch 就说找不到
- ❌ 编造 "调用次数限制"、"网络超时"、"系统限制"、"反爬虫" 等虚假原因
- ❌ 搜索成功却报告失败

**正确行为：**
- ✅ 搜索结果摘要有数据 → 直接用
- ✅ 摘要没数据但有关联 URL → web_fetch 获取
- ✅ 确实找不到 → 如实报告 "搜索结果中未找到 xxx 信息"

## 输出要求
- 基于实际获取的信息回答
- 简洁但有信息量
- 标注信息来源（URL）"""


class WorkerAgent(SubAgent):
    """WorkerAgent - executes subtasks with tool calling capability.

    This agent:
    - Executes a specific subtask
    - Uses tools to gather information
    - Updates subtask status in database
    - Persists to database for visibility and tracking
    - Has a short lifecycle (destroyed after task completion)
    """

    def __init__(
        self,
        name: str = "WorkerAgent",
        task_id: str | None = None,
        subtask_id: str | None = None,
        parent_agent_id: str | None = None,
        description: str | None = None,
        tools: list[str] | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the WorkerAgent.

        Args:
            name: Agent name.
            task_id: Associated task ID.
            subtask_id: Associated subtask ID in DB.
            parent_agent_id: Parent agent (usually OwnerAgent) ID.
            description: Task description.
            tools: List of tool names to use (default: all tools).
            timeout: Execution timeout in seconds. None uses config default.
        """
        # Don't call super().__init__ because we have custom persistence logic
        self._id: str | None = None  # Will be set after persist
        self._name = name
        self._agent_type = AgentType.WORKER
        self._personality = None
        self._system_prompt = WORKER_AGENT_SYSTEM_PROMPT
        self._llm_config = {}
        self._parent_agent_id = parent_agent_id
        self._task_id = task_id

        self._status: AgentStatus = AgentStatus.IDLE
        self._model = None  # No database model initially
        self._run_task: asyncio.Task[Any] | None = None
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._last_summary: str | None = None
        self._context: dict[str, Any] = {}

        # WorkerAgent specific attributes
        self._subtask_id = subtask_id
        self._description = description
        self._tools = tools or ["web_search", "web_fetch"]
        self._timeout = timeout  # Will be resolved in execute()
        self._result: str | None = None
        self._execution_messages: list[ChatMessage] = []
        self._completed = asyncio.Event()
        self._progress_callback: Any = None  # Optional callback to signal progress

        # Dynamic timeout manager - no max extension limit, extend as long as there's progress
        self._timeout_manager = TimeoutManager(
            base_timeout=300,  # 5 minutes base
            max_extension=0,  # No limit - extend as long as there's progress
            min_progress_interval=30,
        )

    async def execute(self, task_description: str) -> str:
        """Execute a subtask and return the result.

        Updates subtask status in database during execution.

        Args:
            task_description: The subtask to execute.

        Returns:
            Execution result.
        """
        self._description = task_description

        # Persist WorkerAgent to database for visibility
        await self._persist()

        # Update agent status to RUNNING
        await self._update_status(AgentStatus.RUNNING)

        logger.info(f"WorkerAgent {self._id} starting subtask: {task_description[:100]}...")

        # Load system prompt from database (type-level default) or use code default
        try:
            async with db_manager.session() as session:
                type_settings = await agent_settings_service.get_type_settings(
                    session, AgentType.WORKER
                )
                if type_settings and type_settings.system_prompt:
                    self._system_prompt = type_settings.system_prompt
                    logger.info("Loaded WORKER system prompt from database")
        except Exception as e:
            logger.warning(f"Failed to load WORKER prompt from database: {e}")

        # Resolve base timeout from config
        # Note: get_float returns None when config value is -1 (unlimited)
        base_timeout = self._timeout or await config_service.get_float("worker_subtask_timeout", 300.0)
        self._timeout_manager._base_timeout = int(base_timeout) if base_timeout is not None else None

        # Start the timeout manager
        self._timeout_manager.start()
        logger.info(f"WorkerAgent {self._id} started with base timeout {base_timeout}s")

        # Get max tool rounds from config
        max_tool_rounds = await config_service.get_int("tool_max_rounds", 10)

        # Update subtask status to RUNNING
        if self._subtask_id:
            await self._update_subtask_status(SubtaskStatus.RUNNING)

            # Set progress callback to update subtask's updated_at periodically
            # This allows the scheduler to track that this worker is still active
            async def touch_subtask_callback():
                async with db_manager.session() as session:
                    await task_service.touch_subtask(session, self._subtask_id)
            self._progress_callback = touch_subtask_callback

        # Initialize execution messages
        self._execution_messages = [
            ChatMessage(role="user", content=task_description)
        ]

        # Get tool definitions for the tools this agent can use
        all_tools = tool_service.get_tool_definitions()
        available_tools = [
            t for t in all_tools
            if t.get("function", {}).get("name") in self._tools
        ]

        try:
            # Execute with dynamic timeout
            result = await self._execute_with_tools(available_tools)
            self._result = result
            self._completed.set()

            # Update agent status to IDLE (completed)
            await self._update_status(AgentStatus.IDLE)

            # Update subtask status to COMPLETED
            if self._subtask_id:
                await self._update_subtask_status(
                    SubtaskStatus.COMPLETED,
                    summary=result[:500] if result else None,
                )

            return result

        except asyncio.TimeoutError:
            current_timeout = self._timeout_manager.get_current_timeout()
            logger.warning(f"WorkerAgent {self._id} timed out after {current_timeout}s")
            self._result = f"任务执行超时（{current_timeout}秒）"
            self._completed.set()

            # Update agent status to ERROR
            await self._update_status(AgentStatus.ERROR)

            # Update subtask status to FAILED
            if self._subtask_id:
                await self._update_subtask_status(
                    SubtaskStatus.FAILED,
                    error=f"执行超时（{current_timeout}秒）",
                )

            return self._result

        except Exception as e:
            logger.exception(f"WorkerAgent {self._id} error: {e}")
            self._result = f"执行出错: {str(e)}"
            self._completed.set()

            # Update agent status to ERROR
            await self._update_status(AgentStatus.ERROR)

            # Update subtask status to FAILED
            if self._subtask_id:
                await self._update_subtask_status(SubtaskStatus.FAILED, error=str(e))

            return self._result

    async def _update_subtask_status(
        self,
        status: SubtaskStatus,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update subtask status in database.

        Args:
            status: New status.
            summary: Optional summary.
            error: Optional error message.
        """
        if not self._subtask_id:
            return

        try:
            async with db_manager.session() as session:
                result_data = {"error": error} if error else None
                await task_service.update_subtask_status(
                    session,
                    self._subtask_id,
                    status,
                    summary=summary,
                    result=result_data,
                )
        except Exception as e:
            logger.exception(f"Failed to update subtask {self._subtask_id} status: {e}")

    async def _persist(self) -> str:
        """Persist the WorkerAgent to database for visibility.

        Also assigns the worker_agent_id to the associated subtask if applicable.

        Returns:
            Agent ID.
        """
        from backend.services.agent_service import agent_service

        if self._id:
            return self._id

        async with db_manager.session() as session:
            agent = await agent_service.create_agent(
                session,
                agent_type=AgentType.WORKER,
                name=self._name,
                parent_agent_id=self._parent_agent_id,
                task_id=self._task_id,
            )
            self._id = agent.id
            logger.info(f"Persisted WorkerAgent {self._id} to database")

            # Assign worker_agent_id to the subtask
            if self._subtask_id:
                await task_service.assign_worker(
                    session, self._subtask_id, self._id
                )
                logger.debug(f"Assigned WorkerAgent {self._id} to subtask {self._subtask_id}")

        return self._id

    async def _update_status(self, status: AgentStatus) -> None:
        """Update agent status in database.

        Args:
            status: New status.
        """
        self._status = status
        if not self._id:
            return

        try:
            async with db_manager.session() as session:
                from sqlalchemy import select
                from backend.models.agent import Agent
                result = await session.execute(
                    select(Agent).where(Agent.id == self._id)
                )
                agent = result.scalar_one_or_none()
                if agent:
                    agent.status = status
                    await session.commit()
        except Exception as e:
            logger.warning(f"Failed to update WorkerAgent {self._id} status: {e}")

    async def terminate(self) -> None:
        """Terminate the WorkerAgent.

        Sets the agent status to TERMINATED in the database.
        This should be called by the OwnerAgent when it terminates.
        """
        logger.info(f"WorkerAgent {self._id} terminating")
        await self._update_status(AgentStatus.TERMINATED)
        self._completed.set()
