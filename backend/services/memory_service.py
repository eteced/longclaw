"""
Memory Service for LongClaw.
Manages conversation persistence and memory compaction.
"""
import json
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.message import Message, MessageType, SenderType, ReceiverType
from backend.services.config_service import config_service
from backend.services.llm_service import ChatMessage, llm_service
from backend.services.message_service import message_service

logger = logging.getLogger(__name__)


class MemoryService:
    """Service for managing agent memory and conversation persistence.

    Features:
    - Persist all conversations to database
    - Token-based compact when limit exceeded
    - Keep recent N messages intact
    - Generate summaries for compacted history
    """

    def __init__(self) -> None:
        """Initialize the memory service."""
        self._token_limit: int = 4000  # Default token limit
        self._keep_recent: int = 5  # Keep last N messages intact
        self._compact_threshold: float = 0.8  # Compact when 80% of limit

    async def init(self) -> None:
        """Initialize the memory service."""
        self._token_limit = await config_service.get_int("memory_token_limit", 4000)
        self._keep_recent = await config_service.get_int("memory_keep_recent", 5)
        self._compact_threshold = await config_service.get_float("memory_compact_threshold", 0.8)
        logger.info(
            f"Memory service initialized: token_limit={self._token_limit}, "
            f"keep_recent={self._keep_recent}"
        )

    async def persist_message(
        self,
        session: AsyncSession,
        conversation_id: str | None,
        sender_type: str,
        sender_id: str | None,
        receiver_type: str,
        receiver_id: str | None,
        content: str,
        message_type: str = "text",
        task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """Persist a message to the database.

        Args:
            session: Database session.
            conversation_id: Conversation ID.
            sender_type: Type of sender.
            sender_id: ID of sender.
            receiver_type: Type of receiver.
            receiver_id: ID of receiver.
            content: Message content.
            message_type: Type of message.
            task_id: Optional task ID.
            metadata: Optional metadata.

        Returns:
            Created message.
        """
        message = await message_service.create_message(
            session,
            sender_type=SenderType(sender_type),
            sender_id=sender_id,
            receiver_type=ReceiverType(receiver_type),
            receiver_id=receiver_id,
            content=content,
            message_type=MessageType(message_type),
            conversation_id=conversation_id,
            task_id=task_id,
            metadata=metadata,
        )
        return message

    async def get_conversation_history(
        self,
        session: AsyncSession,
        conversation_id: str,
        limit: int = 100,
    ) -> list[Message]:
        """Get conversation history from database.

        Args:
            session: Database session.
            conversation_id: Conversation ID.
            limit: Maximum messages to retrieve.

        Returns:
            List of messages.
        """
        result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        messages = list(result.scalars().all())
        return list(reversed(messages))  # Return in chronological order

    async def get_agent_history(
        self,
        session: AsyncSession,
        agent_id: str,
        limit: int = 100,
    ) -> list[Message]:
        """Get agent's conversation history.

        Args:
            session: Database session.
            agent_id: Agent ID.
            limit: Maximum messages to retrieve.

        Returns:
            List of messages.
        """
        result = await session.execute(
            select(Message)
            .where(
                (Message.sender_id == agent_id) | (Message.receiver_id == agent_id)
            )
            .order_by(desc(Message.created_at))
            .limit(limit)
        )
        messages = list(result.scalars().all())
        return list(reversed(messages))

    async def estimate_tokens(self, messages: list[Message]) -> int:
        """Estimate token count for messages.

        Uses a simple heuristic: ~4 characters per token for Chinese,
        ~1 word per token for English.

        Args:
            messages: Messages to estimate.

        Returns:
            Estimated token count.
        """
        total = 0
        for msg in messages:
            content = msg.content or ""
            # Rough estimation: count Chinese characters separately
            chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            other_chars = len(content) - chinese_chars
            # Chinese: ~2 chars per token, English: ~4 chars per token
            tokens = chinese_chars // 2 + other_chars // 4 + 1
            total += tokens
        return total

    async def needs_compact(self, messages: list[Message]) -> bool:
        """Check if conversation history needs compaction.

        Args:
            messages: Current messages.

        Returns:
            True if compaction is needed.
        """
        tokens = await self.estimate_tokens(messages)
        return tokens >= self._token_limit * self._compact_threshold

    async def compact_history(
        self,
        messages: list[Message],
        keep_recent: int | None = None,
    ) -> tuple[list[Message], str]:
        """Compact conversation history by summarizing older messages.

        Args:
            messages: Current messages.
            keep_recent: Number of recent messages to keep intact.

        Returns:
            Tuple of (compacted messages, summary).
        """
        keep_recent = keep_recent or self._keep_recent

        if len(messages) <= keep_recent:
            return messages, ""

        # Split into old and recent
        old_messages = messages[:-keep_recent]
        recent_messages = messages[-keep_recent:]

        # Generate summary for old messages
        summary = await self._generate_summary(old_messages)

        # Create a summary message
        summary_msg = Message(
            id=str(uuid4()),
            conversation_id=old_messages[0].conversation_id if old_messages else None,
            sender_type=SenderType.SYSTEM,
            sender_id="memory_service",
            receiver_type=ReceiverType.AGENT,
            receiver_id=None,
            message_type=MessageType.SYSTEM,
            content=f"[历史对话摘要]\n{summary}",
            created_at=datetime.utcnow(),
        )

        return [summary_msg] + recent_messages, summary

    async def _generate_summary(self, messages: list[Message]) -> str:
        """Generate a summary of messages.

        Args:
            messages: Messages to summarize.

        Returns:
            Summary text.
        """
        if not messages:
            return ""

        # Format messages for LLM
        history_text = "\n".join([
            f"{msg.sender_type.value}: {msg.content[:500]}"
            for msg in messages[-20:]  # Limit to last 20 for summary
        ])

        prompt = f"""请对以下对话历史进行简洁的总结，保留关键信息和决策点：

{history_text}

总结要点：
1. 讨论的主要话题
2. 做出的重要决定
3. 未解决的问题（如果有）

请用简洁的中文总结："""

        try:
            summary = await llm_service.simple_complete(
                prompt,
                system_prompt="你是一个对话总结助手，擅长提取对话中的关键信息。",
                max_tokens=500,
            )
            return summary
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            # Fallback: return a simple list of topics
            topics = set()
            for msg in messages:
                content = msg.content or ""
                # Extract first sentence or first 50 chars
                first_part = content.split('。')[0][:50]
                if first_part:
                    topics.add(first_part)
            return f"历史对话涉及：{'; '.join(list(topics)[:5])}"

    async def create_conversation(
        self,
        session: AsyncSession,
        task_id: str | None = None,
        agent_a_id: str | None = None,
        agent_b_id: str | None = None,
        channel_id: str | None = None,
    ) -> str:
        """Create a new conversation.

        Args:
            session: Database session.
            task_id: Optional task ID.
            agent_a_id: Optional first agent ID.
            agent_b_id: Optional second agent ID.
            channel_id: Optional channel ID.

        Returns:
            Conversation ID.
        """
        from backend.models.conversation import Conversation

        conversation_id = str(uuid4())
        conversation = Conversation(
            id=conversation_id,
            task_id=task_id,
            agent_a_id=agent_a_id,
            agent_b_id=agent_b_id,
            channel_id=channel_id,
        )
        session.add(conversation)
        await session.flush()
        return conversation_id

    def messages_to_chat_messages(
        self,
        messages: list[Message],
        include_summary: bool = True,
    ) -> list[ChatMessage]:
        """Convert database messages to ChatMessage format.

        Args:
            messages: Database messages.
            include_summary: Whether to include system summaries.

        Returns:
            List of ChatMessage objects.
        """
        chat_messages = []

        for msg in messages:
            # Skip system messages unless it's a summary
            if msg.sender_type == SenderType.SYSTEM:
                if include_summary and msg.message_type == MessageType.SYSTEM:
                    chat_messages.append(ChatMessage(
                        role="system",
                        content=msg.content,
                    ))
                continue

            # Map sender type to role
            if msg.sender_type == SenderType.USER or msg.sender_type == SenderType.CHANNEL:
                role = "user"
            elif msg.sender_type in [SenderType.AGENT, SenderType.RESIDENT,
                                     SenderType.OWNER, SenderType.WORKER]:
                role = "assistant"
            else:
                continue

            chat_messages.append(ChatMessage(
                role=role,
                content=msg.content,
            ))

        return chat_messages


# Global memory service instance
memory_service = MemoryService()
