"""
Agent Settings Service for LongClaw.
Manages configurable system prompts and model assignments for agent types and individual agents.
"""
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import AgentType
from backend.models.agent_settings import AgentSettings

logger = logging.getLogger(__name__)


# Default context limits for each agent type (in tokens)
DEFAULT_CONTEXT_LIMITS: dict[AgentType, int] = {
    AgentType.RESIDENT: 64000,
    AgentType.OWNER: 128000,
    AgentType.WORKER: 64000,
    AgentType.SUB: 32000,
}

# Special value for unlimited context (-1 means unlimited, consistent with system config)
UNLIMITED_CONTEXT = -1


# Default prompts for each agent type
DEFAULT_PROMPTS: dict[AgentType, str] = {
    AgentType.RESIDENT: """你叫老六，是一个靠谱的AI助手，性格有点皮。直接用中文回复。

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
    AgentType.OWNER: """你是一个任务调度专家，负责分析用户任务并拆解为可并行执行的子任务。

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
    AgentType.WORKER: """你是一个执行型 Agent，负责完成特定的子任务。

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
    AgentType.SUB: """你是一个执行型 Agent，负责完成特定的子任务。

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


class AgentSettingsService:
    """Service for managing agent settings including prompts and model assignments."""

    async def get_all_settings(self, session: AsyncSession) -> dict[str, Any]:
        """Get all agent settings.

        Returns both type-level defaults and instance-level overrides.

        Args:
            session: Database session.

        Returns:
            Dictionary with type_settings and instance_settings.
        """
        # Get all stored settings
        result = await session.execute(select(AgentSettings))
        settings = result.scalars().all()

        # Separate type-level and instance-level settings
        type_settings: dict[str, dict[str, Any]] = {}
        instance_settings: dict[str, dict[str, Any]] = {}

        for setting in settings:
            if setting.agent_type:
                type_settings[setting.agent_type.value] = {
                    "id": setting.id,
                    "agent_type": setting.agent_type.value,
                    "system_prompt": setting.system_prompt,
                    "provider_name": setting.provider_name,
                    "model_name": setting.model_name,
                    "max_context_tokens": setting.max_context_tokens,
                    "created_at": setting.created_at.isoformat(),
                    "updated_at": setting.updated_at.isoformat(),
                }
            elif setting.agent_id:
                instance_settings[setting.agent_id] = {
                    "id": setting.id,
                    "agent_id": setting.agent_id,
                    "system_prompt": setting.system_prompt,
                    "provider_name": setting.provider_name,
                    "model_name": setting.model_name,
                    "max_context_tokens": setting.max_context_tokens,
                    "created_at": setting.created_at.isoformat(),
                    "updated_at": setting.updated_at.isoformat(),
                }

        # Add default settings for missing types
        for agent_type in AgentType:
            if agent_type.value not in type_settings:
                type_settings[agent_type.value] = {
                    "id": None,
                    "agent_type": agent_type.value,
                    "system_prompt": DEFAULT_PROMPTS.get(agent_type, ""),
                    "provider_name": None,
                    "model_name": None,
                    "max_context_tokens": DEFAULT_CONTEXT_LIMITS.get(agent_type),
                    "is_default": True,
                }

        return {
            "type_settings": type_settings,
            "instance_settings": instance_settings,
        }

    async def get_type_settings(
        self, session: AsyncSession, agent_type: AgentType
    ) -> dict[str, Any]:
        """Get settings for an agent type.

        Args:
            session: Database session.
            agent_type: Agent type.

        Returns:
            Type-level settings dictionary.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if setting:
            return {
                "id": setting.id,
                "agent_type": setting.agent_type.value,
                "system_prompt": setting.system_prompt,
                "provider_name": setting.provider_name,
                "model_name": setting.model_name,
                "max_context_tokens": setting.max_context_tokens,
                "created_at": setting.created_at.isoformat(),
                "updated_at": setting.updated_at.isoformat(),
            }

        # Return default settings
        return {
            "id": None,
            "agent_type": agent_type.value,
            "system_prompt": DEFAULT_PROMPTS.get(agent_type, ""),
            "provider_name": None,
            "model_name": None,
            "max_context_tokens": DEFAULT_CONTEXT_LIMITS.get(agent_type),
            "is_default": True,
        }

    async def get_agent_settings(
        self, session: AsyncSession, agent_id: str, agent_type: AgentType | None = None
    ) -> dict[str, Any]:
        """Get settings for a specific agent with fallback to type-level.

        Checks for instance-level override first, then falls back to type-level default.

        Args:
            session: Database session.
            agent_id: Agent ID.
            agent_type: Agent type for fallback.

        Returns:
            Agent settings dictionary.
        """
        # Check for instance-level override
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if setting:
            return {
                "id": setting.id,
                "agent_id": setting.agent_id,
                "system_prompt": setting.system_prompt,
                "provider_name": setting.provider_name,
                "model_name": setting.model_name,
                "max_context_tokens": setting.max_context_tokens,
                "is_instance_override": True,
                "created_at": setting.created_at.isoformat(),
                "updated_at": setting.updated_at.isoformat(),
            }

        # Fall back to type-level default
        if agent_type:
            type_settings = await self.get_type_settings(session, agent_type)
            type_settings["is_instance_override"] = False
            return type_settings

        return {
            "id": None,
            "agent_id": agent_id,
            "system_prompt": "",
            "provider_name": None,
            "model_name": None,
            "is_instance_override": False,
        }

    async def set_type_prompt(
        self, session: AsyncSession, agent_type: AgentType, system_prompt: str
    ) -> AgentSettings:
        """Set the default prompt for an agent type.

        Args:
            session: Database session.
            agent_type: Agent type.
            system_prompt: System prompt content.

        Returns:
            Created or updated AgentSettings instance.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.system_prompt = system_prompt
            setting.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated prompt for type {agent_type.value}")
            return setting

        # Create new setting
        setting = AgentSettings(
            id=str(uuid4()),
            agent_type=agent_type,
            system_prompt=system_prompt,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for type {agent_type.value}")
        return setting

    async def set_type_model(
        self, session: AsyncSession, agent_type: AgentType, provider: str, model: str
    ) -> AgentSettings:
        """Set the default model for an agent type.

        Args:
            session: Database session.
            agent_type: Agent type.
            provider: Provider name.
            model: Model name.

        Returns:
            Created or updated AgentSettings instance.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.provider_name = provider
            setting.model_name = model
            setting.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated model for type {agent_type.value}: {provider}/{model}")
            return setting

        # Create new setting with default prompt
        setting = AgentSettings(
            id=str(uuid4()),
            agent_type=agent_type,
            system_prompt=DEFAULT_PROMPTS.get(agent_type, ""),
            provider_name=provider,
            model_name=model,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for type {agent_type.value}: {provider}/{model}")
        return setting

    async def set_agent_prompt(
        self, session: AsyncSession, agent_id: str, system_prompt: str
    ) -> AgentSettings:
        """Set the override prompt for a specific agent.

        Args:
            session: Database session.
            agent_id: Agent ID.
            system_prompt: System prompt content.

        Returns:
            Created or updated AgentSettings instance.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.system_prompt = system_prompt
            setting.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated prompt for agent {agent_id}")
            return setting

        # Create new setting
        setting = AgentSettings(
            id=str(uuid4()),
            agent_id=agent_id,
            system_prompt=system_prompt,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for agent {agent_id}")
        return setting

    async def set_agent_model(
        self, session: AsyncSession, agent_id: str, provider: str, model: str
    ) -> AgentSettings:
        """Set the override model for a specific agent.

        Args:
            session: Database session.
            agent_id: Agent ID.
            provider: Provider name.
            model: Model name.

        Returns:
            Created or updated AgentSettings instance.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if setting:
            setting.provider_name = provider
            setting.model_name = model
            setting.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated model for agent {agent_id}: {provider}/{model}")
            return setting

        # Create new setting
        setting = AgentSettings(
            id=str(uuid4()),
            agent_id=agent_id,
            system_prompt="",
            provider_name=provider,
            model_name=model,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for agent {agent_id}: {provider}/{model}")
        return setting

    async def get_effective_model(
        self, session: AsyncSession, agent_id: str, agent_type: AgentType
    ) -> tuple[str | None, str | None]:
        """Get the effective model for an agent.

        Resolution order:
        1. Agent's own model_assignment field
        2. Instance-level AgentSettings for this agent_id
        3. Type-level AgentSettings for this agent_type
        4. None (use default from ModelConfigService)

        Args:
            session: Database session.
            agent_id: Agent ID.
            agent_type: Agent type.

        Returns:
            Tuple of (provider_name, model_name) or (None, None) for default.
        """
        # Check instance-level settings first
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if setting and setting.provider_name and setting.model_name:
            return (setting.provider_name, setting.model_name)

        # Check type-level settings
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if setting and setting.provider_name and setting.model_name:
            return (setting.provider_name, setting.model_name)

        # Return None to use default
        return (None, None)

    async def get_effective_prompt(
        self, session: AsyncSession, agent_id: str, agent_type: AgentType
    ) -> str:
        """Get the effective prompt for an agent.

        Args:
            session: Database session.
            agent_id: Agent ID.
            agent_type: Agent type.

        Returns:
            System prompt string.
        """
        # Check instance-level override
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if setting and setting.system_prompt:
            return setting.system_prompt

        # Check type-level settings
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if setting and setting.system_prompt:
            return setting.system_prompt

        # Return default prompt
        return DEFAULT_PROMPTS.get(agent_type, "")

    async def get_effective_context_limit(
        self, session: AsyncSession, agent_id: str | None, agent_type: AgentType
    ) -> int:
        """Get the effective context limit for an agent (agent-level only, not considering model limit).

        Resolution order:
        1. Instance-level AgentSettings.max_context_tokens (if agent_id provided)
        2. Type-level AgentSettings.max_context_tokens
        3. Default from DEFAULT_CONTEXT_LIMITS

        Note: This returns the agent-level context limit. The actual effective limit
        should be min(agent_limit, model_limit). Use get_final_context_limit() for that.

        Args:
            session: Database session.
            agent_id: Agent ID (optional).
            agent_type: Agent type.

        Returns:
            Context limit in tokens (0 means unlimited).
        """
        # Check instance-level settings first if agent_id is provided
        if agent_id:
            result = await session.execute(
                select(AgentSettings).where(AgentSettings.agent_id == agent_id)
            )
            setting = result.scalar_one_or_none()
            if setting and setting.max_context_tokens is not None:
                return setting.max_context_tokens

        # Check type-level settings
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()
        if setting and setting.max_context_tokens is not None:
            return setting.max_context_tokens

        # Return default
        return DEFAULT_CONTEXT_LIMITS.get(agent_type, 8192)

    async def get_final_context_limit(
        self,
        session: AsyncSession,
        agent_id: str | None,
        agent_type: AgentType,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> int:
        """Get the final context limit for an agent, considering both agent and model limits.

        The effective context limit is min(agent_limit, model_limit).
        If either is 0 (unlimited), the other value is used.
        If both are 0 (unlimited), returns 0 (unlimited).

        Args:
            session: Database session.
            agent_id: Agent ID (optional).
            agent_type: Agent type.
            provider_name: Provider name (optional, for model limit lookup).
            model_name: Model name (optional, for model limit lookup).

        Returns:
            Final context limit in tokens (0 means unlimited).
        """
        # Get agent-level limit
        agent_limit = await self.get_effective_context_limit(session, agent_id, agent_type)

        # Get model-level limit if provider and model are specified
        model_limit = None
        if provider_name and model_name:
            from backend.services.model_config_service import model_config_service
            model_limit = await model_config_service.get_model_context_limit(
                session, provider_name, model_name
            )

        # Calculate final limit
        if agent_limit == UNLIMITED_CONTEXT:
            # Agent is unlimited, use model limit (or unlimited if model is also unlimited/not specified)
            if model_limit is None or model_limit == UNLIMITED_CONTEXT:
                return UNLIMITED_CONTEXT
            return model_limit

        if model_limit is None:
            # No model limit specified, use agent limit
            return agent_limit

        if model_limit == UNLIMITED_CONTEXT:
            # Model is unlimited, use agent limit
            return agent_limit

        # Both have specific limits, use the smaller one
        return min(agent_limit, model_limit)

    async def delete_agent_settings(
        self, session: AsyncSession, agent_id: str
    ) -> bool:
        """Delete the override settings for a specific agent.

        Args:
            session: Database session.
            agent_id: Agent ID.

        Returns:
            True if deleted, False if not found.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if not setting:
            return False

        await session.delete(setting)
        await session.flush()
        logger.info(f"Deleted settings for agent {agent_id}")
        return True

    async def reset_type_settings(
        self, session: AsyncSession, agent_type: AgentType
    ) -> bool:
        """Reset the settings for an agent type to default.

        Args:
            session: Database session.
            agent_type: Agent type.

        Returns:
            True if reset, False if not found.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if not setting:
            return False

        await session.delete(setting)
        await session.flush()
        logger.info(f"Reset settings for type {agent_type.value}")
        return True

    async def update_type_settings(
        self,
        session: AsyncSession,
        agent_type: AgentType,
        system_prompt: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        max_context_tokens: int | None = None,
    ) -> AgentSettings:
        """Update multiple settings for an agent type at once.

        Args:
            session: Database session.
            agent_type: Agent type.
            system_prompt: Optional system prompt.
            provider_name: Optional provider name.
            model_name: Optional model name.
            max_context_tokens: Optional context limit.

        Returns:
            Created or updated AgentSettings instance.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_type == agent_type)
        )
        setting = result.scalar_one_or_none()

        if setting:
            if system_prompt is not None:
                setting.system_prompt = system_prompt
            if provider_name is not None:
                setting.provider_name = provider_name
            if model_name is not None:
                setting.model_name = model_name
            if max_context_tokens is not None:
                setting.max_context_tokens = max_context_tokens
            setting.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated settings for type {agent_type.value}")
            return setting

        # Create new setting
        setting = AgentSettings(
            id=str(uuid4()),
            agent_type=agent_type,
            system_prompt=system_prompt or DEFAULT_PROMPTS.get(agent_type, ""),
            provider_name=provider_name,
            model_name=model_name,
            max_context_tokens=max_context_tokens,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for type {agent_type.value}")
        return setting

    async def update_agent_settings(
        self,
        session: AsyncSession,
        agent_id: str,
        system_prompt: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        max_context_tokens: int | None = None,
    ) -> AgentSettings:
        """Update multiple settings for a specific agent at once.

        Args:
            session: Database session.
            agent_id: Agent ID.
            system_prompt: Optional system prompt.
            provider_name: Optional provider name.
            model_name: Optional model name.
            max_context_tokens: Optional context limit.

        Returns:
            Created or updated AgentSettings instance.
        """
        result = await session.execute(
            select(AgentSettings).where(AgentSettings.agent_id == agent_id)
        )
        setting = result.scalar_one_or_none()

        if setting:
            if system_prompt is not None:
                setting.system_prompt = system_prompt
            if provider_name is not None:
                setting.provider_name = provider_name
            if model_name is not None:
                setting.model_name = model_name
            if max_context_tokens is not None:
                setting.max_context_tokens = max_context_tokens
            setting.updated_at = datetime.utcnow()
            await session.flush()
            logger.info(f"Updated settings for agent {agent_id}")
            return setting

        # Create new setting
        setting = AgentSettings(
            id=str(uuid4()),
            agent_id=agent_id,
            system_prompt=system_prompt or "",
            provider_name=provider_name,
            model_name=model_name,
            max_context_tokens=max_context_tokens,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(setting)
        await session.flush()
        logger.info(f"Created settings for agent {agent_id}")
        return setting


# Global agent settings service instance
agent_settings_service = AgentSettingsService()
