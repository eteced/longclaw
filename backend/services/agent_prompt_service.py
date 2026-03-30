"""
Agent Prompt Service for LongClaw.
Manages configurable system prompts for agent types and individual agents.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent_prompt import AgentPrompt, PromptType

logger = logging.getLogger(__name__)


# Default prompts for each agent type
DEFAULT_PROMPTS: dict[PromptType, str] = {
    PromptType.RESIDENT: """你叫老六，是一个靠谱的AI助手，性格有点皮。直接用中文回复。

## 时间认知
系统消息中已包含当前日期和时间。当用户提到"今天"、"昨天"、"最近"、"本周"等时间词时：
- 根据系统时间理解具体日期
- 涉及时间范围的任务时，主动计算具体日期范围
- 在搜索关键词中包含具体日期

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
- 搜索到信息后要给出信息来源链接""",
    PromptType.OWNER: """你是一个任务调度专家，负责分析用户任务并拆解为可并行执行的子任务。

## 时间认知
系统消息中已包含当前日期和时间。当任务涉及"最新"、"最近"、"今天"、"本周"等时间相关词汇时：
- 直接根据当前时间计算具体日期范围
- 在子任务描述中包含具体的日期范围（如"2026年3月23日至2026年3月24日"）
- 不要猜测日期，使用系统提供的时间信息

## 核心原则

### 1. 先评估信息缺口
拆解任务前，先分析：
- 是否需要当前时间信息？（已在系统消息中提供）
- 是否需要搜索最新信息？
- 是否需要背景知识？
- 如果缺少必要信息，将信息收集作为第一个子任务

### 2. 最大化并行化
- 不同信息来源的搜索可以并行执行
- 不同维度的分析可以并行执行
- 只有依赖关系才需要串行
- 典型模式：多个并行搜索任务 → 一个整合任务

### 3. 子任务描述要具体明确
每个子任务描述应该：
- 包含具体的搜索关键词或分析维度
- 包含具体的时间范围（如涉及时间）
- 让 Worker Agent 无需额外推理就能执行
- 避免模糊的描述如"搜索相关新闻"

## 输出格式
分析任务后，返回 JSON 格式的子任务列表：
```json
{
  "analysis": "任务分析说明，包括信息缺口分析和并行化策略",
  "subtasks": [
    {
      "id": "1",
      "description": "子任务描述（具体、明确、包含参数）",
      "tools_needed": ["web_search", "web_fetch"]
    }
  ]
}
```""",
    PromptType.WORKER: """你是一个执行型 Agent，负责完成特定的子任务。

## 时间认知
系统消息中已包含当前日期和时间。当任务涉及时间范围时：
- 根据当前时间计算具体日期范围
- 搜索关键词中包含具体日期（如"2026年3月22日至3月23日"）
- 不要猜测日期，使用系统提供的时间信息

## 可用工具
- web_search(query): 搜索互联网信息
- web_fetch(url): 抓取网页详细内容

## 执行策略
1. **理解任务**：仔细阅读任务描述，识别关键信息需求和时间范围
2. **制定搜索词**：构建具体、精确的搜索关键词，包含时间范围
3. **执行搜索**：调用 web_search 获取信息
4. **深入获取**：对重要结果使用 web_fetch 获取详细内容
5. **验证补充**：如果信息不足，调整关键词再次搜索
6. **整理输出**：汇总结果，给出简洁、准确的回答

## 搜索技巧
- 关键词要具体：不用"AI新闻"，用"OpenAI GPT-5 发布 2026年3月"
- 包含时间范围：不用"最新"，用"2026年3月22日至23日"
- 多角度搜索：如果首次结果不理想，换关键词重试
- 验证来源：重要信息要访问原网页确认

## 输出要求
- 结果要简洁但有信息量
- 标明信息来源（网址链接）
- 如果信息不足，说明"未能找到相关信息"
- 不要编造或猜测事实信息""",
    PromptType.SUB: """你是一个执行型 Agent，负责完成特定的子任务。

## 时间认知
系统消息中已包含当前日期和时间。当任务涉及时间范围时：
- 根据当前时间计算具体日期范围
- 搜索关键词中包含具体日期（如"2026年3月22日至3月23日"）
- 不要猜测日期，使用系统提供的时间信息

## 可用工具
- web_search(query): 搜索互联网信息
- web_fetch(url): 抓取网页详细内容

## 执行策略
1. **理解任务**：仔细阅读任务描述，识别关键信息需求和时间范围
2. **制定搜索词**：构建具体、精确的搜索关键词，包含时间范围
3. **执行搜索**：调用 web_search 获取信息
4. **深入获取**：对重要结果使用 web_fetch 获取详细内容
5. **验证补充**：如果信息不足，调整关键词再次搜索
6. **整理输出**：汇总结果，给出简洁、准确的回答

## 搜索技巧
- 关键词要具体：不用"AI新闻"，用"OpenAI GPT-5 发布 2026年3月"
- 包含时间范围：不用"最新"，用"2026年3月22日至23日"
- 多角度搜索：如果首次结果不理想，换关键词重试
- 验证来源：重要信息要访问原网页确认

## 输出要求
- 结果要简洁但有信息量
- 标明信息来源（网址链接）
- 如果信息不足，说明"未能找到相关信息"
- 不要编造或猜测事实信息""",
}


class AgentPromptService:
    """Service for managing agent prompts."""

    async def get_all_prompts(self, session: AsyncSession) -> dict[str, Any]:
        """Get all prompt configurations.

        Returns both type-level defaults and instance-level overrides.

        Args:
            session: Database session.

        Returns:
            Dictionary with type_prompts and instance_prompts.
        """
        # Get all stored prompts
        result = await session.execute(select(AgentPrompt))
        prompts = result.scalars().all()

        # Separate type-level and instance-level prompts
        type_prompts: dict[str, dict[str, Any]] = {}
        instance_prompts: dict[str, dict[str, Any]] = {}

        for prompt in prompts:
            if prompt.agent_type:
                type_prompts[prompt.agent_type.value] = {
                    "id": prompt.id,
                    "agent_type": prompt.agent_type.value,
                    "system_prompt": prompt.system_prompt,
                    "created_at": prompt.created_at.isoformat(),
                    "updated_at": prompt.updated_at.isoformat(),
                }
            elif prompt.agent_id:
                instance_prompts[prompt.agent_id] = {
                    "id": prompt.id,
                    "agent_id": prompt.agent_id,
                    "system_prompt": prompt.system_prompt,
                    "created_at": prompt.created_at.isoformat(),
                    "updated_at": prompt.updated_at.isoformat(),
                }

        # Add default prompts for missing types
        for prompt_type in PromptType:
            if prompt_type.value not in type_prompts:
                type_prompts[prompt_type.value] = {
                    "id": None,
                    "agent_type": prompt_type.value,
                    "system_prompt": DEFAULT_PROMPTS.get(prompt_type, ""),
                    "is_default": True,
                }

        return {
            "type_prompts": type_prompts,
            "instance_prompts": instance_prompts,
        }

    async def get_type_prompt(
        self, session: AsyncSession, prompt_type: PromptType
    ) -> str:
        """Get the system prompt for an agent type.

        Args:
            session: Database session.
            prompt_type: Agent type.

        Returns:
            System prompt string.
        """
        result = await session.execute(
            select(AgentPrompt).where(AgentPrompt.agent_type == prompt_type)
        )
        prompt = result.scalar_one_or_none()

        if prompt:
            return prompt.system_prompt

        # Return default prompt
        return DEFAULT_PROMPTS.get(prompt_type, "")

    async def get_agent_prompt(
        self, session: AsyncSession, agent_id: str, agent_type: PromptType | None = None
    ) -> str:
        """Get the system prompt for a specific agent.

        Checks for instance-level override first, then falls back to type-level default.

        Args:
            session: Database session.
            agent_id: Agent ID.
            agent_type: Agent type for fallback.

        Returns:
            System prompt string.
        """
        # Check for instance-level override
        result = await session.execute(
            select(AgentPrompt).where(AgentPrompt.agent_id == agent_id)
        )
        prompt = result.scalar_one_or_none()

        if prompt:
            return prompt.system_prompt

        # Fall back to type-level default
        if agent_type:
            return await self.get_type_prompt(session, agent_type)

        return ""

    async def set_type_prompt(
        self, session: AsyncSession, prompt_type: PromptType, system_prompt: str
    ) -> AgentPrompt:
        """Set the default prompt for an agent type.

        Args:
            session: Database session.
            prompt_type: Agent type.
            system_prompt: System prompt content.

        Returns:
            Created or updated AgentPrompt instance.
        """
        result = await session.execute(
            select(AgentPrompt).where(AgentPrompt.agent_type == prompt_type)
        )
        prompt = result.scalar_one_or_none()

        if prompt:
            prompt.system_prompt = system_prompt
            prompt.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated prompt for type {prompt_type.value}")
            return prompt

        # Create new prompt
        prompt = AgentPrompt(
            id=str(uuid4()),
            agent_type=prompt_type,
            system_prompt=system_prompt,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(prompt)
        await session.flush()
        logger.info(f"Created prompt for type {prompt_type.value}")
        return prompt

    async def set_agent_prompt(
        self, session: AsyncSession, agent_id: str, system_prompt: str
    ) -> AgentPrompt:
        """Set the override prompt for a specific agent.

        Args:
            session: Database session.
            agent_id: Agent ID.
            system_prompt: System prompt content.

        Returns:
            Created or updated AgentPrompt instance.
        """
        result = await session.execute(
            select(AgentPrompt).where(AgentPrompt.agent_id == agent_id)
        )
        prompt = result.scalar_one_or_none()

        if prompt:
            prompt.system_prompt = system_prompt
            prompt.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated prompt for agent {agent_id}")
            return prompt

        # Create new prompt
        prompt = AgentPrompt(
            id=str(uuid4()),
            agent_id=agent_id,
            system_prompt=system_prompt,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(prompt)
        await session.flush()
        logger.info(f"Created prompt for agent {agent_id}")
        return prompt

    async def delete_agent_prompt(
        self, session: AsyncSession, agent_id: str
    ) -> bool:
        """Delete the override prompt for a specific agent.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            True if deleted, False if not found.
        """
        result = await session.execute(
            select(AgentPrompt).where(AgentPrompt.agent_id == agent_id)
        )
        prompt = result.scalar_one_or_none()

        if not prompt:
            return False

        await session.delete(prompt)
        await session.flush()
        logger.info(f"Deleted prompt for agent {agent_id}")
        return True

    async def reset_type_prompt(
        self, session: AsyncSession, prompt_type: PromptType
    ) -> bool:
        """Reset the prompt for an agent type to default.

        Args:
            session: Database session.
            prompt_type: Agent type.

        Returns:
            True if reset, False if not found.
        """
        result = await session.execute(
            select(AgentPrompt).where(AgentPrompt.agent_type == prompt_type)
        )
        prompt = result.scalar_one_or_none()

        if not prompt:
            return False

        await session.delete(prompt)
        await session.flush()
        logger.info(f"Reset prompt for type {prompt_type.value}")
        return True


# Global agent prompt service instance
agent_prompt_service = AgentPromptService()
