#!/usr/bin/env python3
"""
LongClaw 数据库初始化脚本 (backend 版本)

用法:
    cd /path/to/longclaw/backend
    python3 scripts/init_db.py [--force]

或:
    cd /path/to/longclaw/backend
    python3 -m scripts.init_db [--force]

注意: 推荐使用项目根目录下的 scripts/init_db.py
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import delete, text

from backend.database import db_manager
from backend.models import (
    Agent,
    Channel,
    Conversation,
    Message,
    Subtask,
    Task,
)
from backend.models.agent import AgentType
from backend.models.channel import ChannelType
from backend.services.agent_service import agent_service
from backend.services.channel_service import channel_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==================== 配置默认值 ====================

DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "resident_chat_timeout": {"value": "600", "description": "Resident Agent 聊天回复超时（秒），-1 表示无限制"},
    "owner_task_timeout": {"value": "600", "description": "Owner Agent 任务执行总超时（秒），-1 表示无限制"},
    "worker_subtask_timeout": {"value": "180", "description": "Worker/SubAgent 单个子任务超时（秒），-1 表示无限制"},
    "llm_request_timeout": {"value": "300", "description": "LLM API 请求超时（秒），-1 表示无限制"},
    "llm_connect_timeout": {"value": "30", "description": "LLM API 连接超时（秒），-1 表示无限制"},
    "tool_http_timeout": {"value": "30", "description": "Tool HTTP 请求超时（秒），-1 表示无限制"},
    "tool_connect_timeout": {"value": "10", "description": "Tool HTTP 连接超时（秒），-1 表示无限制"},
    "tool_max_rounds": {"value": "6", "description": "单次任务最大工具调用轮数，-1 表示无限制"},
    "scheduler_agent_timeout": {"value": "300", "description": "Scheduler Agent 不活跃判定阈值（秒），-1 表示禁用检查"},
    "scheduler_check_interval": {"value": "10", "description": "Scheduler 检查间隔（秒）"},
    "command_blacklist": {
        "value": "rm -rf,mkfs,shutdown,reboot,halt,poweroff,init 0,init 6,dd if=,> /dev/sd,chmod -R 777 /,chown -R,chgrp -R,killall,kill -9 -1,crontab,useradd,userdel,passwd,visudo,iptables,ufw,firewall-cmd,systemctl stop,systemctl disable,systemctl restart,docker rm,docker rmi,docker system prune,kubectl delete,kubectl drain,kubectl scale",
        "description": "禁止执行的命令黑名单（逗号分隔）",
    },
    "command_timeout": {"value": "60", "description": "命令执行超时时间（秒），-1 表示无限制"},
    "memory_token_limit": {"value": "4000", "description": "单个会话的 token 上限，-1 表示无限制"},
    "memory_keep_recent": {"value": "5", "description": "压缩时保留的最近消息数"},
    "memory_compact_threshold": {"value": "0.8", "description": "触发压缩的比例阈值（0.8 表示 80%）"},
    "memory_search_limit": {"value": "5", "description": "记忆搜索返回的最大结果数，-1 表示无限制"},
    "reflect_check_interval": {"value": "30", "description": "Reflect Agent 检查间隔（秒）"},
    "reflect_stuck_threshold": {"value": "120", "description": "Agent 被判定为停滞的时间阈值（秒），-1 表示禁用检查"},
    "agent_max_context_tokens": {"value": "8192", "description": "所有Agent的总上下文 token 上限，-1 表示无限制"},
    "context_compact_threshold": {"value": "0.8", "description": "达到上限的比例时触发压缩（0.8 表示 80%）"},
    "owner_confirm_dependencies": {"value": "true", "description": "启用OwnerAgent两阶段依赖确认（推荐开启）"},
    "force_complex_task": {"value": "false", "description": "强制所有任务走OwnerAgent复杂任务流程（用于测试）"},
}

# ==================== 预设配置方案 ====================

PRESET_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "description": "默认配置，平衡性能与安全",
        "is_default": True,
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
            "force_complex_task": "false",
        },
    },
    "high_performance": {
        "description": "高性能模式，更高的超时和上限，适合复杂任务",
        "is_default": False,
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
            "force_complex_task": "false",
        },
    },
    "unlimited": {
        "description": "无限制模式，禁用所有超时和上限限制",
        "is_default": False,
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
            "force_complex_task": "false",
        },
    },
    "safe_mode": {
        "description": "安全模式，较低的超时和限制，适合生产环境",
        "is_default": False,
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
            "force_complex_task": "false",
        },
    },
    "debug": {
        "description": "调试模式，详细的日志和较短的超时，适合开发测试",
        "is_default": False,
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
        },
    },
}


async def clear_all_tables() -> None:
    """Clear all data from tables in correct order (respecting foreign keys)."""
    async with db_manager.session() as session:
        # 按照外键依赖顺序清空表 (先清空有外键依赖的子表)
        tables = [
            "messages",
            "subtasks",
            "tasks",
            "conversations",
            "knowledge",
            "agent_settings",
            "agent_prompts",
            "agents",
            "channels",
            "config_profiles",
            "system_config",
        ]

        logger.info("Step 1: 清空所有数据表...")

        for table in tables:
            try:
                await session.execute(text(f"TRUNCATE TABLE {table}"))
                logger.info(f"  ✓ 已清空: {table}")
            except Exception:
                try:
                    await session.execute(text(f"DELETE FROM {table}"))
                    logger.info(f"  ✓ 已清空: {table} (DELETE)")
                except Exception as e:
                    logger.warning(f"  - 跳过: {table} ({e})")

        logger.info("  所有表已清空")


async def init_system_config() -> None:
    """Initialize system configuration."""
    from backend.models.system_config import SystemConfig
    from sqlalchemy import select

    logger.info("Step 2: 初始化系统配置...")

    async with db_manager.session() as session:
        created_count = 0
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
                created_count += 1
                logger.info(f"  ✓ 创建配置: {key} = {config['value']}")

        await session.commit()
        logger.info(f"  已创建 {created_count} 个配置项")


async def init_config_profiles() -> None:
    """Initialize preset configuration profiles."""
    import uuid
    from backend.models.config_profile import ConfigProfile
    from sqlalchemy import select

    logger.info("Step 3: 初始化配置方案...")

    async with db_manager.session() as session:
        created_count = 0
        for profile_name, profile_data in PRESET_PROFILES.items():
            result = await session.execute(
                select(ConfigProfile).where(ConfigProfile.name == profile_name)
            )
            existing = result.scalar_one_or_none()

            if not existing:
                new_profile = ConfigProfile(
                    id=str(uuid.uuid4()),
                    name=profile_name,
                    description=profile_data["description"],
                    config_data=profile_data["configs"],
                    is_default=profile_data.get("is_default", False),
                )
                session.add(new_profile)
                created_count += 1
                logger.info(f"  ✓ 创建方案: {profile_name}")

        await session.commit()
        logger.info(f"  已创建 {created_count} 个配置方案")


async def create_resident_agent() -> str:
    """Create a new resident agent."""
    logger.info("Step 4: 创建 Resident Agent...")

    async with db_manager.session() as session:
        agent = await agent_service.create_agent(
            session,
            agent_type=AgentType.RESIDENT,
            name="老六",
            personality="靠谱、友好、有点皮的AI助手。擅长处理各种任务，能够调用工具搜索信息、执行代码等。",
        )
        logger.info(f"  ✓ 已创建 Agent: {agent.name} (ID: {agent.id})")
        return agent.id


async def create_web_channel(resident_agent_id: str) -> str:
    """Create a default web channel bound to the resident agent."""
    logger.info("Step 5: 创建 Web Channel...")

    async with db_manager.session() as session:
        channel = await channel_service.create_channel(
            session,
            channel_type=ChannelType.WEB,
            resident_agent_id=resident_agent_id,
        )
        logger.info(f"  ✓ 已创建 Channel (ID: {channel.id})")
        logger.info(f"  ✓ 已绑定 Agent: {resident_agent_id}")
        return channel.id


async def verify_initialization() -> dict[str, Any]:
    """Verify initialization results."""
    from sqlalchemy import func, select

    from backend.models.config_profile import ConfigProfile
    from backend.models.system_config import SystemConfig

    logger.info("Step 6: 验证初始化结果...")

    results = {}

    async with db_manager.session() as session:
        # Check Resident Agent
        agent_result = await session.execute(
            select(func.count(Agent.id)).where(Agent.agent_type == AgentType.RESIDENT)
        )
        results["resident_agent_count"] = agent_result.scalar_one()
        logger.info(f"  Resident Agents: {results['resident_agent_count']}")

        # Check Web Channel
        channel_result = await session.execute(
            select(func.count(Channel.id)).where(
                Channel.channel_type == ChannelType.WEB,
                Channel.is_active == True,
            )
        )
        results["web_channel_count"] = channel_result.scalar_one()
        logger.info(f"  Active Web Channels: {results['web_channel_count']}")

        # Check configs
        config_result = await session.execute(select(func.count(SystemConfig.config_key)))
        results["config_count"] = config_result.scalar_one()
        logger.info(f"  System Configs: {results['config_count']}")

        # Check config profiles
        profile_result = await session.execute(select(func.count(ConfigProfile.id)))
        results["profile_count"] = profile_result.scalar_one()
        logger.info(f"  Config Profiles: {results['profile_count']}")

        # Get binding info
        binding_result = await session.execute(
            select(Channel.id, Channel.resident_agent_id, Agent.name)
            .select_from(Channel)
            .join(Agent, Channel.resident_agent_id == Agent.id)
            .where(Channel.channel_type == ChannelType.WEB, Channel.is_active == True)
        )
        bindings = binding_result.all()

        if bindings:
            for channel_id, agent_id, agent_name in bindings:
                logger.info(f"  绑定关系: Channel {channel_id} -> Agent {agent_name} ({agent_id})")
                results["channel_id"] = channel_id
                results["agent_id"] = agent_id
                results["agent_name"] = agent_name

        # Get agent info
        agent_query = await session.execute(
            select(Agent.id, Agent.name).where(Agent.agent_type == AgentType.RESIDENT).limit(1)
        )
        agent_row = agent_query.first()
        if agent_row:
            results["agent_id"] = agent_row[0]
            results["agent_name"] = agent_row[1]

        results["success"] = (
            results["resident_agent_count"] >= 1
            and results["web_channel_count"] >= 1
        )

    return results


async def init_database(force: bool = False) -> dict:
    """Initialize the database."""
    if not force:
        print()
        print("=" * 60)
        print("       LongClaw 数据库初始化脚本")
        print("=" * 60)
        print()
        print("此脚本将执行以下操作:")
        print("  1. 清空所有数据表")
        print("  2. 初始化系统配置")
        print("  3. 初始化预设配置方案")
        print("  4. 创建 Resident Agent (老六)")
        print("  5. 创建 Web Channel 并绑定 Agent")
        print()
        print("⚠️  警告: 所有现有数据将被永久删除!")
        print()

        try:
            response = input("确认继续? (yes/no): ").strip().lower()
            if response not in ("yes", "y"):
                print("已取消。")
                return {"success": False}
        except KeyboardInterrupt:
            print("\n已取消。")
            return {"success": False}

    print()
    logger.info("初始化数据库连接...")
    await db_manager.init()

    try:
        # Step 1: Clear tables
        await clear_all_tables()

        # Step 2: Init config
        await init_system_config()

        # Step 3: Init config profiles
        await init_config_profiles()

        # Step 4: Create agent
        agent_id = await create_resident_agent()

        # Step 5: Create channel
        channel_id = await create_web_channel(agent_id)

        # Step 6: Verify
        results = await verify_initialization()

        if results["success"]:
            print()
            print("=" * 60)
            print("✓ 初始化完成!")
            print("=" * 60)
            print()
            print("初始化结果:")
            print(f"  - Resident Agent ID: {results.get('agent_id', 'N/A')}")
            print(f"  - Agent Name: {results.get('agent_name', 'N/A')}")
            print(f"  - Web Channel ID: {results.get('channel_id', 'N/A')}")
            print(f"  - 系统配置项: {results.get('config_count', 0)}")
            print(f"  - 预设配置方案: {results.get('profile_count', 0)}")
            print()

        return results

    finally:
        await db_manager.close()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="LongClaw 数据库初始化脚本")
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="跳过确认提示，直接执行初始化",
    )
    return parser.parse_args()


def main() -> None:
    """Main entry point."""
    args = parse_args()
    result = asyncio.run(init_database(force=args.force))
    if not result.get("success", False):
        sys.exit(1)


if __name__ == "__main__":
    main()
