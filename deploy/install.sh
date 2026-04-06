#!/bin/bash
#
# LongClaw 安装部署脚本
# ================================
# 此脚本在目标服务器上运行，安装和配置 LongClaw
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检测操作系统
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS=$ID
        VER=$VERSION_ID
    else
        OS="unknown"
        VER="unknown"
    fi
    log_info "检测到操作系统: $OS $VER"
}

# 安装系统依赖
install_system_deps() {
    log_info "安装系统依赖..."

    if [ "$OS" = "ubuntu" ] || [ "$OS" = "debian" ]; then
        apt-get update
        # 安装 Node.js 18
        cd /tmp
        wget -q https://npmmirror.com/mirrors/node/v18.20.0/node-v18.20.0-linux-$(uname -m).tar.xz
        tar -xf node-v18.20.0-linux-$(uname -m).tar.xz
        mv node-v18.20.0-linux-$(uname -m) /opt/node
        ln -sf /opt/node/bin/node /usr/local/bin/node
        ln -sf /opt/node/bin/npm /usr/local/bin/npm
        cd -
        apt-get install -y python3 python3-pip python3-venv mysql-server redis-server mysql-client
    elif [ "$OS" = "centos" ] || [ "$OS" = "rhel" ] || [ "$OS" = "rocky" ]; then
        yum install -y python3 python3-pip python3-venv nodejs npm mysql-server redis
    else
        log_warning "未知操作系统，请手动安装依赖"
    fi

    log_success "系统依赖安装完成"
}

# 配置 MySQL
setup_mysql() {
    log_info "配置 MySQL..."

    # 启动 MySQL
    service mysql start || true

    # 创建数据库和用户
    mysql -u root << 'EOF' || true
CREATE DATABASE IF NOT EXISTS `longclaw` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'longclaw'@'localhost' IDENTIFIED BY 'longclaw123';
CREATE USER IF NOT EXISTS 'longclaw'@'%' IDENTIFIED BY 'longclaw123';
GRANT ALL PRIVILEGES ON `longclaw`.* TO 'longclaw'@'localhost';
GRANT ALL PRIVILEGES ON `longclaw`.* TO 'longclaw'@'%';
FLUSH PRIVILEGES;
EOF

    log_success "MySQL 配置完成"
}

# 配置 Redis
setup_redis() {
    log_info "配置 Redis..."
    service redis-server start || redis-server --daemonize yes || true
    log_success "Redis 配置完成"
}

# 配置后端
setup_backend() {
    log_info "配置后端..."

    cd "$PROJECT_DIR/backend"

    # 创建虚拟环境
    log_info "创建 Python 虚拟环境..."
    python3 -m venv venv
    source venv/bin/activate

    # 安装依赖
    log_info "安装 Python 依赖..."
    pip install --upgrade pip
    pip install -r requirements.txt
    pip install cryptography  # MySQL 认证需要

    deactivate

    log_success "后端配置完成"
}

# 创建数据库表
create_tables() {
    log_info "创建数据库表..."
    cd "$PROJECT_DIR"
    source backend/venv/bin/activate
    PYTHONPATH="$PROJECT_DIR" python -c "
import asyncio
from backend.database import Base
from backend.models import *
from backend.database import db_manager

async def create():
    await db_manager.init()
    async with db_manager.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await db_manager.close()
    print('Tables created successfully')

asyncio.run(create())
"
    log_success "数据库表创建完成"
}

# 初始化数据库
init_database() {
    log_info "初始化数据库..."
    cd "$PROJECT_DIR"
    source backend/venv/bin/activate
    PYTHONPATH="$PROJECT_DIR" python backend/scripts/init_db.py --force
    log_success "数据库初始化完成"
}

# 配置前端
setup_frontend() {
    log_info "配置前端..."

    cd "$PROJECT_DIR/frontend"

    # 安装依赖
    log_info "安装前端依赖..."
    npm install

    # 构建前端
    log_info "构建前端..."
    NODE_OPTIONS='--max-old-space-size=4096' npm run build

    log_success "前端配置完成"
}

# 启动服务
start_services() {
    log_info "启动服务..."

    # 创建日志目录
    mkdir -p /var/log/longclaw 2>/dev/null || true

    # 停止旧服务
    pkill -f uvicorn 2>/dev/null || true
    pkill -f vite 2>/dev/null || true
    sleep 1

    # 启动后端
    log_info "启动后端服务..."
    cd "$PROJECT_DIR"
    source backend/venv/bin/activate
    PYTHONPATH="$PROJECT_DIR" nohup python -c "
import uvicorn
uvicorn.run('backend.main:app', host='0.0.0.0', port=8001, log_level='info')
" > /var/log/longclaw/backend.log 2>&1 &

    sleep 3

    # 检查后端是否启动成功
    if curl -s http://localhost:8001/health > /dev/null 2>&1; then
        log_success "后端服务启动成功"
    else
        log_warning "后端服务可能未正常启动，请检查日志"
    fi

    # 启动前端
    log_info "启动前端服务..."
    cd "$PROJECT_DIR/frontend"
    nohup npm run dev > /var/log/longclaw/frontend.log 2>&1 &

    sleep 3

    log_success "服务启动完成"
}

# 显示服务状态
show_status() {
    echo ""
    echo "=============================================="
    echo "  LongClaw 部署完成!"
    echo "=============================================="
    echo ""
    echo "  服务地址:"
    echo "  - 前端界面: http://localhost:5173"
    echo "  - 后端 API:  http://localhost:8001"
    echo "  - API 文档:  http://localhost:8001/docs"
    echo ""
    echo "  日志文件:"
    echo "  - 后端日志: /var/log/longclaw/backend.log"
    echo "  - 前端日志: /var/log/longclaw/frontend.log"
    echo ""
    echo "  常用命令:"
    echo "  - 停止服务: pkill -f uvicorn; pkill -f vite"
    echo "  - 重启后端: cd $PROJECT_DIR/backend && source venv/bin/activate && PYTHONPATH=$PROJECT_DIR python -c \"import uvicorn; uvicorn.run('backend.main:app', host='0.0.0.0', port=8001)\""
    echo "  - 重启前端: cd $PROJECT_DIR/frontend && npm run dev"
    echo "  - 健康检查: curl http://localhost:8001/health"
    echo ""
}

# 主函数
main() {
    echo ""
    echo "=============================================="
    echo "  LongClaw 安装部署脚本"
    echo "=============================================="
    echo ""

    detect_os
    install_system_deps

    echo ""
    echo "----------------------------------------------"
    echo "  开始配置"
    echo "----------------------------------------------"
    echo ""

    setup_mysql
    setup_redis
    setup_backend
    create_tables
    init_database
    setup_frontend
    start_services
    show_status
}

# 运行主函数
main "$@"
