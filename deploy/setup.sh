#!/bin/bash
#
# LongClaw 一键安装部署脚本
# ================================
# 此脚本用于在新机器上快速部署 LongClaw
#
# 用法:
#   ./setup.sh [选项]
#
# 选项:
#   --skip-db          跳过数据库初始化
#   --skip-frontend    跳过前端构建
#   --production       生产环境模式
#   --help             显示帮助信息
#

set -e

# ============================================================
# 颜色定义
# ============================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ============================================================
# 配置变量
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
INSTALL_DIR="/opt/longclaw"
DATA_DIR="/var/lib/longclaw"
LOG_DIR="/var/log/longclaw"
LOG_FILE="$LOG_DIR/setup.log"

# 默认配置
SKIP_DB=false
SKIP_FRONTEND=false
PRODUCTION=false
FORCE=false
LLM_PROVIDER="openai"
AUTO_START=true

# 数据库配置
DB_HOST="localhost"
DB_PORT="3306"
DB_NAME="longclaw"
DB_USER="longclaw"
DB_PASS=""

# Redis配置
REDIS_HOST="localhost"
REDIS_PORT="6379"
REDIS_DB="0"

# 服务配置
BACKEND_PORT="8001"
FRONTEND_PORT="5173"
API_KEY=""

# LLM配置
OPENAI_API_KEY=""
OPENAI_BASE_URL="https://api.openai.com/v1"
OPENAI_MODEL="gpt-4o"
DEEPSEEK_API_KEY=""
DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"
DEEPSEEK_MODEL="deepseek-chat"

# ============================================================
# 帮助信息
# ============================================================
show_help() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║         LongClaw 一键安装部署脚本                         ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo "用法:"
    echo -e "  ${GREEN}$0${NC} [选项]"
    echo ""
    echo "选项:"
    echo -e "  ${GREEN}--skip-db${NC}           跳过数据库初始化"
    echo -e "  ${GREEN}--skip-frontend${NC}     跳过前端构建"
    echo -e "  ${GREEN}--production${NC}        生产环境模式"
    echo -e "  ${GREEN}--help${NC}              显示此帮助信息"
    echo ""
    echo "交互式配置项:"
    echo "  - 数据库连接信息"
    echo "  - Redis 连接信息"
    echo "  - API 密钥设置"
    echo "  - LLM 模型配置"
    echo ""
    echo "示例:"
    echo -e "  ${GREEN}$0${NC}                    # 交互式安装"
    echo -e "  ${GREEN}$0 --production${NC}        # 生产环境安装"
    echo -e "  ${GREEN}$0 --skip-db${NC}          # 跳过数据库初始化"
    echo ""
}

# ============================================================
# 日志函数
# ============================================================
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # 确保日志目录存在
    mkdir -p "$(dirname "$LOG_FILE")"

    # 写入日志文件
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE" 2>/dev/null || true

    # 根据级别输出到终端
    case "$level" in
        "INFO")
            echo -e "${GREEN}[$timestamp] [INFO]${NC} $message"
            ;;
        "WARN")
            echo -e "${YELLOW}[$timestamp] [WARN]${NC} $message"
            ;;
        "ERROR")
            echo -e "${RED}[$timestamp] [ERROR]${NC} $message"
            ;;
        *)
            echo "[$timestamp] [$level] $message"
            ;;
    esac
}

# ============================================================
# 检查依赖
# ============================================================
check_dependencies() {
    log "INFO" "检查系统依赖..."

    local missing_deps=()

    # 检查 Python
    if ! command -v python3 &> /dev/null; then
        missing_deps+=("python3")
    fi

    # 检查 pip
    if ! python3 -m pip --version &> /dev/null; then
        missing_deps+=("python3-pip")
    fi

    # 检查 Node.js
    if ! command -v node &> /dev/null; then
        missing_deps+=("nodejs")
    fi

    # 检查 npm
    if ! command -v npm &> /dev/null; then
        missing_deps+=("npm")
    fi

    # 检查 MySQL/MariaDB
    if ! command -v mysql &> /dev/null; then
        missing_deps+=("mysql-client")
    fi

    # 检查 Redis
    if ! command -v redis-cli &> /dev/null; then
        missing_deps+=("redis-server")
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        log "WARN" "检测到缺少以下依赖: ${missing_deps[*]}"
        log "INFO" "请使用包管理器安装，例如:"
        echo -e "  ${CYAN}Ubuntu/Debian:${NC}"
        echo -e "    ${YELLOW}sudo apt-get install -y python3 python3-pip nodejs npm mysql-client redis-server${NC}"
        echo ""
        echo -e "  ${CYAN}CentOS/RHEL:${NC}"
        echo -e "    ${YELLOW}sudo yum install -y python3 python3-pip nodejs npm mysql redis${NC}"
        echo ""
        echo -e "  ${CYAN}macOS:${NC}"
        echo -e "    ${YELLOW}brew install python3 node mysql redis${NC}"
        echo ""

        read -p "是否继续安装? (yes/no): " confirm
        if [ "$confirm" != "yes" ] && [ "$confirm" != "y" ]; then
            log "ERROR" "安装已取消"
            exit 1
        fi
    fi

    # 检查 Python 版本
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    REQUIRED_VERSION="3.10"
    if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
        log "ERROR" "Python 版本需要 >= $REQUIRED_VERSION，当前版本: $PYTHON_VERSION"
        exit 1
    fi

    log "INFO" "依赖检查完成 (Python $PYTHON_VERSION)"
}

# ============================================================
# 交互式配置
# ============================================================
interactive_config() {
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                    配置参数设置                            ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # 数据库配置
    echo -e "${YELLOW}数据库配置${NC}"
    read -p "  数据库主机 [$DB_HOST]: " input
    DB_HOST="${input:-$DB_HOST}"

    read -p "  数据库端口 [$DB_PORT]: " input
    DB_PORT="${input:-$DB_PORT}"

    read -p "  数据库名称 [$DB_NAME]: " input
    DB_NAME="${input:-$DB_NAME}"

    read -p "  数据库用户 [$DB_USER]: " input
    DB_USER="${input:-$DB_USER}"

    read -p "  数据库密码: " input
    DB_PASS="${input:-$DB_PASS}"
    if [ -z "$DB_PASS" ]; then
        DB_PASS="longclaw123"
        log "WARN" "使用默认数据库密码"
    fi
    echo ""

    # Redis 配置
    echo -e "${YELLOW}Redis 配置${NC}"
    read -p "  Redis 主机 [$REDIS_HOST]: " input
    REDIS_HOST="${input:-$REDIS_HOST}"

    read -p "  Redis 端口 [$REDIS_PORT]: " input
    REDIS_PORT="${input:-$REDIS_PORT}"
    echo ""

    # API 密钥配置
    echo -e "${YELLOW}API 密钥配置${NC}"
    read -p "  API 密钥 [$API_KEY]: " input
    API_KEY="${input:-$API_KEY}"
    if [ -z "$API_KEY" ]; then
        API_KEY="longclaw_admin_$(date +%Y%m%d)"
        log "INFO" "生成随机 API 密钥: $API_KEY"
    fi
    echo ""

    # LLM 配置
    echo -e "${YELLOW}LLM 模型配置${NC}"
    echo "  可用提供商: openai, deepseek"
    read -p "  LLM 提供商 [$LLM_PROVIDER]: " input
    LLM_PROVIDER="${input:-$LLM_PROVIDER}"

    if [ "$LLM_PROVIDER" = "openai" ]; then
        read -p "  OpenAI API Key: " input
        OPENAI_API_KEY="${input:-$OPENAI_API_KEY}"
        read -p "  OpenAI Base URL [$OPENAI_BASE_URL]: " input
        OPENAI_BASE_URL="${input:-$OPENAI_BASE_URL}"
        read -p "  OpenAI Model [$OPENAI_MODEL]: " input
        OPENAI_MODEL="${input:-$OPENAI_MODEL}"
    elif [ "$LLM_PROVIDER" = "deepseek" ]; then
        read -p "  DeepSeek API Key: " input
        DEEPSEEK_API_KEY="${input:-$DEEPSEEK_API_KEY}"
        read -p "  DeepSeek Base URL [$DEEPSEEK_BASE_URL]: " input
        DEEPSEEK_BASE_URL="${input:-$DEEPSEEK_BASE_URL}"
        read -p "  DeepSeek Model [$DEEPSEEK_MODEL]: " input
        DEEPSEEK_MODEL="${input:-$DEEPSEEK_MODEL}"
    fi
    echo ""

    # 服务端口配置
    echo -e "${YELLOW}服务端口配置${NC}"
    read -p "  后端端口 [$BACKEND_PORT]: " input
    BACKEND_PORT="${input:-$BACKEND_PORT}"

    read -p "  前端端口 [$FRONTEND_PORT]: " input
    FRONTEND_PORT="${input:-$FRONTEND_PORT}"
    echo ""

    # 自动启动配置
    echo -e "${YELLOW}自动启动配置${NC}"
    read -p "  安装后自动启动服务? (yes/no) [yes]: " input
    AUTO_START="${input:-yes}"
    if [ "$AUTO_START" = "yes" ] || [ "$AUTO_START" = "y" ]; then
        AUTO_START=true
    else
        AUTO_START=false
    fi
}

# ============================================================
# 创建目录结构
# ============================================================
create_directories() {
    log "INFO" "创建目录结构..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$DATA_DIR"
    mkdir -p "$LOG_DIR"
    mkdir -p "$DATA_DIR/venv"

    log "INFO" "目录创建完成"
}

# ============================================================
# 复制文件
# ============================================================
copy_files() {
    log "INFO" "复制项目文件到 $INSTALL_DIR..."

    # 复制后端
    rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
          --exclude='.pytest_cache' --exclude='*.log' \
          "$PROJECT_DIR/backend/" "$INSTALL_DIR/backend/"

    # 复制前端 (不包括 node_modules)
    rsync -a --exclude='node_modules' --exclude='dist' --exclude='.cache' \
          "$PROJECT_DIR/frontend/" "$INSTALL_DIR/frontend/"

    # 复制脚本
    rsync -a "$PROJECT_DIR/scripts/" "$INSTALL_DIR/scripts/"

    # 复制配置文件
    cp "$PROJECT_DIR/backend/requirements.txt" "$INSTALL_DIR/backend/requirements.txt"
    cp "$PROJECT_DIR/frontend/package.json" "$INSTALL_DIR/frontend/package.json"

    log "INFO" "文件复制完成"
}

# ============================================================
# 安装后端依赖
# ============================================================
install_backend_deps() {
    log "INFO" "安装后端依赖..."

    cd "$INSTALL_DIR/backend"

    # 创建虚拟环境
    if [ ! -d "$DATA_DIR/venv" ]; then
        python3 -m venv "$DATA_DIR/venv"
        log "INFO" "Python 虚拟环境已创建"
    fi

    # 激活虚拟环境并安装依赖
    source "$DATA_DIR/venv/bin/activate"
    pip install --upgrade pip
    pip install -r requirements.txt

    deactivate

    log "INFO" "后端依赖安装完成"
}

# ============================================================
# 安装前端依赖
# ============================================================
install_frontend_deps() {
    if [ "$SKIP_FRONTEND" = true ]; then
        log "INFO" "跳过前端依赖安装"
        return
    fi

    log "INFO" "安装前端依赖..."

    cd "$INSTALL_DIR/frontend"
    npm install

    log "INFO" "前端依赖安装完成"
}

# ============================================================
# 构建前端
# ============================================================
build_frontend() {
    if [ "$SKIP_FRONTEND" = true ]; then
        log "INFO" "跳过前端构建"
        return
    fi

    log "INFO" "构建前端..."

    cd "$INSTALL_DIR/frontend"
    npm run build

    log "INFO" "前端构建完成"
}

# ============================================================
# 初始化数据库
# ============================================================
init_database() {
    if [ "$SKIP_DB" = true ]; then
        log "INFO" "跳过数据库初始化"
        return
    fi

    log "INFO" "初始化数据库..."

    # 创建数据库 (如果不存在)
    mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASS" -e "
        CREATE DATABASE IF NOT EXISTS $DB_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    " 2>/dev/null || log "WARN" "无法创建数据库，请确保 MySQL/MariaDB 已运行且配置正确"

    # 创建配置 .env 文件
    create_env_file

    # 初始化数据库表
    cd "$INSTALL_DIR"
    source "$DATA_DIR/venv/bin/activate"
    PYTHONPATH="$INSTALL_DIR" python3 -c "
        import asyncio
        from backend.database import db_manager
        from backend.config import get_settings

        async def init():
            settings = get_settings()
            await db_manager.init()
            await db_manager.create_tables()
            print('Database tables created successfully')

        asyncio.run(init())
    "
    deactivate

    log "INFO" "数据库初始化完成"
}

# ============================================================
# 创建环境配置文件
# ============================================================
create_env_file() {
    log "INFO" "创建 .env 配置文件..."

    cat > "$INSTALL_DIR/backend/.env" << EOF
# Server
HOST=0.0.0.0
PORT=$BACKEND_PORT
DEBUG=false

# Database
DB_HOST=$DB_HOST
DB_PORT=$DB_PORT
DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASS

# Redis
REDIS_HOST=$REDIS_HOST
REDIS_PORT=$REDIS_PORT
REDIS_DB=$REDIS_DB

# Auth
API_KEY=$API_KEY

# LLM Configuration
LLM_DEFAULT_PROVIDER=$LLM_PROVIDER
# OpenAI
OPENAI_API_KEY=$OPENAI_API_KEY
OPENAI_BASE_URL=$OPENAI_BASE_URL
OPENAI_MODEL=$OPENAI_MODEL
# DeepSeek
DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL=$DEEPSEEK_BASE_URL
DEEPSEEK_MODEL=$DEEPSEEK_MODEL
EOF

    # 也复制一份到项目根目录
    cp "$INSTALL_DIR/backend/.env" "$PROJECT_DIR/.env"

    log "INFO" ".env 配置文件已创建"
}

# ============================================================
# 创建 systemd 服务文件
# ============================================================
create_systemd_service() {
    if [ "$PRODUCTION" != true ]; then
        log "INFO" "非生产环境模式，跳过 systemd 服务创建"
        return
    fi

    log "INFO" "创建 systemd 服务..."

    # 后端服务
    cat > /etc/systemd/system/longclaw-backend.service << EOF
[Unit]
Description=LongClaw Backend Service
After=network.target mysql.service redis.service
Requires=mysql.service redis.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
Environment="PYTHONPATH=$INSTALL_DIR"
EnvironmentFile=$INSTALL_DIR/backend/.env
ExecStart=$DATA_DIR/venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    # 前端服务 (如果使用生产模式)
    cat > /etc/systemd/system/longclaw-frontend.service << EOF
[Unit]
Description=LongClaw Frontend Service
After=network.target longclaw-backend.service
Requires=longclaw-backend.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR/frontend
ExecStart=/usr/bin/npm run preview -- --port $FRONTEND_PORT --host 0.0.0.0
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    log "INFO" "systemd 服务已创建"
}

# ============================================================
# 创建启动脚本
# ============================================================
create_start_scripts() {
    log "INFO" "创建启动脚本..."

    # 开发模式启动脚本
    cat > "$INSTALL_DIR/start-dev.sh" << 'STARTSCRIPT'
#!/bin/bash
#
# LongClaw 开发模式启动脚本
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="/var/lib/longclaw"
LOG_DIR="/var/log/longclaw"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║              LongClaw 开发模式启动                       ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# 激活虚拟环境
source "$DATA_DIR/venv/bin/activate"

# 设置 Python 路径
export PYTHONPATH="$SCRIPT_DIR"

# 后台启动后端
echo -e "${YELLOW}启动后端服务 (端口 8001)...${NC}"
cd "$SCRIPT_DIR"
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "后端 PID: $BACKEND_PID"

# 等待后端启动
sleep 3

# 启动前端
echo -e "${YELLOW}启动前端服务 (端口 5173)...${NC}"
cd "$SCRIPT_DIR/frontend"
nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "前端 PID: $FRONTEND_PID"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ LongClaw 启动完成!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo "  后端: http://localhost:8001"
echo "  前端: http://localhost:5173"
echo "  API 文档: http://localhost:8001/docs"
echo ""
echo "  日志文件: $LOG_DIR/backend.log"
echo "           $LOG_DIR/frontend.log"
echo ""
echo "  停止服务: $SCRIPT_DIR/stop.sh"
echo ""

# 保持脚本运行
wait
STARTSCRIPT

    chmod +x "$INSTALL_DIR/start-dev.sh"

    # 生产模式启动脚本
    cat > "$INSTALL_DIR/start.sh" << 'STARTSCRIPT'
#!/bin/bash
#
# LongClaw 生产模式启动脚本
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Starting LongClaw services via systemd..."
systemctl start longclaw-backend.service
systemctl start longclaw-frontend.service

echo "Services started. Status:"
systemctl status longclaw-backend.service --no-pager
systemctl status longclaw-frontend.service --no-pager
STARTSCRIPT

    chmod +x "$INSTALL_DIR/start.sh"

    # 停止脚本
    cat > "$INSTALL_DIR/stop.sh" << 'STARTSCRIPT'
#!/bin/bash
#
# LongClaw 停止脚本
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="/var/lib/longclaw"

# 停止 Python 进程
pkill -f "uvicorn backend.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

# 停止 systemd 服务 (如果存在)
systemctl stop longclaw-backend.service 2>/dev/null || true
systemctl stop longclaw-frontend.service 2>/dev/null || true

echo "LongClaw services stopped."
STARTSCRIPT

    chmod +x "$INSTALL_DIR/stop.sh"

    # 状态检查脚本
    cat > "$INSTALL_DIR/status.sh" << 'STARTSCRIPT'
#!/bin/bash
#
# LongClaw 状态检查脚本
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/var/log/longclaw"

echo "=== LongClaw 状态检查 ==="
echo ""

# 检查后端进程
if pgrep -f "uvicorn backend.main:app" > /dev/null; then
    echo "✓ 后端服务: 运行中"
else
    echo "✗ 后端服务: 未运行"
fi

# 检查前端进程
if pgrep -f "vite" > /dev/null; then
    echo "✓ 前端服务: 运行中"
else
    echo "✗ 前端服务: 未运行"
fi

echo ""

# 检查端口
echo "=== 端口检查 ==="
netstat -tlnp 2>/dev/null | grep -E "(8001|5173)" || ss -tlnp | grep -E "(8001|5173)" || echo "端口检查工具不可用"
STARTSCRIPT

    chmod +x "$INSTALL_DIR/status.sh"

    log "INFO" "启动脚本已创建"
}

# ============================================================
# 启动服务
# ============================================================
start_services() {
    if [ "$AUTO_START" != true ]; then
        log "INFO" "跳过自动启动"
        return
    fi

    log "INFO" "启动服务..."

    # 检查数据库连接
    if ! mysql -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" -p"$DB_PASS" -e "SELECT 1" > /dev/null 2>&1; then
        log "WARN" "无法连接到数据库，请确保 MySQL/MariaDB 已启动"
        log "INFO" "启动命令: sudo systemctl start mysql"
    fi

    # 检查 Redis 连接
    if ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping > /dev/null 2>&1; then
        log "WARN" "无法连接到 Redis，请确保 Redis 已启动"
        log "INFO" "启动命令: sudo systemctl start redis"
    fi

    cd "$INSTALL_DIR"

    # 启动后端
    log "INFO" "启动后端服务..."
    source "$DATA_DIR/venv/bin/activate"
    export PYTHONPATH="$INSTALL_DIR"

    nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port $BACKEND_PORT > "$LOG_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!

    sleep 2

    # 检查后端是否启动成功
    if curl -s http://localhost:$BACKEND_PORT/health > /dev/null 2>&1; then
        log "INFO" "后端服务启动成功 (PID: $BACKEND_PID)"
    else
        log "WARN" "后端服务可能未正常启动，请检查日志: $LOG_DIR/backend.log"
    fi

    # 启动前端
    if [ "$SKIP_FRONTEND" != true ]; then
        log "INFO" "启动前端服务..."
        cd "$INSTALL_DIR/frontend"
        nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
        FRONTEND_PID=$!
        log "INFO" "前端服务已启动 (PID: $FRONTEND_PID)"
    fi

    deactivate

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║              LongClaw 部署完成!                           ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${YELLOW}服务地址:${NC}"
    echo -e "    后端: ${GREEN}http://localhost:$BACKEND_PORT${NC}"
    echo -e "    前端: ${GREEN}http://localhost:$FRONTEND_PORT${NC}"
    echo -e "    API文档: ${GREEN}http://localhost:$BACKEND_PORT/docs${NC}"
    echo ""
    echo -e "  ${YELLOW}配置信息:${NC}"
    echo -e "    API Key: ${GREEN}$API_KEY${NC}"
    echo ""
    echo -e "  ${YELLOW}管理脚本:${NC}"
    echo -e "    启动: ${GREEN}$INSTALL_DIR/start-dev.sh${NC}"
    echo -e "    停止: ${GREEN}$INSTALL_DIR/stop.sh${NC}"
    echo -e "    状态: ${GREEN}$INSTALL_DIR/status.sh${NC}"
    echo ""
    echo -e "  ${YELLOW}日志文件:${NC}"
    echo -e "    后端: ${GREEN}$LOG_DIR/backend.log${NC}"
    echo -e "    前端: ${GREEN}$LOG_DIR/frontend.log${NC}"
    echo ""
}

# ============================================================
# 主函数
# ============================================================
main() {
    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --skip-db)
                SKIP_DB=true
                shift
                ;;
            --skip-frontend)
                SKIP_FRONTEND=true
                shift
                ;;
            --production)
                PRODUCTION=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                echo "未知参数: $1"
                show_help
                exit 1
                ;;
        esac
    done

    # 显示欢迎信息
    echo -e "${CYAN}╔══════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                        ║${NC}"
    echo -e "${CYAN}║${NC}     ${GREEN}██████╗  ██████╗  ██████╗██╗  ██╗${CYAN}                   ║${NC}"
    echo -e "${CYAN}║${NC}     ${GREEN}██╔══██╗██╔════╝ ██╔════╝██║ ██╔╝${CYAN}                   ║${NC}"
    echo -e "${CYAN}║${NC}     ${GREEN}██████╔╝██║  ███╗██║     █████╔╝ ${CYAN}                   ║${NC}"
    echo -e "${CYAN}║${NC}     ${GREEN}██╔══██╗██║   ██║██║     ██╔═██╗ ${CYAN}                   ║${NC}"
    echo -e "${CYAN}║${NC}     ${GREEN}██████╔╝╚██████╔╝╚██████╗██║  ██╗${CYAN}                  ║${NC}"
    echo -e "${CYAN}║${NC}     ${GREEN}╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝${CYAN}                  ║${NC}"
    echo -e "${CYAN}║${NC}                    ${YELLOW}Agent Management Platform${CYAN}           ║${NC}"
    echo -e "${CYAN}║                                                        ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════╝${NC}"
    echo ""

    # 检查是否为 root 用户 (某些操作需要)
    if [ "$EUID" -ne 0 ] && [ "$PRODUCTION" = true ]; then
        echo -e "${YELLOW}警告: 生产模式安装建议使用 root 用户${NC}"
    fi

    # 执行安装步骤
    check_dependencies
    interactive_config
    create_directories
    copy_files
    install_backend_deps

    if [ "$SKIP_FRONTEND" != true ]; then
        install_frontend_deps
        build_frontend
    fi

    init_database
    create_start_scripts

    if [ "$PRODUCTION" = true ]; then
        create_systemd_service
    fi

    start_services
}

# 运行主函数
main "$@"
