"""
Resident Agent for LongClaw.
A persistent agent that handles user conversations through channels.
"""
import asyncio
import logging
from datetime import datetime
from typing import Any

from backend.agents.base_agent import BaseAgent, get_current_datetime_str
from backend.agents.owner_agent import OwnerAgent
from backend.database import db_manager
from backend.models.agent import AgentType
from backend.models.message import Message, MessageType, ReceiverType, SenderType
from backend.models.subtask import SubtaskStatus
from backend.models.task import TaskStatus
from backend.services.agent_settings_service import agent_settings_service
from backend.services.config_service import config_service
from backend.services.knowledge_service import knowledge_service
from backend.services.llm_service import ChatMessage, ToolCall
from backend.services.task_service import task_service
from backend.services.tool_service import tool_service

logger = logging.getLogger(__name__)

# Default system prompt for the resident agent
DEFAULT_SYSTEM_PROMPT = """你叫老六，是一个靠谱的AI助手，性格有点皮。直接用中文回复。

## 时间认知
- 系统消息中包含当前日期和时间，请据此理解时间相关的用户请求
- 当用户提到"今天"、"昨天"、"最近"、"本周"等时间词时，要结合当前时间理解
- 涉及时间范围的任务时，主动计算具体日期范围

## 工作流程

当用户需要搜索信息、查询资料时：
1. 分析任务是否涉及时间敏感信息（如"最新"、"最近24小时"）
2. 使用 web_search 工具搜索相关信息
3. 根据搜索结果，使用 web_fetch 获取详细内容
4. 整合信息，给用户一个完整、有帮助的回答

## 重要提示
- 你有 web_search 和 web_fetch 工具可用
- 需要搜索时，直接调用工具，不要在文本中写工具调用代码
- 工具会自动执行，你只需等待结果
- 搜索关键词要包含具体的时间范围或日期

## 信息验证
- 遇到不确定的信息，主动用工具搜索验证
- 不要猜测或编造数据、日期、事件等事实信息
- 如果搜索结果信息不足，可以换关键词再次搜索

## 回复风格
- 友好、轻松、有点调皮
- 用中文回复
- 保持简洁但有帮助
- 搜索到信息后要给出信息来源链接"""


class ResidentAgent(BaseAgent):
    """Resident Agent - a persistent agent for user interaction.

    This agent:
    - Handles user messages from channels
    - Classifies messages as chat or task requests
    - Responds to chat messages using LLM
    - Executes tasks using tools (web search, web fetch)
    """

    def __init__(
        self,
        agent_id: str | None = None,
        name: str = "老六",
        personality: str | None = None,
        system_prompt: str | None = None,
        llm_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the resident agent.

        Args:
            agent_id: Existing agent ID (for loading from DB).
            name: Agent name.
            personality: Personality description.
            system_prompt: System prompt for LLM.
            llm_config: LLM configuration.
        """
        super().__init__(
            agent_id=agent_id,
            name=name,
            agent_type=AgentType.RESIDENT,
            personality=personality or "靠谱、友好、有点皮的AI助手",
            system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT,
            llm_config=llm_config,
        )
        self._conversation_history: list[ChatMessage] = []
        self._max_history: int = 20  # Keep last 20 messages
        self._pending_replies: dict[str, asyncio.Future[str]] = {}
        self._task_messages: list[ChatMessage] = []  # Messages for current task
        self._last_heartbeat: float = 0.0  # Timestamp of last heartbeat

    async def on_start(self) -> None:
        """Called when the agent starts."""
        # Load system prompt from database (instance override or type default)
        await self._load_system_prompt()
        logger.info(f"Resident agent {self._name} started, ready to chat!")

    async def _load_system_prompt(self) -> None:
        """Load system prompt from database.

        Checks for instance-level override first, then falls back to type-level default.
        If neither exists, uses the code's default prompt.
        """
        if not self._id:
            return

        try:
            async with db_manager.session() as session:
                # Get effective prompt (instance override or type default)
                db_prompt = await agent_settings_service.get_effective_prompt(
                    session,
                    agent_id=self._id,
                    agent_type=AgentType.RESIDENT,
                )
                if db_prompt:
                    self._system_prompt = db_prompt
                    logger.info(f"Loaded system prompt from database for agent {self._id}")
        except Exception as e:
            logger.warning(f"Failed to load system prompt from database: {e}")

    async def on_stop(self) -> None:
        """Called when the agent stops."""
        logger.info(f"Resident agent {self._name} stopped")

    async def on_message(self, message: Message) -> None:
        """Handle an incoming message.

        Args:
            message: The message to handle.
        """
        logger.info(f"Resident agent received message: {message.content[:50] if message.content else ''}...")

        # Update heartbeat to show agent is active
        await self._touch()

        # Add user message to history
        user_msg = ChatMessage(role="user", content=message.content or "")
        self._conversation_history.append(user_msg)
        self._trim_history()

        # Extract channel_id from message if sender is CHANNEL
        channel_id = None
        if message.sender_type == SenderType.CHANNEL:
            channel_id = message.sender_id

        try:
            # Determine if this is a chat or task request
            is_task_request = await self._classify_message(message.content or "")

            if is_task_request:
                # Task request - execute with tools
                reply = await self._execute_task(message.content or "", channel_id=channel_id)
            else:
                # Chat message - use LLM to generate response
                reply = await self._generate_chat_response()

            # Send reply
            await self.send_message(
                receiver_type=ReceiverType.CHANNEL,
                receiver_id=message.sender_id or "unknown",
                content=reply,
                message_type=MessageType.TEXT,
            )

            # Add assistant reply to history
            assistant_msg = ChatMessage(role="assistant", content=reply)
            self._conversation_history.append(assistant_msg)

            # Check if context needs compaction
            await self._check_and_compact()

            # Update heartbeat after processing
            await self._touch()

            # Set the reply future if someone is waiting
            if message.id in self._pending_replies:
                try:
                    self._pending_replies[message.id].set_result(reply)
                except asyncio.InvalidStateError:
                    # Future was already cancelled (e.g., timeout)
                    logger.warning(f"Future for message {message.id} already cancelled")
                finally:
                    if message.id in self._pending_replies:
                        del self._pending_replies[message.id]

        except Exception as e:
            logger.exception(f"Error handling message: {e}")
            error_reply = "哎呀，出了点小问题，稍后再试试吧~"

            # Update heartbeat even on error
            await self._touch()

            # Set the reply future if someone is waiting (with error reply)
            # This must be done BEFORE send_message to ensure the waiting request gets a response
            if message.id in self._pending_replies:
                try:
                    self._pending_replies[message.id].set_result(error_reply)
                except asyncio.InvalidStateError:
                    # Future was already cancelled (e.g., timeout)
                    logger.warning(f"Future for message {message.id} already cancelled")
                finally:
                    if message.id in self._pending_replies:
                        del self._pending_replies[message.id]

            # Try to send error reply, but don't let its failure prevent the response
            try:
                await self.send_message(
                    receiver_type=ReceiverType.CHANNEL,
                    receiver_id=message.sender_id or "unknown",
                    content=error_reply,
                    message_type=MessageType.TEXT,
                )
            except Exception as send_error:
                logger.exception(f"Failed to send error reply: {send_error}")

    async def on_idle(self) -> None:
        """Called when the agent is idle.

        Sends periodic heartbeat to prevent scheduler from marking us as ERROR.
        """
        import time

        # Get heartbeat interval from config (default: 60 seconds)
        # This should be less than scheduler_agent_timeout (default: 300 seconds)
        heartbeat_interval = await config_service.get_int("resident_heartbeat_interval", 60)

        current_time = time.time()
        if current_time - self._last_heartbeat >= heartbeat_interval:
            await self._touch()
            self._last_heartbeat = current_time
            logger.debug(f"ResidentAgent {self._id} idle heartbeat sent")

    async def generate_summary(self) -> str:
        """Generate a summary of recent conversations.

        Returns:
            Summary text.
        """
        if not self._conversation_history:
            return "暂无对话记录"

        # Get recent messages
        recent = self._conversation_history[-10:]
        history_text = "\n".join([
            f"{'用户' if msg.role == 'user' else '老六'}: {msg.content[:100]}"
            for msg in recent
        ])

        return f"最近 {len(recent)} 条消息:\n{history_text}"

    def _estimate_tokens(self, messages: list[ChatMessage] | None = None) -> int:
        """Estimate the number of tokens in messages.

        Simple estimation: ~4 characters per token for Chinese, ~5 for English.

        Args:
            messages: Messages to estimate. If None, use conversation history.

        Returns:
            Estimated token count.
        """
        if messages is None:
            messages = self._conversation_history

        total_chars = 0
        for msg in messages:
            if msg.content:
                total_chars += len(msg.content)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    total_chars += len(tc.name) + len(str(tc.arguments))

        # Rough estimate: 4 chars per token
        return total_chars // 4

    async def _check_and_compact(self) -> None:
        """Check if context exceeds threshold and compact if needed.

        This method:
        1. Checks token count against max context (from model config)
        2. If exceeds threshold, summarizes old messages
        3. Saves summary to knowledge
        4. Trims conversation history
        """
        if not self._id:
            return

        # Get config values - use model-specific context limit
        max_context = await self._resolve_context_limit()
        threshold = await config_service.get_float("context_compact_threshold", 0.8)
        keep_recent = await config_service.get_int("memory_keep_recent", 5)

        current_tokens = self._estimate_tokens()
        threshold_tokens = int(max_context * threshold)

        if current_tokens < threshold_tokens:
            return

        logger.info(f"Context exceeds threshold ({current_tokens}/{threshold_tokens}), compacting...")

        # Get messages to summarize (all except recent)
        if len(self._conversation_history) <= keep_recent:
            return

        messages_to_summarize = self._conversation_history[:-keep_recent]
        if not messages_to_summarize:
            return

        # Generate summary
        try:
            summary = await self._summarize_messages(messages_to_summarize)

            # Save to knowledge
            async with db_manager.session() as session:
                date_range = f"{datetime.now().strftime('%Y-%m-%d')}"
                await knowledge_service.save_conversation_summary(
                    session,
                    self._id,
                    summary,
                    date_range,
                )

            # Trim history
            self._conversation_history = self._conversation_history[-keep_recent:]
            logger.info(f"Compacted conversation history, kept {keep_recent} recent messages")

        except Exception as e:
            logger.error(f"Failed to compact conversation history: {e}")

    async def _summarize_messages(self, messages: list[ChatMessage]) -> str:
        """Summarize a list of messages using LLM.

        Args:
            messages: Messages to summarize.

        Returns:
            Summary text.
        """
        if not messages:
            return ""

        # Build summary prompt
        history_text = "\n".join([
            f"{'用户' if msg.role == 'user' else '助手'}: {msg.content[:500]}"
            for msg in messages
            if msg.content
        ])

        summary_prompt = f"""请总结以下对话内容，提取关键信息、用户偏好、重要事实等。保持简洁，不超过200字。

对话内容:
{history_text}

总结:"""

        try:
            from backend.services.llm_service import llm_service
            response = await llm_service.simple_complete(summary_prompt)
            return response
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            # Fallback: just note the conversation happened
            return f"发生过 {len(messages)} 条消息的对话"

    async def search_memory(self, query: str) -> list[dict[str, Any]]:
        """Search agent's memory/knowledge for relevant information.

        Args:
            query: Search query.

        Returns:
            List of matching knowledge entries.
        """
        if not self._id:
            return []

        try:
            async with db_manager.session() as session:
                results = await knowledge_service.search_knowledge(
                    session, self._id, query
                )
                return [k.to_dict() for k in results]
        except Exception as e:
            logger.error(f"Failed to search memory: {e}")
            return []

    async def save_important_memory(self, key: str, value: str, category: str | None = None) -> bool:
        """Save an important memory for this agent.

        Args:
            key: Short description.
            value: Full content.
            category: Optional category.

        Returns:
            True if saved successfully.
        """
        if not self._id:
            return False

        try:
            async with db_manager.session() as session:
                await knowledge_service.create_knowledge(
                    session, self._id, key, value, category=category
                )
                return True
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")
            return False

    async def get_memory_context(self, query: str | None = None) -> str:
        """Get relevant memory context for a query.

        Args:
            query: Optional query to search for relevant memories.

        Returns:
            Context string with relevant memories.
        """
        if not self._id:
            return ""

        try:
            async with db_manager.session() as session:
                max_memories = await config_service.get_int("memory_search_limit", 5)
                return await knowledge_service.get_context_with_memory(
                    session, self._id, query, max_memories
                )
        except Exception as e:
            logger.error(f"Failed to get memory context: {e}")
            return ""

    async def _classify_message(self, content: str) -> bool:
        """Classify if a message is a task request or chat.

        Args:
            content: Message content.

        Returns:
            True if task request, False if chat.
        """
        # Simple heuristic for now
        task_keywords = [
            "帮我", "请帮我", "任务", "执行", "完成", "创建", "生成",
            "写一个", "做一个", "帮我写", "帮我做", "帮我查",
            "分析", "处理", "整理", "汇总", "计算", "搜索", "查找",
            "查一下", "搜一下", "找一下", "了解一下", "调研",
        ]

        content_lower = content.lower()
        is_task = False
        matched_keyword = None

        for keyword in task_keywords:
            if keyword in content_lower:
                # More complex task patterns
                if any(word in content_lower for word in ["代码", "程序", "脚本", "报告", "文档", "计划", "信息", "资料", "数据", "新闻"]):
                    is_task = True
                    matched_keyword = keyword
                    break
                # Search-related keywords are strong indicators
                if any(word in content_lower for word in ["搜索", "查找", "查一下", "搜一下", "找一下", "调研"]):
                    is_task = True
                    matched_keyword = keyword
                    break
                # Simple help requests might just be chat
                if len(content) > 20:  # Longer messages more likely to be tasks
                    is_task = True
                    matched_keyword = keyword
                    break

        logger.info(f"Message classification: is_task={is_task}, matched_keyword={matched_keyword}, content_length={len(content)}")
        return is_task

    async def _is_complex_task(self, content: str) -> bool:
        """Determine if a task is complex enough to need OwnerAgent.

        Args:
            content: Message content.

        Returns:
            True if task needs OwnerAgent orchestration.
        """
        # Check for force complex task flag
        # 1. Special keyword [COMPLEX] in message forces OwnerAgent (for testing)
        if "[COMPLEX]" in content:
            logger.info("Force complex task via [COMPLEX] keyword detected")
            return True

        # 2. Config setting to force all tasks through OwnerAgent
        try:
            force_complex = await config_service.get_bool("force_complex_task", False)
            if force_complex:
                logger.info("Force complex task via config setting")
                return True
        except Exception as e:
            logger.warning(f"Failed to check force_complex_task config: {e}")

        # Complex task indicators
        complex_patterns = [
            "比较", "对比", "多个", "分别", "同时", "并", "以及",
            "综合", "全面", "详细", "深入", "系统", "完整",
            "趋势", "分析", "报告", "研究", "调研",
            # Search-related keywords that indicate need for orchestrated search
            "搜索", "搜一下", "查一下", "查询", "帮我找", "最新",
        ]

        # Check for multiple search queries or aspects
        has_multiple_aspects = (
            ("和" in content or "与" in content or "以及" in content) and
            any(word in content for word in ["新闻", "信息", "资料", "数据"])
        )

        # Check for complex patterns
        has_complex_pattern = any(pattern in content for pattern in complex_patterns)

        # Longer tasks tend to be more complex
        is_long_task = len(content) > 50

        result = has_multiple_aspects or has_complex_pattern or is_long_task
        logger.debug(
            f"Complexity check: has_multiple_aspects={has_multiple_aspects}, "
            f"has_complex_pattern={has_complex_pattern}, is_long_task={is_long_task}, "
            f"result={result}, content_length={len(content)}"
        )

        return result

    async def _execute_task(self, user_request: str, channel_id: str | None = None) -> str:
        """Execute a task using tools or OwnerAgent.

        Creates a Task record for all task requests (for tracking).
        For complex tasks, delegates to OwnerAgent for multi-agent orchestration.
        For simple tasks, uses direct tool-use loop.

        Args:
            user_request: The user's request.
            channel_id: Optional channel ID for tracking the source of the task.

        Returns:
            Final response to the user.
        """
        logger.info(f"Executing task: {user_request[:100]}...")

        # Create a Task record for tracking (for ALL tasks)
        task_id = None
        try:
            async with db_manager.session() as session:
                task = await task_service.create_task(
                    session,
                    title=user_request[:100] + ("..." if len(user_request) > 100 else ""),
                    description=user_request,
                    original_message=user_request,
                    channel_id=channel_id,  # Use the actual channel_id from message
                )
                task_id = task.id
                logger.info(f"Created task {task_id} for request")
        except Exception as e:
            logger.warning(f"Failed to create task record: {e}")

        # Check if this is a complex task that needs OwnerAgent
        is_complex = await self._is_complex_task(user_request)
        logger.info(f"Task complexity check: is_complex={is_complex}")

        if is_complex:
            logger.info("Complex task detected, delegating to OwnerAgent")
            result = await self._delegate_to_owner_agent(user_request, task_id)
        else:
            # Simple task: use direct tool-use loop
            result = await self._execute_with_tools(user_request)

            # Update task status to completed
            if task_id:
                try:
                    async with db_manager.session() as session:
                        await task_service.update_task(
                            session,
                            task_id,
                            summary=result[:500] + ("..." if len(result) > 500 else ""),
                            status=TaskStatus.COMPLETED,
                        )
                        logger.info(f"Task {task_id} completed")
                except Exception as e:
                    logger.warning(f"Failed to update task status: {e}")

        return result

    async def _delegate_to_owner_agent(self, user_request: str, task_id: str | None = None) -> str:
        """Delegate a complex task to OwnerAgent.

        Runs OwnerAgent to execute the task with multi-agent orchestration.
        Note: We do NOT set owner_agent_id to avoid foreign key constraint issues.
        The OwnerAgent is transient and not persisted to the agents table.
        The task status (RUNNING) prevents the scheduler from picking it up.

        Args:
            user_request: The user's request.
            task_id: Optional pre-existing task ID.

        Returns:
            Final response from OwnerAgent.
        """
        try:
            # Update heartbeat before starting long operation
            await self._touch()

            # Mark task as RUNNING so scheduler knows it's being processed
            # Do NOT set owner_agent_id - OwnerAgent is transient and not in DB
            if task_id:
                async with db_manager.session() as session:
                    await task_service.update_status(session, task_id, TaskStatus.RUNNING)
                    logger.info(f"Task {task_id} marked as RUNNING, executing via OwnerAgent")

            # Create and run OwnerAgent
            owner = OwnerAgent(
                task_id=task_id,
                parent_agent_id=self.id,
                timeout=None,  # Use config default
                max_subagents=5,
            )

            # Run OwnerAgent with heartbeat updates during long execution
            # This prevents scheduler from marking us as ERROR while waiting
            heartbeat_task = asyncio.create_task(self._heartbeat_during_execution())

            try:
                result = await owner.execute(user_request)
            finally:
                # Cancel heartbeat task when OwnerAgent completes
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # Update heartbeat after OwnerAgent completes
            await self._touch()

            # Determine task status based on subtask results
            if task_id:
                async with db_manager.session() as session:
                    # Check subtask status to determine final task status
                    subtasks = await task_service.get_task_subtasks(session, task_id)

                    # Count subtasks by status using enum comparison
                    failed_count = sum(1 for st in subtasks if st.status == SubtaskStatus.FAILED)
                    completed_count = sum(1 for st in subtasks if st.status == SubtaskStatus.COMPLETED)
                    total_count = len(subtasks)

                    logger.info(f"Task {task_id} subtask summary: total={total_count}, failed={failed_count}, completed={completed_count}")

                    if total_count > 0 and failed_count == total_count:
                        # All subtasks failed - set task to ERROR
                        await task_service.update_status(
                            session,
                            task_id,
                            TaskStatus.ERROR,
                        )
                        await task_service.update_task(
                            session,
                            task_id,
                            summary=result,
                        )
                        logger.warning(f"Task {task_id} marked as ERROR - all {total_count} subtasks failed")
                    elif completed_count == 0 and failed_count > 0:
                        # No successful subtasks but some failed - set task to ERROR
                        await task_service.update_status(
                            session,
                            task_id,
                            TaskStatus.ERROR,
                        )
                        await task_service.update_task(
                            session,
                            task_id,
                            summary=result,
                        )
                        logger.warning(f"Task {task_id} marked as ERROR - no successful subtasks, {failed_count} failed")
                    else:
                        # At least some success - set task to COMPLETED
                        # Use update_status to ensure completed_at is set correctly
                        await task_service.update_status(
                            session,
                            task_id,
                            TaskStatus.COMPLETED,
                        )
                        await task_service.update_task(
                            session,
                            task_id,
                            summary=result,
                        )
                        logger.info(f"Task {task_id} completed with {completed_count} successful subtasks")

            await owner.terminate()

            return result

        except Exception as e:
            logger.exception(f"OwnerAgent execution failed: {e}")
            # Fallback to direct execution
            return await self._execute_with_tools(user_request)

    async def _execute_with_tools(self, user_request: str) -> str:
        """Execute a task using direct tool-use loop.

        This implements the tool-use loop:
        1. LLM thinks about what to do
        2. LLM decides to call a tool (or respond)
        3. If tool call, execute the tool and return result
        4. Repeat until LLM gives a final response

        Args:
            user_request: The user's request.

        Returns:
            Final response to the user.
        """
        # Initialize task messages with user request
        self._task_messages = [ChatMessage(role="user", content=user_request)]

        # Get tool definitions
        tools = tool_service.get_tool_definitions()
        logger.info(f"Tool definitions: {len(tools)} tools available")
        for tool in tools:
            logger.info(f"  - Tool: {tool['function']['name']}")

        # Get max tool rounds from config
        max_tool_rounds = await config_service.get_int("tool_max_rounds", 10)

        tool_round = 0
        while tool_round < max_tool_rounds:
            tool_round += 1
            logger.info(f"Tool round {tool_round} starting")

            # Update heartbeat to show agent is still active during long operations
            await self._touch()

            try:
                # Call LLM with tools available
                messages = list(self._task_messages)
                response = await self.think_with_tools(messages, tools=tools)

                # Check if LLM wants to call tools
                if response.has_tool_calls:
                    # First, add assistant message with ALL tool_calls (only once)
                    self._task_messages.append(ChatMessage(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                    ))

                    # Then process each tool call and add tool result messages
                    for tool_call in response.tool_calls or []:
                        logger.info(f"Executing tool: {tool_call.name} with args: {tool_call.arguments}")
                        tool_result = await tool_service.execute_tool(
                            tool_call.name,
                            **tool_call.arguments
                        )

                        # Add tool result message
                        result_content = tool_result.content
                        if not tool_result.success and tool_result.error:
                            result_content = f"错误: {tool_result.error}"

                        self._task_messages.append(ChatMessage(
                            role="tool",
                            content=result_content,
                            tool_call_id=tool_call.id,
                            name=tool_call.name,
                        ))

                        logger.info(f"Tool {tool_call.name} executed: success={tool_result.success}")

                        # Update heartbeat after each tool execution
                        await self._touch()
                else:
                    # LLM gave a final response
                    return response.content or "抱歉，我没法回答这个问题。"

            except Exception as e:
                logger.exception(f"Error in task execution round {tool_round}: {e}")
                return f"执行任务时出错了: {str(e)}"

        # Max rounds reached - try to summarize existing results
        logger.warning(f"Max tool rounds ({max_tool_rounds}) reached, attempting to summarize existing results")

        # Check if we have any tool results to work with
        tool_results = [msg for msg in self._task_messages if msg.role == "tool"]

        if tool_results:
            # We have some results, ask LLM to summarize what we found
            summary_prompt = ChatMessage(
                role="user",
                content="请根据以上搜索结果，整理并回答用户的问题。如果信息不完整，请说明已找到的内容。"
            )
            self._task_messages.append(summary_prompt)

            try:
                # Get a final response without tools
                response = await self.think(self._task_messages)
                return response
            except Exception as e:
                logger.exception(f"Error generating summary from tool results: {e}")
                # Fall through to the fallback message

        # No tool results available, return the fallback message
        return "抱歉，这个任务有点复杂，我尝试了很多次但还是没有完全解决。你可以换个方式问问？"

    async def think_with_tools(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]],
    ) -> Any:
        """Call LLM with tools available.

        Args:
            messages: Chat messages.
            tools: Tool definitions.

        Returns:
            LLM response.
        """
        from backend.services.llm_service import llm_service

        # Add system prompt with current date/time
        if self._system_prompt:
            datetime_str = get_current_datetime_str()
            full_system_prompt = f"{datetime_str}\n\n{self._system_prompt}"
            messages = [ChatMessage(role="system", content=full_system_prompt)] + messages

        # Merge llm config
        merged_kwargs = {**self._llm_config}

        # Resolve model if configured
        resolved_provider, resolved_model = await self._resolve_model()
        if resolved_model:
            merged_kwargs['model'] = resolved_model

        logger.info(f"Calling LLM with {len(tools)} tools, {len(messages)} messages")
        response = await llm_service.complete(
            messages,
            tools=tools,
            provider=resolved_provider,
            **merged_kwargs
        )
        logger.info(f"LLM response: finish_reason={response.finish_reason}, has_tool_calls={response.has_tool_calls}")
        if response.tool_calls:
            logger.info(f"Tool calls requested: {[tc.name for tc in response.tool_calls]}")
        return response

    async def _generate_chat_response(self) -> str:
        """Generate a chat response using LLM.

        Returns:
            Generated response.
        """
        try:
            # Build messages for LLM
            messages = list(self._conversation_history)

            response = await self.think(messages)
            return response
        except Exception as e:
            logger.exception(f"Error generating response: {e}")
            return "嗯...让我想想该说什么...出了点小问题，你能再说一遍吗？"

    def _trim_history(self) -> None:
        """Trim conversation history to max size."""
        if len(self._conversation_history) > self._max_history:
            self._conversation_history = self._conversation_history[-self._max_history:]

    def get_conversation_history(self) -> list[ChatMessage]:
        """Get the conversation history.

        Returns:
            List of chat messages.
        """
        return list(self._conversation_history)

    async def wait_for_reply(self, message_id: str, timeout: float | None = None) -> str:
        """Wait for a reply to a specific message.

        Args:
            message_id: Message ID to wait for reply.
            timeout: Timeout in seconds. None uses config default.

        Returns:
            Reply content.

        Raises:
            asyncio.TimeoutError: If timeout expires.
        """
        # Resolve timeout from config if not specified
        if timeout is None:
            timeout = await config_service.get_float("resident_chat_timeout", 600.0)

        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        self._pending_replies[message_id] = future

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            del self._pending_replies[message_id]
            raise

    async def _heartbeat_during_execution(self) -> None:
        """Periodically update heartbeat during long task execution.

        This prevents the scheduler from marking the agent as ERROR
        while waiting for OwnerAgent to complete.

        The heartbeat interval is half of the scheduler_agent_timeout
        to ensure we update before the timeout triggers.
        """
        # Get heartbeat interval from config (default: 60 seconds)
        # This should be less than scheduler_agent_timeout (default: 300 seconds)
        heartbeat_interval = await config_service.get_int("resident_heartbeat_interval", 60)

        while True:
            try:
                await asyncio.sleep(heartbeat_interval)
                await self._touch()
                logger.debug(f"ResidentAgent {self._id} heartbeat during task execution")
            except asyncio.CancelledError:
                # This is expected when the OwnerAgent completes
                logger.debug(f"ResidentAgent {self._id} heartbeat task cancelled")
                raise
            except Exception as e:
                logger.warning(f"ResidentAgent {self._id} heartbeat error: {e}")
                # Continue trying to send heartbeats

