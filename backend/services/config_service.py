"""
Configuration Service for LongClaw.
Manages system configuration with in-memory caching, profiles, and export/import.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.models.system_config import SystemConfig
from backend.models.config_profile import ConfigProfile

logger = logging.getLogger(__name__)

# Configuration metadata - defines type, category, and special values
CONFIG_METADATA: dict[str, dict[str, Any]] = {
    # Timeout configurations
    "resident_chat_timeout": {
        "type": "timeout",
        "category": "timeout",
        "unlimited_value": -1,
        "display_name": "Resident Agent 聊天超时",
        "unit": "秒",
        "min_value": 10,
        "max_value": 86400,  # 24 hours
    },
    "owner_task_timeout": {
        "type": "timeout",
        "category": "timeout",
        "unlimited_value": -1,
        "display_name": "Owner Agent 任务超时",
        "unit": "秒",
        "min_value": 30,
        "max_value": 86400,
    },
    "worker_subtask_timeout": {
        "type": "timeout",
        "category": "timeout",
        "unlimited_value": -1,
        "display_name": "Worker 子任务超时",
        "unit": "秒",
        "min_value": 10,
        "max_value": 3600,
    },
    "worker_waiting_owner_timeout": {
        "type": "timeout",
        "category": "timeout",
        "unlimited_value": -1,
        "display_name": "Worker 等待 Owner 响应超时",
        "unit": "秒",
        "min_value": 10,
        "max_value": 86400,
    },
    "llm_request_timeout": {
        "type": "timeout",
        "category": "llm",
        "unlimited_value": -1,
        "display_name": "LLM 请求超时",
        "unit": "秒",
        "min_value": 10,
        "max_value": 1800,
    },
    "llm_connect_timeout": {
        "type": "timeout",
        "category": "llm",
        "unlimited_value": -1,
        "display_name": "LLM 连接超时",
        "unit": "秒",
        "min_value": 5,
        "max_value": 300,
    },
    "tool_http_timeout": {
        "type": "timeout",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "Tool HTTP 超时",
        "unit": "秒",
        "min_value": 5,
        "max_value": 600,
    },
    "tool_connect_timeout": {
        "type": "timeout",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "Tool 连接超时",
        "unit": "秒",
        "min_value": 1,
        "max_value": 120,
    },
    "command_timeout": {
        "type": "timeout",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "命令执行超时",
        "unit": "秒",
        "min_value": 1,
        "max_value": 3600,
    },
    "tool_search_timeout": {
        "type": "timeout",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "网页搜索超时",
        "unit": "秒",
        "min_value": 10,
        "max_value": 300,
    },
    "tool_fetch_timeout": {
        "type": "timeout",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "网页抓取超时",
        "unit": "秒",
        "min_value": 10,
        "max_value": 300,
    },
    "chrome_max_processes": {
        "type": "limit",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "Chrome 进程最大数量",
        "unit": "个",
        "min_value": 1,
        "max_value": 100,
    },
    "chrome_cleanup_interval": {
        "type": "interval",
        "category": "tool",
        "unlimited_value": None,
        "display_name": "Chrome 清理检查间隔",
        "unit": "秒",
        "min_value": 10,
        "max_value": 600,
    },
    "chrome_session_max_age": {
        "type": "timeout",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "Chrome 孤儿会话判定时间",
        "unit": "秒",
        "min_value": 30,
        "max_value": 600,
    },
    "scheduler_agent_timeout": {
        "type": "timeout",
        "category": "scheduler",
        "unlimited_value": -1,
        "display_name": "Agent 不活跃判定阈值",
        "unit": "秒",
        "min_value": 60,
        "max_value": 3600,
    },
    "scheduler_check_interval": {
        "type": "interval",
        "category": "scheduler",
        "unlimited_value": None,  # No unlimited for intervals
        "display_name": "Scheduler 检查间隔",
        "unit": "秒",
        "min_value": 5,
        "max_value": 300,
    },
    "reflect_check_interval": {
        "type": "interval",
        "category": "scheduler",
        "unlimited_value": None,
        "display_name": "Reflect 检查间隔",
        "unit": "秒",
        "min_value": 10,
        "max_value": 300,
    },
    "reflect_stuck_threshold": {
        "type": "timeout",
        "category": "scheduler",
        "unlimited_value": -1,
        "display_name": "停滞判定阈值",
        "unit": "秒",
        "min_value": 30,
        "max_value": 1800,
    },
    # Limit configurations
    "tool_max_rounds": {
        "type": "limit",
        "category": "tool",
        "unlimited_value": -1,
        "display_name": "最大工具调用轮数",
        "unit": "轮",
        "min_value": 1,
        "max_value": 100,
    },
    "memory_token_limit": {
        "type": "limit",
        "category": "memory",
        "unlimited_value": -1,
        "display_name": "会话 Token 上限",
        "unit": "tokens",
        "min_value": 500,
        "max_value": 100000,
    },
    "memory_keep_recent": {
        "type": "limit",
        "category": "memory",
        "unlimited_value": None,
        "display_name": "保留最近消息数",
        "unit": "条",
        "min_value": 1,
        "max_value": 50,
    },
    "memory_compact_threshold": {
        "type": "threshold",
        "category": "memory",
        "unlimited_value": None,
        "display_name": "压缩触发阈值",
        "unit": "",  # 小数值，0.8 表示 80%
        "min_value": 0.1,
        "max_value": 1.0,
    },
    "memory_search_limit": {
        "type": "limit",
        "category": "memory",
        "unlimited_value": -1,
        "display_name": "记忆搜索结果上限",
        "unit": "条",
        "min_value": 1,
        "max_value": 50,
    },
    "agent_max_context_tokens": {
        "type": "limit",
        "category": "context",
        "unlimited_value": -1,
        "display_name": "Agent 总上下文上限",
        "unit": "tokens",
        "min_value": 1024,
        "max_value": 200000,
    },
    "context_compact_threshold": {
        "type": "threshold",
        "category": "context",
        "unlimited_value": None,
        "display_name": "上下文压缩阈值",
        "unit": "",  # 小数值，0.8 表示 80%
        "min_value": 0.1,
        "max_value": 1.0,
    },
    # Boolean configurations
    "owner_confirm_dependencies": {
        "type": "boolean",
        "category": "feature",
        "unlimited_value": None,
        "display_name": "启用依赖确认",
        "unit": None,
    },
    "owner_max_iterations": {
        "type": "integer",
        "category": "feature",
        "unlimited_value": -1,
        "display_name": "Owner最大迭代次数",
        "unit": "次",
        "min_value": 1,
        "max_value": 100,
    },
    "force_complex_task": {
        "type": "boolean",
        "category": "feature",
        "unlimited_value": None,
        "display_name": "强制复杂任务流程",
        "unit": None,
    },
    "resident_always_allocate_slot": {
        "type": "boolean",
        "category": "scheduler",
        "unlimited_value": None,
        "display_name": "Resident常驻分配Slot",
        "unit": None,
        "description": "Resident Agent是否始终占用模型Slot。关闭后，空闲时释放Slot给其他Agent",
    },
    # String configurations
    "command_blacklist": {
        "type": "string",
        "category": "security",
        "unlimited_value": None,
        "display_name": "命令黑名单",
        "unit": None,
    },
}

# Preset profiles for different scenarios
PRESET_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "description": "默认配置，平衡性能与安全",
        "configs": {
            "resident_chat_timeout": "600",
            "owner_task_timeout": "600",
            "worker_subtask_timeout": "180",
            "llm_request_timeout": "300",
            "llm_connect_timeout": "30",
            "tool_http_timeout": "30",
            "tool_connect_timeout": "10",
            "tool_max_rounds": "6",
            "command_timeout": "60",
            "scheduler_agent_timeout": "300",
            "scheduler_check_interval": "10",
            "reflect_check_interval": "30",
            "reflect_stuck_threshold": "120",
            "memory_token_limit": "4000",
            "memory_keep_recent": "5",
            "memory_compact_threshold": "0.8",
            "memory_search_limit": "5",
            "agent_max_context_tokens": "8192",
            "context_compact_threshold": "0.8",
            "owner_confirm_dependencies": "true",
            "owner_max_iterations": "5",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "true",
        },
    },
    "high_performance": {
        "description": "高性能模式，更高的超时和上限，适合复杂任务",
        "configs": {
            "resident_chat_timeout": "1200",
            "owner_task_timeout": "1800",
            "worker_subtask_timeout": "600",
            "llm_request_timeout": "600",
            "llm_connect_timeout": "60",
            "tool_http_timeout": "120",
            "tool_connect_timeout": "30",
            "tool_max_rounds": "20",
            "command_timeout": "300",
            "scheduler_agent_timeout": "600",
            "scheduler_check_interval": "15",
            "reflect_check_interval": "60",
            "reflect_stuck_threshold": "300",
            "memory_token_limit": "16000",
            "memory_keep_recent": "10",
            "memory_compact_threshold": "0.9",
            "memory_search_limit": "10",
            "agent_max_context_tokens": "32768",
            "context_compact_threshold": "0.9",
            "owner_confirm_dependencies": "true",
            "owner_max_iterations": "5",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "true",
        },
    },
    "unlimited": {
        "description": "无限制模式，禁用所有超时和上限限制",
        "configs": {
            "resident_chat_timeout": "-1",
            "owner_task_timeout": "-1",
            "worker_subtask_timeout": "-1",
            "llm_request_timeout": "-1",
            "llm_connect_timeout": "-1",
            "tool_http_timeout": "-1",
            "tool_connect_timeout": "-1",
            "tool_max_rounds": "-1",
            "command_timeout": "-1",
            "scheduler_agent_timeout": "-1",
            "scheduler_check_interval": "10",
            "reflect_check_interval": "30",
            "reflect_stuck_threshold": "-1",
            "memory_token_limit": "-1",
            "memory_keep_recent": "20",
            "memory_compact_threshold": "0.95",
            "memory_search_limit": "-1",
            "agent_max_context_tokens": "-1",
            "context_compact_threshold": "0.95",
            "owner_confirm_dependencies": "true",
            "owner_max_iterations": "5",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "true",
        },
    },
    "safe_mode": {
        "description": "安全模式，较低的超时和限制，适合生产环境",
        "configs": {
            "resident_chat_timeout": "300",
            "owner_task_timeout": "300",
            "worker_subtask_timeout": "60",
            "llm_request_timeout": "120",
            "llm_connect_timeout": "15",
            "tool_http_timeout": "15",
            "tool_connect_timeout": "5",
            "tool_max_rounds": "3",
            "command_timeout": "30",
            "scheduler_agent_timeout": "180",
            "scheduler_check_interval": "5",
            "reflect_check_interval": "15",
            "reflect_stuck_threshold": "60",
            "memory_token_limit": "2000",
            "memory_keep_recent": "3",
            "memory_compact_threshold": "0.7",
            "memory_search_limit": "3",
            "agent_max_context_tokens": "4096",
            "context_compact_threshold": "0.7",
            "owner_confirm_dependencies": "true",
            "owner_max_iterations": "5",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "false",
        },
    },
    "debug": {
        "description": "调试模式，详细的日志和较短的超时，适合开发测试",
        "configs": {
            "resident_chat_timeout": "60",
            "owner_task_timeout": "120",
            "worker_subtask_timeout": "30",
            "llm_request_timeout": "60",
            "llm_connect_timeout": "10",
            "tool_http_timeout": "10",
            "tool_connect_timeout": "5",
            "tool_max_rounds": "5",
            "command_timeout": "30",
            "scheduler_agent_timeout": "120",
            "scheduler_check_interval": "5",
            "reflect_check_interval": "10",
            "reflect_stuck_threshold": "30",
            "memory_token_limit": "2000",
            "memory_keep_recent": "10",
            "memory_compact_threshold": "0.6",
            "memory_search_limit": "10",
            "agent_max_context_tokens": "4096",
            "context_compact_threshold": "0.6",
            "owner_confirm_dependencies": "false",
            "force_complex_task": "true",
            "resident_always_allocate_slot": "true",
        },
    },
}


# Default configuration values
DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "resident_chat_timeout": {
        "value": "600",
        "description": "Resident Agent 聊天回复超时（秒），-1 表示无限制",
    },
    "owner_task_timeout": {
        "value": "600",
        "description": "Owner Agent 任务执行总超时（秒），-1 表示无限制",
    },
    "worker_subtask_timeout": {
        "value": "180",
        "description": "Worker/SubAgent 单个子任务超时（秒），-1 表示无限制",
    },
    "llm_request_timeout": {
        "value": "300",
        "description": "LLM API 请求超时（秒），-1 表示无限制",
    },
    "llm_connect_timeout": {
        "value": "30",
        "description": "LLM API 连接超时（秒），-1 表示无限制",
    },
    "tool_http_timeout": {
        "value": "30",
        "description": "Tool HTTP 请求超时（秒），-1 表示无限制",
    },
    "tool_connect_timeout": {
        "value": "10",
        "description": "Tool HTTP 连接超时（秒），-1 表示无限制",
    },
    "tool_max_rounds": {
        "value": "6",
        "description": "单次任务最大工具调用轮数，-1 表示无限制",
    },
    "scheduler_agent_timeout": {
        "value": "300",
        "description": "Scheduler Agent 不活跃判定阈值（秒），-1 表示禁用检查",
    },
    "scheduler_check_interval": {
        "value": "10",
        "description": "Scheduler 检查间隔（秒）",
    },
    "command_blacklist": {
        "value": "rm -rf,mkfs,shutdown,reboot,halt,poweroff,init 0,init 6,dd if=,> /dev/sd,chmod -R 777 /,chown -R,chgrp -R,killall,kill -9 -1,crontab,useradd,userdel,passwd,visudo,iptables,ufw,firewall-cmd,systemctl stop,systemctl disable,systemctl restart,docker rm,docker rmi,docker system prune,kubectl delete,kubectl drain,kubectl scale",
        "description": "禁止执行的命令黑名单（逗号分隔）",
    },
    "command_timeout": {
        "value": "60",
        "description": "命令执行超时时间（秒），-1 表示无限制",
    },
    "memory_token_limit": {
        "value": "4000",
        "description": "单个会话的 token 上限，-1 表示无限制",
    },
    "memory_keep_recent": {
        "value": "5",
        "description": "压缩时保留的最近消息数",
    },
    "memory_compact_threshold": {
        "value": "0.8",
        "description": "触发压缩的比例阈值（0.8 表示 80%）",
    },
    "reflect_check_interval": {
        "value": "30",
        "description": "Reflect Agent 检查间隔（秒）",
    },
    "reflect_stuck_threshold": {
        "value": "120",
        "description": "Agent 被判定为停滞的时间阈值（秒），-1 表示禁用检查",
    },
    "agent_max_context_tokens": {
        "value": "8192",
        "description": "所有Agent的总上下文 token 上限，-1 表示无限制",
    },
    "context_compact_threshold": {
        "value": "0.8",
        "description": "达到上限的比例时触发压缩（0.8 表示 80%）",
    },
    "memory_search_limit": {
        "value": "5",
        "description": "记忆搜索返回的最大结果数，-1 表示无限制",
    },
    "owner_confirm_dependencies": {
        "value": "true",
        "description": "启用OwnerAgent两阶段依赖确认（推荐开启）",
    },
    "owner_max_iterations": {
        "value": "3",
        "description": "OwnerAgent 最大迭代次数，用于任务完成度评估和后续子任务生成",
    },
    "force_complex_task": {
        "value": "false",
        "description": "强制所有任务走OwnerAgent复杂任务流程（用于测试）",
    },
    "worker_waiting_owner_timeout": {
        "value": "120",
        "description": "Worker 等待 Owner 响应超时（秒），-1 表示无限制",
    },
    "resident_always_allocate_slot": {
        "value": "true",
        "description": "Resident Agent是否始终占用模型Slot。关闭后，空闲时释放Slot给其他Agent",
    },
    "resident_agent_max_context": {
        "value": "8192",
        "description": "Resident Agent 上下文 token 上限",
    },
    "owner_agent_max_context": {
        "value": "4096",
        "description": "Owner Agent 上下文 token 上限",
    },
    "worker_agent_max_context": {
        "value": "2048",
        "description": "Worker Agent 上下文 token 上限",
    },
    # Browser cleanup configs
    "chrome_max_processes": {
        "value": "10",
        "description": "Chrome 进程最大数量，超过此数量触发自动清理",
    },
    "chrome_cleanup_interval": {
        "value": "60",
        "description": "Chrome 清理检查间隔（秒）",
    },
    "chrome_session_max_age": {
        "value": "120",
        "description": "Chrome 孤儿会话判定时间（秒）",
    },
    "tool_search_timeout": {
        "value": "30",
        "description": "网页搜索超时时间（秒）",
    },
    "tool_fetch_timeout": {
        "value": "30",
        "description": "网页抓取超时时间（秒）",
    },
}


class ConfigService:
    """Service for managing system configuration.

    Provides cached access to configuration values with automatic refresh.
    Supports profiles, export/import, and unlimited value handling.
    """

    # Special value indicating unlimited (no timeout/limit)
    UNLIMITED_VALUE = -1

    def __init__(self) -> None:
        """Initialize the config service."""
        self._cache: dict[str, Any] = {}
        self._cache_lock: asyncio.Lock = asyncio.Lock()
        self._initialized: bool = False
        self._current_profile: str | None = None

    async def initialize(self) -> None:
        """Initialize the config service and load defaults into database."""
        async with db_manager.session() as session:
            # Initialize default configs
            for key, config in DEFAULT_CONFIGS.items():
                result = await session.execute(
                    select(SystemConfig).where(SystemConfig.config_key == key)
                )
                existing = result.scalar_one_or_none()

                if not existing:
                    new_config = SystemConfig(
                        config_key=key,
                        config_value=config["value"],
                        description=config["description"],
                        updated_at=datetime.utcnow(),
                    )
                    session.add(new_config)
                    logger.info(f"Created default config: {key}={config['value']}")

            await session.commit()

            # Initialize preset profiles
            for profile_name, profile_data in PRESET_PROFILES.items():
                result = await session.execute(
                    select(ConfigProfile).where(ConfigProfile.name == profile_name)
                )
                existing_profile = result.scalar_one_or_none()

                if not existing_profile:
                    new_profile = ConfigProfile(
                        id=str(uuid.uuid4()),
                        name=profile_name,
                        description=profile_data["description"],
                        config_data=profile_data["configs"],
                        is_default=(profile_name == "default"),
                    )
                    session.add(new_profile)
                    logger.info(f"Created preset profile: {profile_name}")

            await session.commit()

        # Load all configs into cache
        await self._refresh_cache()
        self._initialized = True
        logger.info("Config service initialized")

    async def _refresh_cache(self) -> None:
        """Refresh the in-memory cache from database."""
        async with db_manager.session() as session:
            result = await session.execute(select(SystemConfig))
            configs = result.scalars().all()

            async with self._cache_lock:
                self._cache.clear()
                for config in configs:
                    self._cache[config.config_key] = config.get_typed_value()

        logger.debug(f"Config cache refreshed: {len(self._cache)} items")

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        if not self._initialized:
            await self.initialize()

        async with self._cache_lock:
            return self._cache.get(key, default)

    async def get_int(self, key: str, default: int = 0) -> int | None:
        """Get a configuration value as integer.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value as integer, or None if value is -1 (unlimited).
            Note: -1 is the special "unlimited" value for limit configs.
        """
        value = await self.get(key, default)
        try:
            val = int(value)
            # -1 means unlimited, return None so callers can handle it
            return None if val == self.UNLIMITED_VALUE else val
        except (ValueError, TypeError):
            return default

    async def get_float(self, key: str, default: float = 0.0) -> float | None:
        """Get a configuration value as float.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value as float, or None if value is -1 (unlimited).
            Note: -1 is the special "unlimited" value for timeout/limit configs.
            asyncio.wait_for() and httpx.Timeout() treat negative values as expired,
            so returning None allows callers to use no timeout.
        """
        value = await self.get(key, default)
        try:
            val = float(value)
            # -1 means unlimited, return None so callers can skip timeout
            return None if val == self.UNLIMITED_VALUE else val
        except (ValueError, TypeError):
            return default

    async def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a configuration value as boolean.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value as boolean.
        """
        value = await self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def is_unlimited(self, key: str, value: int | float) -> bool:
        """Check if a value represents unlimited for a config key.

        Args:
            key: Configuration key.
            value: Current value.

        Returns:
            True if the value means unlimited.
        """
        metadata = CONFIG_METADATA.get(key, {})
        unlimited_value = metadata.get("unlimited_value")
        if unlimited_value is None:
            return False
        return value == unlimited_value

    async def get_effective_timeout(self, key: str, default: float | None = None) -> float | None:
        """Get effective timeout value, returning None for unlimited.

        This is a convenience method for timeout configs.
        Returns None if the config is set to unlimited (-1).

        Args:
            key: Configuration key.
            default: Default timeout value.

        Returns:
            Timeout in seconds, or None if unlimited.
        """
        value = await self.get_float(key, default or 0)
        if self.is_unlimited(key, value):
            return None
        return value

    async def get_all(self) -> list[dict[str, Any]]:
        """Get all configurations.

        Returns:
            List of configuration dictionaries.
        """
        if not self._initialized:
            await self.initialize()

        async with db_manager.session() as session:
            result = await session.execute(
                select(SystemConfig).order_by(SystemConfig.config_key)
            )
            configs = result.scalars().all()

            return [
                {
                    "key": config.config_key,
                    "value": config.config_value,
                    "description": config.description,
                    "updated_at": config.updated_at.isoformat(),
                    "metadata": CONFIG_METADATA.get(config.config_key, {}),
                }
                for config in configs
            ]

    async def set(self, key: str, value: str, session: AsyncSession | None = None) -> None:
        """Set a configuration value.

        Args:
            key: Configuration key.
            value: Configuration value.
            session: Optional database session.
        """
        if session is None:
            async with db_manager.session() as session:
                await self._set_in_session(session, key, value)
        else:
            await self._set_in_session(session, key, value)

        await self._refresh_cache()
        logger.info(f"Updated config: {key}={value}")

    async def _set_in_session(self, session: AsyncSession, key: str, value: str) -> None:
        """Set a configuration value within a session."""
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.config_key == key)
        )
        config = result.scalar_one_or_none()

        if config:
            config.config_value = value
            config.updated_at = datetime.utcnow()
        else:
            new_config = SystemConfig(
                config_key=key,
                config_value=value,
                description=DEFAULT_CONFIGS.get(key, {}).get("description"),
                updated_at=datetime.utcnow(),
            )
            session.add(new_config)

    async def set_multiple(self, configs: dict[str, str]) -> None:
        """Set multiple configuration values at once.

        Args:
            configs: Dictionary of key-value pairs.
        """
        async with db_manager.session() as session:
            for key, value in configs.items():
                await self._set_in_session(session, key, value)
            await session.commit()

        await self._refresh_cache()
        logger.info(f"Updated {len(configs)} configs")

    # ==================== Export/Import ====================

    async def export_config(self) -> dict[str, Any]:
        """Export all configurations as a dictionary.

        Returns:
            Dictionary with all configuration data.
        """
        configs = await self.get_all()
        return {
            "version": "1.0",
            "exported_at": datetime.utcnow().isoformat(),
            "configs": {
                config["key"]: {
                    "value": config["value"],
                    "description": config["description"],
                }
                for config in configs
            },
        }

    async def export_full_config(self) -> dict[str, Any]:
        """Export all configurations including system config, agent settings, and model config.

        Returns:
            Dictionary with all configuration data.
        """
        # Get system configs
        system_configs = await self.get_all()
        configs_dict = {
            config["key"]: {
                "value": config["value"],
                "description": config["description"],
            }
            for config in system_configs
        }

        # Get agent settings (using agent_settings_service to include defaults)
        agent_settings_data = {}
        async with db_manager.session() as session:
            from backend.services.agent_settings_service import agent_settings_service
            all_settings = await agent_settings_service.get_all_settings(session)

            # Export type-level settings
            for agent_type, settings in all_settings.get("type_settings", {}).items():
                key = f"type:{agent_type}"
                agent_settings_data[key] = {
                    "system_prompt": settings.get("system_prompt", ""),
                    "provider_name": settings.get("provider_name"),
                    "model_name": settings.get("model_name"),
                    "max_context_tokens": settings.get("max_context_tokens"),
                }

            # Export instance-level settings
            for agent_id, settings in all_settings.get("instance_settings", {}).items():
                key = f"agent:{agent_id}"
                agent_settings_data[key] = {
                    "system_prompt": settings.get("system_prompt", ""),
                    "provider_name": settings.get("provider_name"),
                    "model_name": settings.get("model_name"),
                    "max_context_tokens": settings.get("max_context_tokens"),
                }

        # Get model config
        model_config_data = {}
        async with db_manager.session() as session:
            from backend.models.model_config import ModelConfig
            result = await session.execute(
                select(ModelConfig).where(ModelConfig.config_type == "default")
            )
            model_config = result.scalar_one_or_none()
            if model_config:
                model_config_data = {
                    "default_provider": model_config.default_provider,
                    "providers": model_config.providers,
                }

        # Get config profiles (non-default ones)
        profiles_data = []
        async with db_manager.session() as session:
            result = await session.execute(
                select(ConfigProfile).where(ConfigProfile.is_default == False)
            )
            profiles = result.scalars().all()
            for profile in profiles:
                profiles_data.append({
                    "name": profile.name,
                    "description": profile.description,
                    "config_data": profile.config_data,
                })

        # Get resident agents for export
        resident_agents_data = {}
        async with db_manager.session() as session:
            from backend.models.agent import Agent, AgentType
            result = await session.execute(
                select(Agent).where(Agent.agent_type == AgentType.RESIDENT)
            )
            for agent in result.scalars().all():
                resident_agents_data[agent.id] = {
                    "name": agent.name,
                    "personality": agent.personality,
                }

        return {
            "version": "2.1",
            "exported_at": datetime.utcnow().isoformat(),
            "unlimited_value": self.UNLIMITED_VALUE,
            "system_configs": configs_dict,
            "agent_settings": agent_settings_data,
            "model_config": model_config_data,
            "profiles": profiles_data,
            "resident_agents": resident_agents_data,
        }

    async def export_config_json(self) -> str:
        """Export all configurations as JSON string.

        Returns:
            JSON string of all configurations.
        """
        data = await self.export_config()
        return json.dumps(data, indent=2, ensure_ascii=False)

    async def import_config(self, data: dict[str, Any], merge: bool = True) -> dict[str, Any]:
        """Import configurations from a dictionary.

        Args:
            data: Configuration data dictionary.
            merge: If True, merge with existing; if False, replace all.

        Returns:
            Import result summary.
        """
        if "configs" not in data and "system_configs" not in data:
            raise ValueError("Invalid config format: missing config data")

        result = {
            "system_configs": {"imported": 0, "skipped": 0, "errors": []},
            "agent_settings": {"imported": 0, "skipped": 0, "errors": []},
            "model_config": {"imported": False, "error": None},
            "profiles": {"imported": 0, "errors": []},
            "resident_agents": {"imported": 0, "skipped": 0, "errors": []},
        }

        # Import system configs (support both old and new format)
        configs_data = data.get("system_configs", data.get("configs", {}))
        if configs_data:
            if not merge:
                await self.reset_to_defaults()

            for key, config in configs_data.items():
                if key not in DEFAULT_CONFIGS:
                    result["system_configs"]["skipped"] += 1
                    continue

                try:
                    value = config.get("value", config) if isinstance(config, dict) else config
                    await self.set(key, str(value))
                    result["system_configs"]["imported"] += 1
                except Exception as e:
                    result["system_configs"]["errors"].append(f"{key}: {str(e)}")

        # Import agent settings (version 2.0 format)
        agent_settings_data = data.get("agent_settings", {})
        if agent_settings_data:
            async with db_manager.session() as session:
                from backend.models.agent_settings import AgentSettings
                from backend.models.agent import AgentType

                for key, settings in agent_settings_data.items():
                    try:
                        if key.startswith("type:"):
                            agent_type_str = key[5:]
                            try:
                                agent_type = AgentType(agent_type_str)
                            except ValueError:
                                result["agent_settings"]["skipped"] += 1
                                continue

                            # Find existing or create new
                            existing = await session.execute(
                                select(AgentSettings).where(AgentSettings.agent_type == agent_type)
                            )
                            setting = existing.scalar_one_or_none()

                            if setting:
                                setting.system_prompt = settings.get("system_prompt", setting.system_prompt)
                                setting.provider_name = settings.get("provider_name")
                                setting.model_name = settings.get("model_name")
                                setting.max_context_tokens = settings.get("max_context_tokens")
                                setting.updated_at = datetime.utcnow()
                            else:
                                setting = AgentSettings(
                                    id=str(uuid.uuid4()),
                                    agent_type=agent_type,
                                    system_prompt=settings.get("system_prompt", ""),
                                    provider_name=settings.get("provider_name"),
                                    model_name=settings.get("model_name"),
                                    max_context_tokens=settings.get("max_context_tokens"),
                                    created_at=datetime.utcnow(),
                                    updated_at=datetime.utcnow(),
                                )
                                session.add(setting)
                            result["agent_settings"]["imported"] += 1

                        elif key.startswith("agent:"):
                            agent_id = key[6:]
                            # Verify agent exists
                            from backend.models.agent import Agent
                            agent_result = await session.execute(
                                select(Agent).where(Agent.id == agent_id)
                            )
                            if not agent_result.scalar_one_or_none():
                                result["agent_settings"]["skipped"] += 1
                                continue

                            existing = await session.execute(
                                select(AgentSettings).where(AgentSettings.agent_id == agent_id)
                            )
                            setting = existing.scalar_one_or_none()

                            if setting:
                                setting.system_prompt = settings.get("system_prompt", setting.system_prompt)
                                setting.provider_name = settings.get("provider_name")
                                setting.model_name = settings.get("model_name")
                                setting.max_context_tokens = settings.get("max_context_tokens")
                                setting.updated_at = datetime.utcnow()
                            else:
                                setting = AgentSettings(
                                    id=str(uuid.uuid4()),
                                    agent_id=agent_id,
                                    system_prompt=settings.get("system_prompt", ""),
                                    provider_name=settings.get("provider_name"),
                                    model_name=settings.get("model_name"),
                                    max_context_tokens=settings.get("max_context_tokens"),
                                    created_at=datetime.utcnow(),
                                    updated_at=datetime.utcnow(),
                                )
                                session.add(setting)
                            result["agent_settings"]["imported"] += 1

                    except Exception as e:
                        result["agent_settings"]["errors"].append(f"{key}: {str(e)}")

                await session.commit()

        # Import resident agents (version 2.1 format)
        resident_agents_data = data.get("resident_agents", {})
        if resident_agents_data:
            async with db_manager.session() as session:
                from backend.models.agent import Agent

                for agent_id, agent_data in resident_agents_data.items():
                    try:
                        existing = await session.execute(
                            select(Agent).where(Agent.id == agent_id)
                        )
                        agent = existing.scalar_one_or_none()
                        if agent:
                            if "name" in agent_data:
                                agent.name = agent_data["name"]
                            if "personality" in agent_data:
                                agent.personality = agent_data["personality"]
                            agent.updated_at = datetime.utcnow()
                            result["resident_agents"]["imported"] += 1
                        else:
                            result["resident_agents"]["skipped"] += 1
                    except Exception as e:
                        result["resident_agents"]["errors"].append(f"{agent_id}: {str(e)}")

                await session.commit()

        # Import model config
        model_config_data = data.get("model_config", {})
        if model_config_data:
            try:
                async with db_manager.session() as session:
                    from backend.models.model_config import ModelConfig
                    existing = await session.execute(
                        select(ModelConfig).where(ModelConfig.config_type == "default")
                    )
                    config = existing.scalar_one_or_none()

                    if config:
                        if "default_provider" in model_config_data:
                            config.default_provider = model_config_data["default_provider"]
                        if "providers" in model_config_data:
                            config.providers = model_config_data["providers"]
                        config.updated_at = datetime.utcnow()
                    else:
                        config = ModelConfig(
                            id=str(uuid.uuid4()),
                            config_type="default",
                            default_provider=model_config_data.get("default_provider", "openai"),
                            providers=model_config_data.get("providers", []),
                            created_at=datetime.utcnow(),
                            updated_at=datetime.utcnow(),
                        )
                        session.add(config)
                    await session.commit()
                    result["model_config"]["imported"] = True
            except Exception as e:
                result["model_config"]["error"] = str(e)

        # Import profiles (non-default)
        profiles_data = data.get("profiles", [])
        if profiles_data:
            async with db_manager.session() as session:
                for profile_data in profiles_data:
                    try:
                        name = profile_data.get("name")
                        if not name:
                            continue

                        # Check if profile exists
                        existing = await session.execute(
                            select(ConfigProfile).where(ConfigProfile.name == name)
                        )
                        profile = existing.scalar_one_or_none()

                        if profile:
                            profile.description = profile_data.get("description", profile.description)
                            profile.config_data = profile_data.get("config_data", profile.config_data)
                            profile.updated_at = datetime.utcnow()
                        else:
                            profile = ConfigProfile(
                                id=str(uuid.uuid4()),
                                name=name,
                                description=profile_data.get("description", ""),
                                config_data=profile_data.get("config_data", {}),
                                is_default=False,
                            )
                            session.add(profile)
                        result["profiles"]["imported"] += 1
                    except Exception as e:
                        result["profiles"]["errors"].append(f"{profile_data.get('name', 'unknown')}: {str(e)}")

                await session.commit()

        return result

    async def reset_to_defaults(self) -> None:
        """Reset all configurations to default values."""
        async with db_manager.session() as session:
            for key, config in DEFAULT_CONFIGS.items():
                await self._set_in_session(session, key, config["value"])
            await session.commit()

        await self._refresh_cache()
        logger.info("All configs reset to defaults")

    # ==================== Profile Management ====================

    async def get_profiles(self) -> list[dict[str, Any]]:
        """Get all configuration profiles.

        Returns:
            List of profile dictionaries.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(ConfigProfile).order_by(ConfigProfile.is_default.desc(), ConfigProfile.name)
            )
            profiles = result.scalars().all()

            return [
                {
                    "id": profile.id,
                    "name": profile.name,
                    "description": profile.description,
                    "is_default": profile.is_default,
                    "created_at": profile.created_at.isoformat(),
                    "updated_at": profile.updated_at.isoformat(),
                }
                for profile in profiles
            ]

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Get a specific profile.

        Args:
            profile_id: Profile ID or name.

        Returns:
            Profile dictionary or None if not found.
        """
        async with db_manager.session() as session:
            # Try by ID first, then by name
            result = await session.execute(
                select(ConfigProfile).where(ConfigProfile.id == profile_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                result = await session.execute(
                    select(ConfigProfile).where(ConfigProfile.name == profile_id)
                )
                profile = result.scalar_one_or_none()

            if not profile:
                return None

            return {
                "id": profile.id,
                "name": profile.name,
                "description": profile.description,
                "config_data": profile.config_data,
                "is_default": profile.is_default,
                "created_at": profile.created_at.isoformat(),
                "updated_at": profile.updated_at.isoformat(),
            }

    async def create_profile(
        self,
        name: str,
        description: str | None = None,
        config_data: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Create a new configuration profile.

        Args:
            name: Profile name.
            description: Profile description.
            config_data: Configuration data (current configs if not provided).

        Returns:
            Created profile.
        """
        if config_data is None:
            # Use current configuration
            configs = await self.get_all()
            config_data = {config["key"]: config["value"] for config in configs}

        async with db_manager.session() as session:
            profile = ConfigProfile(
                id=str(uuid.uuid4()),
                name=name,
                description=description,
                config_data=config_data,
                is_default=False,
            )
            session.add(profile)
            await session.commit()

            logger.info(f"Created config profile: {name}")
            return await self.get_profile(profile.id)

    async def update_profile(
        self,
        profile_id: str,
        name: str | None = None,
        description: str | None = None,
        config_data: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Update a configuration profile.

        Args:
            profile_id: Profile ID.
            name: New name.
            description: New description.
            config_data: New config data.

        Returns:
            Updated profile or None if not found.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(ConfigProfile).where(ConfigProfile.id == profile_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                return None

            if name:
                profile.name = name
            if description is not None:
                profile.description = description
            if config_data:
                profile.config_data = config_data
            profile.updated_at = datetime.utcnow()

            await session.commit()
            logger.info(f"Updated config profile: {profile.name}")
            return await self.get_profile(profile.id)

    async def delete_profile(self, profile_id: str) -> bool:
        """Delete a configuration profile.

        Args:
            profile_id: Profile ID.

        Returns:
            True if deleted, False if not found or is default.
        """
        async with db_manager.session() as session:
            result = await session.execute(
                select(ConfigProfile).where(ConfigProfile.id == profile_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                return False

            if profile.is_default:
                logger.warning(f"Cannot delete default profile: {profile.name}")
                return False

            await session.execute(
                delete(ConfigProfile).where(ConfigProfile.id == profile_id)
            )
            await session.commit()
            logger.info(f"Deleted config profile: {profile.name}")
            return True

    async def load_profile(self, profile_id: str) -> dict[str, Any]:
        """Load a configuration profile and apply it.

        Args:
            profile_id: Profile ID or name.

        Returns:
            Load result summary.
        """
        profile = await self.get_profile(profile_id)
        if not profile:
            raise ValueError(f"Profile not found: {profile_id}")

        config_data = profile["config_data"]
        applied = 0
        skipped = 0

        for key, value in config_data.items():
            if key in DEFAULT_CONFIGS:
                await self.set(key, str(value))
                applied += 1
            else:
                skipped += 1

        self._current_profile = profile["name"]
        logger.info(f"Loaded config profile: {profile['name']} ({applied} configs applied)")

        return {
            "profile_name": profile["name"],
            "applied": applied,
            "skipped": skipped,
        }

    async def save_current_to_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Save current configuration to an existing profile.

        Args:
            profile_id: Profile ID.

        Returns:
            Updated profile or None if not found.
        """
        configs = await self.get_all()
        config_data = {config["key"]: config["value"] for config in configs}
        return await self.update_profile(profile_id, config_data=config_data)

    def get_cached(self, key: str, default: Any = None) -> Any:
        """Get a configuration value from cache only (synchronous).

        Falls back to default if cache is not initialized or key not found.

        Args:
            key: Configuration key.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        return self._cache.get(key, default)

    def get_metadata(self) -> dict[str, dict[str, Any]]:
        """Get configuration metadata.

        Returns:
            Dictionary of config metadata.
        """
        return CONFIG_METADATA.copy()

    def get_categories(self) -> dict[str, list[str]]:
        """Get configuration keys grouped by category.

        Returns:
            Dictionary of category -> list of config keys.
        """
        categories: dict[str, list[str]] = {}
        for key, meta in CONFIG_METADATA.items():
            category = meta.get("category", "other")
            if category not in categories:
                categories[category] = []
            categories[category].append(key)
        return categories


# Global config service instance
config_service = ConfigService()
