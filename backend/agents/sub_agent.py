"""
SubAgent for LongClaw.
A lightweight agent for executing specific subtasks.
"""
import asyncio
import logging
import uuid
from typing import Any

from backend.agents.base_agent import BaseAgent, TimeoutManager, get_current_datetime_str
from backend.database import db_manager
from backend.models.agent import AgentType, AgentStatus
from backend.models.message import Message
from backend.services.agent_settings_service import agent_settings_service
from backend.services.config_service import config_service
from backend.services.llm_service import ChatMessage
from backend.services.tool_service import tool_service

logger = logging.getLogger(__name__)

# System prompt for SubAgent
SUB_AGENT_SYSTEM_PROMPT = """你是一个执行型 Agent，负责完成特定的子任务。

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


class SubAgent(BaseAgent):
    """SubAgent - a lightweight agent for executing subtasks.

    This agent:
    - Executes a specific subtask
    - Uses tools to gather information
    - Has a short lifecycle (destroyed after task completion)
    - Does not persist to database
    """

    def __init__(
        self,
        name: str = "SubAgent",
        task_id: str | None = None,
        parent_agent_id: str | None = None,
        description: str | None = None,
        tools: list[str] | None = None,
        timeout: float | None = None,
    ) -> None:
        """Initialize the SubAgent.

        Args:
            name: Agent name.
            task_id: Associated task ID.
            parent_agent_id: Parent agent (usually OwnerAgent) ID.
            description: Task description.
            tools: List of tool names to use (default: all tools).
            timeout: Execution timeout in seconds. None uses config default.
        """
        # Generate a unique ID without database persistence
        self._id = f"sub_{uuid.uuid4().hex[:8]}"

        # Initialize base attributes without calling super().__init__
        # because we don't want to persist to database
        self._name = name
        self._agent_type = AgentType.WORKER
        self._personality = None
        self._system_prompt = SUB_AGENT_SYSTEM_PROMPT
        self._llm_config = {}
        self._parent_agent_id = parent_agent_id
        self._task_id = task_id

        self._status: AgentStatus = AgentStatus.IDLE
        self._model = None  # No database model
        self._run_task: asyncio.Task[Any] | None = None
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._last_summary: str | None = None
        self._context: dict[str, Any] = {}

        # SubAgent specific attributes
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
            min_progress_interval=30,  # Record progress every 30s
        )

    @property
    def result(self) -> str | None:
        """Get the execution result."""
        return self._result

    @property
    def is_completed(self) -> bool:
        """Check if the agent has completed its task."""
        return self._completed.is_set()

    async def execute(self, task_description: str) -> str:
        """Execute a task and return the result.

        This is the main entry point for SubAgent.
        It runs the task synchronously and returns the result.

        Args:
            task_description: The task to execute.

        Returns:
            Execution result.
        """
        self._description = task_description
        logger.info(f"SubAgent {self._id} starting task: {task_description[:100]}...")

        # Load system prompt from database (type-level default) or use code default
        try:
            async with db_manager.session() as session:
                type_settings = await agent_settings_service.get_type_settings(
                    session, AgentType.SUB
                )
                if type_settings and type_settings.system_prompt:
                    self._system_prompt = type_settings.system_prompt
                    logger.info("Loaded SUB system prompt from database")
        except Exception as e:
            logger.warning(f"Failed to load SUB prompt from database: {e}")

        # Resolve base timeout from config
        # Note: get_float returns None when config value is -1 (unlimited)
        base_timeout = self._timeout or await config_service.get_float("worker_subtask_timeout", 300.0)
        self._timeout_manager._base_timeout = int(base_timeout) if base_timeout is not None else None

        # Start the timeout manager
        self._timeout_manager.start()
        logger.info(f"SubAgent {self._id} started with base timeout {base_timeout}s")

        # Initialize execution messages
        self._execution_messages = [
            ChatMessage(role="user", content=task_description)
        ]

        # Get tool definitions for the tools this agent can use
        all_tools = tool_service.get_tool_definitions()
        # Filter to only the tools this agent can use
        available_tools = [
            t for t in all_tools
            if t.get("function", {}).get("name") in self._tools
        ]

        try:
            # Execute with dynamic timeout check
            result = await self._execute_with_tools(available_tools)
            self._result = result
            self._completed.set()
            return result

        except asyncio.TimeoutError:
            current_timeout = self._timeout_manager.get_current_timeout()
            logger.warning(f"SubAgent {self._id} timed out after {current_timeout}s")
            self._result = f"任务执行超时（{current_timeout}秒）"
            self._completed.set()
            return self._result

        except Exception as e:
            logger.exception(f"SubAgent {self._id} error: {e}")
            self._result = f"执行出错: {str(e)}"
            self._completed.set()
            return self._result

    async def _execute_with_tools(self, tools: list[dict[str, Any]]) -> str:
        """Execute task using tool-use loop.

        Args:
            tools: Available tool definitions.

        Returns:
            Final result.
        """
        from backend.services.llm_service import llm_service

        # Get max tool rounds from config
        # Note: get_int returns None when config value is -1 (unlimited)
        max_tool_rounds = await config_service.get_int("tool_max_rounds", 10)

        # Track consecutive web_search calls to prevent infinite search loops
        consecutive_search_count = 0
        MAX_CONSECUTIVE_SEARCHES = 3

        tool_round = 0
        # If max_tool_rounds is None (unlimited), loop until break
        while max_tool_rounds is None or tool_round < max_tool_rounds:
            # Check for timeout before each round
            if self._timeout_manager.is_timed_out():
                current_timeout = self._timeout_manager.get_current_timeout()
                raise asyncio.TimeoutError(f"Agent timed out after {current_timeout}s")

            # Check if agent was terminated externally
            if await self._check_terminated():
                logger.info(f"SubAgent {self._id} terminated, stopping execution")
                return "任务已被终止"

            tool_round += 1
            logger.debug(f"SubAgent {self._id} tool round {tool_round}")

            # Build messages with system prompt (with current date/time)
            datetime_str = get_current_datetime_str()
            full_system_prompt = f"{datetime_str}\n\n{self._system_prompt}"
            messages = [ChatMessage(role="system", content=full_system_prompt)]
            messages.extend(self._execution_messages)

            try:
                # Debug: log message structure (without full content)
                msg_summary = [f"{m.role}" + (f"[tool_calls={len(m.tool_calls)}]" if m.tool_calls else "") + (f"[tool_call_id={m.tool_call_id[:8]}...]" if m.tool_call_id else "") for m in messages]
                logger.debug(f"SubAgent {self._id} sending {len(messages)} messages: {msg_summary}")

                # Call LLM with tools
                response = await llm_service.complete(messages, tools=tools)

                # Record progress after LLM response
                self._timeout_manager.record_progress(
                    "llm_response",
                    f"Received LLM response in round {tool_round}"
                )
                # Call progress callback if set (to update DB for scheduler tracking)
                if self._progress_callback:
                    try:
                        await self._progress_callback()
                    except Exception as e:
                        logger.warning(f"Progress callback failed: {e}")

                if response.has_tool_calls:
                    # Check for web_search calls and track consecutive searches
                    has_web_search = any(
                        tc.name == "web_search" for tc in (response.tool_calls or [])
                    )
                    if has_web_search:
                        consecutive_search_count += 1
                        logger.info(f"SubAgent {self._id} consecutive web_search count: {consecutive_search_count}")

                        # Force stop if too many consecutive searches
                        if consecutive_search_count >= MAX_CONSECUTIVE_SEARCHES:
                            logger.warning(f"SubAgent {self._id} reached max consecutive searches ({MAX_CONSECUTIVE_SEARCHES}), forcing final response")

                            # Add assistant message with tool_calls (required by API)
                            self._execution_messages.append(ChatMessage(
                                role="assistant",
                                content=response.content,
                                tool_calls=response.tool_calls,
                            ))

                            # Add tool responses for all tool_calls (required by API)
                            # Without tool responses, the API will return 400 error
                            for tool_call in response.tool_calls or []:
                                self._execution_messages.append(ChatMessage(
                                    role="tool",
                                    content="已达到最大连续搜索次数限制（3次）。请根据已有的搜索结果整理回答，不要继续搜索。",
                                    tool_call_id=tool_call.id,
                                    name=tool_call.name,
                                ))

                            # Add a user message to prompt final response
                            self._execution_messages.append(ChatMessage(
                                role="user",
                                content="请根据以上搜索结果，整理并回答原始问题。",
                            ))

                            # Continue to let LLM process and give final answer
                            continue
                    else:
                        # Reset counter when other tools are used (e.g., web_fetch)
                        consecutive_search_count = 0

                    # Add assistant message with ALL tool_calls (only once)
                    self._execution_messages.append(ChatMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    ))

                    # Then process each tool call and add tool result messages
                    round_tool_results = []
                    for tool_call in response.tool_calls or []:
                        logger.info(f"SubAgent {self._id} calling tool: {tool_call.name}")

                        # Execute tool
                        tool_result = await tool_service.execute_tool(
                            tool_call.name,
                            **tool_call.arguments
                        )

                        # Record progress after tool execution
                        self._timeout_manager.record_progress(
                            "tool_call",
                            f"Executed tool: {tool_call.name}",
                            {"success": tool_result.success}
                        )
                        # Call progress callback if set (to update DB for scheduler tracking)
                        if self._progress_callback:
                            try:
                                await self._progress_callback()
                            except Exception as e:
                                logger.warning(f"Progress callback failed: {e}")

                        # Add tool result
                        result_content = tool_result.content
                        if not tool_result.success and tool_result.error:
                            result_content = f"错误: {tool_result.error}"

                        self._execution_messages.append(ChatMessage(
                            role="tool",
                            content=result_content,
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
                        ))

                        logger.info(f"SubAgent {self._id} tool {tool_call.name} executed: success={tool_result.success}")

                        # Record tool result for message recording
                        round_tool_results.append({
                            "id": tool_call.id,
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                            "result": result_content,
                            "success": tool_result.success,
                        })

                    # Record round to message system after all tools executed
                    await self._record_round_to_message(
                        round_num=tool_round,
                        llm_response=response,
                        tool_results=round_tool_results,
                        is_final=False,
                    )
                else:
                    # LLM gave final response
                    # Record final round to message system
                    await self._record_round_to_message(
                        round_num=tool_round,
                        llm_response=response,
                        tool_results=[],
                        is_final=True,
                    )
                    return response.content or "任务完成，但无结果返回。"

            except Exception as e:
                logger.exception(f"SubAgent {self._id} error in round {tool_round}: {e}")
                return f"执行过程中出错: {str(e)}"

        # Max rounds reached
        return "达到最大工具调用次数，任务可能未完全完成。"

    async def persist(self) -> str:
        """SubAgent does not persist to database.

        Returns:
            Agent ID.
        """
        # SubAgent doesn't persist, just return the ID
        return self._id

    async def load(self, agent_id: str) -> None:
        """SubAgent cannot be loaded from database."""
        raise NotImplementedError("SubAgent cannot be loaded from database")

    async def on_start(self) -> None:
        """Called when the agent starts."""
        logger.debug(f"SubAgent {self._id} started")

    async def on_stop(self) -> None:
        """Called when the agent stops."""
        logger.debug(f"SubAgent {self._id} stopped")

    async def on_message(self, message: Message) -> None:
        """Handle an incoming message.

        SubAgent doesn't typically receive messages from the queue.
        Use execute() instead.
        """
        logger.warning(f"SubAgent {self._id} received unexpected message")

    async def on_idle(self) -> None:
        """Called when the agent is idle."""
        pass

    async def generate_summary(self) -> str:
        """Generate a summary of the agent's work.

        Returns:
            Summary text.
        """
        if self._result:
            return f"任务: {self._description}\n结果: {self._result[:200]}"
        return f"任务: {self._description}\n状态: 未完成"

    async def _record_round_to_message(
        self,
        round_num: int,
        llm_response: "LLMResponse",
        tool_results: list[dict[str, Any]],
        is_final: bool,
    ) -> None:
        """Record execution round to message system.

        Parses LLM response to separate thinking (<think> tags) from actual response.
        """
        from backend.services.message_service import message_service
        from backend.models.message import SenderType, ReceiverType, MessageType
        from backend.services.llm_service import LLMResponse
        import re

        # Parse thinking content from <think>...</think> tags
        raw_content = llm_response.content or ""
        thinking_content = ""
        actual_content = raw_content

        # Extract <think>...</think> content
        think_match = re.search(r'<think\s*(.*?)\s*</think\s*>', raw_content, re.DOTALL)
        if think_match:
            thinking_content = think_match.group(1).strip()
            # Remove think tags to get actual content
            actual_content = re.sub(r'<think\s*.*?\s*</think\s*>', '', raw_content, flags=re.DOTALL).strip()

        # Build human-readable markdown content
        content_parts = [f"## Round {round_num}"]

        # Add thinking section if present
        if thinking_content:
            content_parts.append("\n### 思考过程\n")
            content_parts.append(thinking_content)

        # Add actual response/content section
        if actual_content:
            if tool_results:
                # Has tool calls, this is decision/action content
                content_parts.append("\n### 决策\n")
            else:
                # No tool calls, this is the actual response
                content_parts.append("\n### 回复\n")
            content_parts.append(actual_content)

        # Add tool calls section
        if tool_results:
            content_parts.append("\n### 工具调用\n")
            for tr in tool_results:
                args_str = ", ".join(f"{k}={v!r}" for k, v in tr.get("arguments", {}).items())
                result_preview = tr['result'][:500] if len(tr.get('result', '')) > 500 else tr.get('result', 'N/A')
                content_parts.append(f"**{tr['name']}**({args_str})\n```\n{result_preview}\n```\n")

        # For final response, add summary section
        if is_final and actual_content:
            content_parts.append(f"\n### 总结\n{actual_content}")

        content = "\n".join(content_parts)

        # Build metadata (machine-readable)
        metadata = {
            "type": "agent_execution_round",
            "agent_id": self._id,
            "round_number": round_num,
            "is_final": is_final,
            "tool_calls": tool_results,
        }

        # Store to database
        try:
            async with db_manager.session() as session:
                await message_service.create_message(
                    session=session,
                    sender_type=SenderType.WORKER,
                    sender_id=self._id,
                    receiver_type=ReceiverType.AGENT,
                    receiver_id=self._id,
                    content=content,
                    message_type=MessageType.SYSTEM,
                    task_id=self._task_id,
                    subtask_id=getattr(self, '_subtask_id', None),
                    metadata=metadata,
                )
        except Exception as e:
            logger.warning(f"Failed to record round message: {e}")
