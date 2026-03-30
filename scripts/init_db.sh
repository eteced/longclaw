#!/bin/bash
#
# LongClaw 数据库初始化脚本 (Shell 版本)
#
# 用法:
#   ./scripts/init_db.sh [--force]
#
# 注意: 推荐使用更完整的 Python 版本:
#   PYTHONPATH=. python3 scripts/init_db.py [--force]
#
# 此脚本执行以下操作:
# 1. 清空所有数据表
# 2. 初始化系统配置
# 3. 创建默认 Web Channel
# 4. 创建 Resident Agent 并绑定到 Channel
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
FORCE=false
for arg in "$@"; do
    case $arg in
        --force|-f)
            FORCE=true
            shift
            ;;
    esac
done

# Database connection settings (can be overridden by environment variables)
DB_USER="${DB_USER:-longclaw}"
DB_PASS="${DB_PASS:-longclaw123}"
DB_NAME="${DB_NAME:-longclaw}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"

# MySQL command
MYSQL_CMD="mysql -u${DB_USER} -p${DB_PASS} -h${DB_HOST} -P${DB_PORT} ${DB_NAME}"

echo -e "${YELLOW}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${YELLOW}║       LongClaw 数据库初始化脚本 (Shell 版本)             ║${NC}"
echo -e "${YELLOW}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# Confirmation
if [ "$FORCE" = false ]; then
    echo "此脚本将执行以下操作:"
    echo "  1. 清空所有数据表"
    echo "  2. 初始化系统配置"
    echo "  3. 创建 Resident Agent (老六)"
    echo "  4. 创建 Web Channel 并绑定 Agent"
    echo ""
    echo -e "${RED}⚠️  警告: 所有现有数据将被永久删除!${NC}"
    echo ""
    read -p "确认继续? (yes/no): " confirm
    if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
        echo "已取消。"
        exit 0
    fi
fi

echo ""
echo -e "${YELLOW}Step 1: 清空所有数据表...${NC}"

# 按照外键依赖顺序清空表 (先清空有外键依赖的子表)
TABLES_TO_CLEAR=(
    "messages"
    "subtasks"
    "tasks"
    "conversations"
    "knowledge"
    "agent_prompts"
    "agent_settings"
    "agents"
    "channels"
    "config_profiles"
    "system_config"
)

for table in "${TABLES_TO_CLEAR[@]}"; do
    echo -n "  清空表 ${table}... "
    RESULT=$($MYSQL_CMD -e "TRUNCATE TABLE ${table};" 2>&1)
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC}"
    else
        # Table might not exist, try DELETE instead
        RESULT=$($MYSQL_CMD -e "DELETE FROM ${table};" 2>&1)
        if [ $? -eq 0 ]; then
            echo -e "${GREEN}✓ (DELETE)${NC}"
        else
            echo -e "${YELLOW}- 跳过${NC}"
        fi
    fi
done

echo ""
echo -e "${YELLOW}Step 2: 初始化系统配置...${NC}"

NOW=$(date -u +"%Y-%m-%d %H:%M:%S")

# 插入默认系统配置
declare -A CONFIGS
CONFIGS["resident_chat_timeout"]="600|Resident Agent 聊天回复超时（秒）"
CONFIGS["owner_task_timeout"]="600|Owner Agent 任务执行总超时（秒）"
CONFIGS["worker_subtask_timeout"]="300|Worker/SubAgent 单个子任务超时（秒）"
CONFIGS["llm_request_timeout"]="300|LLM API 请求超时（秒）"
CONFIGS["scheduler_check_interval"]="10|Scheduler 检查间隔（秒）"
CONFIGS["tool_max_rounds"]="6|单次任务最大工具调用轮数"

config_count=0
for key in "${!CONFIGS[@]}"; do
    IFS='|' read -r value desc <<< "${CONFIGS[$key]}"
    echo -n "  创建配置 ${key}... "
    $MYSQL_CMD -e "
    INSERT INTO system_config (config_key, config_value, description, updated_at)
    VALUES ('${key}', '${value}', '${desc}', '${NOW}')
    ON DUPLICATE KEY UPDATE config_value='${value}', updated_at='${NOW}';
    " > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓${NC}"
        ((config_count++))
    fi
done

echo "  已创建 ${config_count} 个配置项"

echo ""
echo -e "${YELLOW}Step 3: 创建 Resident Agent...${NC}"

# Generate UUID for resident agent
RESIDENT_AGENT_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

echo -n "  创建 Agent: 老六 (${RESIDENT_AGENT_ID})... "
$MYSQL_CMD -e "
INSERT INTO agents (id, agent_type, name, personality, status, created_at, updated_at)
VALUES ('${RESIDENT_AGENT_ID}', 'resident', '老六', '靠谱、友好、有点皮的AI助手', 'idle', '${NOW}', '${NOW}');
" 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}失败${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 4: 创建 Web Channel...${NC}"

# Generate UUID for channel
CHANNEL_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')

echo -n "  创建 Channel (${CHANNEL_ID})... "
$MYSQL_CMD -e "
INSERT INTO channels (id, channel_type, resident_agent_id, is_active, created_at)
VALUES ('${CHANNEL_ID}', 'web', '${RESIDENT_AGENT_ID}', 1, '${NOW}');
" 2>&1

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓${NC}"
    echo "  已绑定 Agent: ${RESIDENT_AGENT_ID}"
else
    echo -e "${RED}失败${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 5: 验证初始化结果...${NC}"

# Check agents table
AGENT_COUNT=$($MYSQL_CMD -N -e "SELECT COUNT(*) FROM agents WHERE agent_type = 'resident';")
echo "  Resident Agents: ${AGENT_COUNT}"

# Check channels table
CHANNEL_COUNT=$($MYSQL_CMD -N -e "SELECT COUNT(*) FROM channels WHERE channel_type = 'web' AND is_active = 1;")
echo "  Active Web Channels: ${CHANNEL_COUNT}"

# Check configs
CONFIG_COUNT=$($MYSQL_CMD -N -e "SELECT COUNT(*) FROM system_config;" 2>/dev/null || echo "0")
echo "  System Configs: ${CONFIG_COUNT}"

if [ "${AGENT_COUNT}" -ge 1 ] && [ "${CHANNEL_COUNT}" -ge 1 ]; then
    echo ""
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}✓ 初始化完成!${NC}"
    echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
else
    echo ""
    echo -e "${RED}初始化失败!${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Step 6: 检查后端服务...${NC}"

HEALTH_URL="http://localhost:8001/health"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${HEALTH_URL}" 2>/dev/null || echo "000")

if [ "${HTTP_CODE}" = "200" ]; then
    echo -e "  后端服务: ${GREEN}运行正常 (http://localhost:8001)${NC}"
elif [ "${HTTP_CODE}" = "000" ]; then
    echo -e "  后端服务: ${YELLOW}未运行${NC}"
    echo "  启动命令: python -m backend.main"
else
    echo -e "  后端服务: ${YELLOW}响应异常 (HTTP ${HTTP_CODE})${NC}"
fi

echo ""
echo "初始化结果:"
echo "  - Resident Agent ID: ${RESIDENT_AGENT_ID}"
echo "  - Agent Name: 老六"
echo "  - Web Channel ID: ${CHANNEL_ID}"
echo "  - 系统配置项: ${CONFIG_COUNT}"
echo ""
echo "下一步:"
echo "  1. 启动后端服务: python -m backend.main"
echo "  2. 启动前端服务: cd frontend && npm run dev"
echo "  3. 访问 http://localhost:5173 开始使用"
echo ""
