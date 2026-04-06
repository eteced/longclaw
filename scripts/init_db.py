#!/usr/bin/env python3
"""
LongClaw 数据库初始化脚本

用于在清空数据库后执行必要的初始化操作。

用法:
    # 方式1: 从项目根目录执行
    cd /path/to/longclaw
    PYTHONPATH=. python3 scripts/init_db.py [--force]

    # 方式2: 直接执行
    python3 scripts/init_db.py --force

参数:
    --force    跳过确认提示，直接执行初始化

初始化步骤:
    1. 清空所有数据表
    2. 初始化系统配置
    3. 初始化预设配置方案
    4. 创建 Resident Agent (默认名称: 老六)
    5. 创建 Web Channel 并绑定 Agent
    6. 验证初始化结果
"""

import argparse
import asyncio
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

# Setup path to import backend modules
script_dir = Path(__file__).parent
project_root = script_dir.parent
backend_dir = project_root / "backend"

# Add project root to sys.path for imports
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==================== 配置默认值 ====================

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
        "description": "触发压缩的 token 阈值比例",
    },
    "memory_search_limit": {
        "value": "5",
        "description": "记忆搜索返回的最大结果数，-1 表示无限制",
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
    "resident_agent_max_context": {
        "value": "8192",
        "description": "ResidentAgent 上下文 token 上限，-1 表示无限制",
    },
    "owner_agent_max_context": {
        "value": "4096",
        "description": "OwnerAgent 上下文 token 上限，-1 表示无限制",
    },
    "worker_agent_max_context": {
        "value": "2048",
        "description": "WorkerAgent 上下文 token 上限，-1 表示无限制",
    },
    "context_compact_threshold": {
        "value": "0.8",
        "description": "达到上限的此比例时触发 compact",
    },
    "owner_confirm_dependencies": {
        "value": "true",
        "description": "启用OwnerAgent两阶段依赖确认（推荐开启）",
    },
    "force_complex_task": {
        "value": "false",
        "description": "强制所有任务走OwnerAgent复杂任务流程（用于测试）",
    },
    "resident_always_allocate_slot": {
        "value": "true",
        "description": "Resident Agent是否始终占用模型Slot。关闭后，空闲时释放Slot给其他Agent",
    },
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
            "resident_agent_max_context": "8192",
            "owner_agent_max_context": "4096",
            "worker_agent_max_context": "2048",
            "context_compact_threshold": "0.8",
            "owner_confirm_dependencies": "true",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "true",
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
            "resident_agent_max_context": "32768",
            "owner_agent_max_context": "16384",
            "worker_agent_max_context": "8192",
            "context_compact_threshold": "0.9",
            "owner_confirm_dependencies": "true",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "true",
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
            "resident_agent_max_context": "-1",
            "owner_agent_max_context": "-1",
            "worker_agent_max_context": "-1",
            "context_compact_threshold": "0.95",
            "owner_confirm_dependencies": "true",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "true",
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
            "resident_agent_max_context": "4096",
            "owner_agent_max_context": "2048",
            "worker_agent_max_context": "1024",
            "context_compact_threshold": "0.7",
            "owner_confirm_dependencies": "true",
            "force_complex_task": "false",
            "resident_always_allocate_slot": "false",
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
            "resident_agent_max_context": "4096",
            "owner_agent_max_context": "2048",
            "worker_agent_max_context": "1024",
            "context_compact_threshold": "0.6",
            "owner_confirm_dependencies": "false",
            "force_complex_task": "true",
            "resident_always_allocate_slot": "true",
        },
    },
}


# ==================== 初始化函数 ====================

async def clear_tables(session) -> None:
    """清空所有数据表。

    清空顺序考虑外键约束:
    messages -> subtasks -> tasks -> agents -> channels -> conversations -> knowledge -> agent_prompts -> agent_settings -> config_profiles -> system_config
    """
    from sqlalchemy import text

    # 首先禁用外键检查（必须先做，否则 TRUNCATE 会失败）
    try:
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        logger.info("  已禁用外键检查")
    except Exception:
        pass

    # 按照外键依赖顺序清空表 (先清空有外键依赖的子表)
    # 顺序原则：先清子表，再清父表
    tables = [
        # messages 无强依赖，先清
        "messages",
        # subtasks 依赖 tasks 和 agents
        "subtasks",
        # model_slots 依赖多个表
        "model_slots",
        # conversations 依赖 channels 和 agents
        "conversations",
        # tasks 依赖 agents (必须在 agents 之前清)
        "tasks",
        # knowledge 依赖 agents
        "knowledge",
        # agent_prompts 和 agent_settings 依赖 agents
        "agent_prompts",
        "agent_settings",
        # agents 必须在 tasks 之后清
        "agents",
        # channels 依赖 agents
        "channels",
        # config_profiles 和 system_config 无外键依赖，最后清
        "config_profiles",
        "system_config",
    ]

    logger.info("Step 1: 清空所有数据表...")

    for table in tables:
        try:
            # 先尝试 TRUNCATE (更快)
            await session.execute(text(f"TRUNCATE TABLE `{table}`"))
            logger.info(f"  ✓ 已清空: {table} (TRUNCATE)")
        except Exception:
            # TRUNCATE 失败则用 DELETE
            try:
                await session.execute(text(f"DELETE FROM `{table}`"))
                logger.info(f"  ✓ 已清空: {table} (DELETE)")
            except Exception as e:
                # 表可能不存在
                logger.warning(f"  - 跳过: {table} ({e})")

    # 重新启用外键检查
    try:
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        logger.info("  已重新启用外键检查")
    except Exception:
        pass

    await session.commit()
    logger.info("  所有表已清空")


async def run_migrations(session) -> None:
    """运行数据库迁移脚本。

    执行 backend/migrations/*.sql 中的所有迁移。
    """
    from sqlalchemy import text
    import os

    migrations_dir = Path(__file__).parent.parent / "backend" / "migrations"

    if not migrations_dir.exists():
        logger.info("Step 1.5: 未找到迁移目录，跳过迁移")
        return

    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        logger.info("Step 1.5: 未找到迁移文件，跳过迁移")
        return

    logger.info(f"Step 1.5: 运行数据库迁移 ({len(migration_files)} 个文件)...")

    # 确保迁移记录表存在
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL UNIQUE,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    await session.commit()

    # 获取已应用的迁移
    result = await session.execute(text("SELECT name FROM schema_migrations"))
    applied = {row[0] for row in result.fetchall()}

    applied_count = 0
    for migration_file in migration_files:
        migration_name = migration_file.name

        if migration_name in applied:
            logger.info(f"  - 已应用: {migration_name}")
            continue

        migration_content = migration_file.read_text()

        try:
            # 执行迁移
            for statement in migration_content.split(';'):
                statement = statement.strip()
                if statement and not statement.startswith('--'):
                    lines = [l for l in statement.split('\n') if not l.strip().startswith('--')]
                    clean_statement = '\n'.join(lines).strip()
                    if clean_statement:
                        # MySQL 不支持 ADD COLUMN IF NOT EXISTS，需要处理
                        clean_statement = clean_statement.replace('ADD COLUMN IF NOT EXISTS', 'ADD COLUMN')
                        try:
                            await session.execute(text(clean_statement))
                        except Exception as e:
                            # 忽略重复列错误
                            if "1060" not in str(e) and "Duplicate column" not in str(e):
                                raise

            # 标记为已应用
            await session.execute(
                text(f"INSERT IGNORE INTO schema_migrations (name) VALUES ('{migration_name}')")
            )
            await session.commit()
            logger.info(f"  ✓ 已应用: {migration_name}")
            applied_count += 1
        except Exception as e:
            logger.warning(f"  ! 迁移失败 {migration_name}: {e}")
            await session.rollback()

    logger.info(f"  已应用 {applied_count} 个新迁移")


async def init_system_config(session) -> None:
    """初始化系统配置表。"""
    from backend.models.system_config import SystemConfig

    logger.info("Step 2: 初始化系统配置...")

    created_count = 0
    for key, config in DEFAULT_CONFIGS.items():
        # 检查是否已存在
        from sqlalchemy import select
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


async def init_config_profiles(session) -> None:
    """初始化预设配置方案。"""
    from backend.models.config_profile import ConfigProfile

    logger.info("Step 3: 初始化预设配置方案...")

    created_count = 0
    for profile_name, profile_data in PRESET_PROFILES.items():
        from sqlalchemy import select
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


async def create_resident_agent(session) -> str:
    """创建默认的 Resident Agent。

    Returns:
        Agent ID
    """
    from backend.models.agent import AgentType
    from backend.services.agent_service import agent_service

    logger.info("Step 4: 创建 Resident Agent...")

    agent = await agent_service.create_agent(
        session,
        agent_type=AgentType.RESIDENT,
        name="老六",
        personality="靠谱、友好、有点皮的AI助手。擅长处理各种任务，能够调用工具搜索信息、执行代码等。",
    )

    logger.info(f"  ✓ 已创建 Agent: {agent.name} (ID: {agent.id})")
    return agent.id


async def create_web_channel(session, resident_agent_id: str) -> str:
    """创建 Web Channel 并绑定 Resident Agent。

    Args:
        session: 数据库会话
        resident_agent_id: 要绑定的 Agent ID

    Returns:
        Channel ID
    """
    from backend.models.channel import ChannelType
    from backend.services.channel_service import channel_service

    logger.info("Step 5: 创建 Web Channel...")

    channel = await channel_service.create_channel(
        session,
        channel_type=ChannelType.WEB,
        resident_agent_id=resident_agent_id,
    )

    logger.info(f"  ✓ 已创建 Channel (ID: {channel.id})")
    logger.info(f"  ✓ 已绑定 Agent: {resident_agent_id}")
    return channel.id


async def verify_initialization(session) -> dict[str, Any]:
    """验证初始化结果。

    Returns:
        验证结果字典
    """
    from sqlalchemy import func, select

    from backend.models.agent import Agent, AgentType
    from backend.models.channel import Channel, ChannelType
    from backend.models.config_profile import ConfigProfile
    from backend.models.system_config import SystemConfig

    logger.info("Step 6: 验证初始化结果...")

    results = {}

    # 检查 Resident Agent
    agent_result = await session.execute(
        select(func.count(Agent.id)).where(Agent.agent_type == AgentType.RESIDENT)
    )
    results["resident_agent_count"] = agent_result.scalar_one()
    logger.info(f"  Resident Agents: {results['resident_agent_count']}")

    # 检查 Web Channel
    channel_result = await session.execute(
        select(func.count(Channel.id)).where(
            Channel.channel_type == ChannelType.WEB,
            Channel.is_active == True,
        )
    )
    results["web_channel_count"] = channel_result.scalar_one()
    logger.info(f"  Active Web Channels: {results['web_channel_count']}")

    # 检查配置项
    config_result = await session.execute(select(func.count(SystemConfig.config_key)))
    results["config_count"] = config_result.scalar_one()
    logger.info(f"  System Configs: {results['config_count']}")

    # 检查配置方案
    profile_result = await session.execute(select(func.count(ConfigProfile.id)))
    results["profile_count"] = profile_result.scalar_one()
    logger.info(f"  Config Profiles: {results['profile_count']}")

    # 检查绑定关系
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

    # 获取 Agent ID
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


async def health_check() -> bool:
    """检查后端服务是否运行。

    Returns:
        True 如果服务正在运行
    """
    import httpx

    logger.info("Step 7: 检查后端服务...")

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("http://localhost:8001/health")
            if resp.status_code == 200:
                logger.info("  ✓ 后端服务运行正常 (http://localhost:8001)")
                return True
            else:
                logger.warning(f"  ! 后端服务响应异常: HTTP {resp.status_code}")
                return False
    except Exception as e:
        logger.info(f"  - 后端服务未运行或无法连接: {e}")
        logger.info("  提示: 请确保后端服务已启动 (python -m backend.main)")
        return False


async def main(force: bool = False) -> int:
    """主入口函数。

    Args:
        force: 是否跳过确认提示

    Returns:
        退出码 (0=成功, 1=失败)
    """
    from backend.database import db_manager

    print()
    print("=" * 60)
    print("       LongClaw 数据库初始化脚本")
    print("=" * 60)
    print()

    if not force:
        print("此脚本将执行以下操作:")
        print("  1. 清空所有数据表 (messages, tasks, agents, channels 等)")
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
                return 0
        except KeyboardInterrupt:
            print("\n已取消。")
            return 0

    print()

    # 初始化数据库连接
    logger.info("初始化数据库连接...")
    await db_manager.init()

    try:
        async with db_manager.session() as session:
            # Step 1: 清空表
            await clear_tables(session)

            # Step 2: 初始化配置
            await init_system_config(session)

            # Step 3: 初始化配置方案
            await init_config_profiles(session)

            # Step 4: 创建 Agent
            agent_id = await create_resident_agent(session)

            # Step 5: 创建 Channel
            channel_id = await create_web_channel(session, agent_id)

            # 提交所有更改
            await session.commit()

            # Step 6: 验证
            results = await verify_initialization(session)

            if not results["success"]:
                logger.error("初始化验证失败!")
                return 1

        # Step 7: 健康检查
        await health_check()

        # 打印摘要
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
        print("下一步:")
        print("  1. 启动后端服务: python -m backend.main")
        print("  2. 启动前端服务: cd frontend && npm run dev")
        print("  3. 访问 http://localhost:5173 开始使用")
        print()

        return 0

    except Exception as e:
        logger.exception(f"初始化失败: {e}")
        return 1
    finally:
        await db_manager.close()


def parse_args():
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="LongClaw 数据库初始化脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 交互式执行
    python3 scripts/init_db.py

    # 跳过确认直接执行
    python3 scripts/init_db.py --force
        """,
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="跳过确认提示，直接执行初始化",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = asyncio.run(main(force=args.force))
    sys.exit(exit_code)
