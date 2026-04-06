#!/bin/bash
#
# LongClaw 一键安装脚本 (可复制粘贴到终端运行)
# ================================
# 使用方法:
#   curl -fsSL https://raw.githubusercontent.com/your-repo/longclaw/main/deploy/quick-start.sh | bash
#
# 或下载后本地运行:
#   chmod +x quick-start.sh && ./quick-start.sh
#

set -e

# 配置
INSTALL_DIR="${INSTALL_DIR:-/opt/longclaw}"
DATA_DIR="${DATA_DIR:-/var/lib/longclaw}"
LOG_DIR="${LOG_DIR:-/var/log/longclaw}"

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# 打印 banner
echo -e "${CYAN}"
echo "██████╗  ██████╗  ██████╗██╗  ██╗"
echo "██╔══██╗██╔════╝ ██╔════╝██║ ██╔╝"
echo "██████╔╝██║  ███╗██║     █████╔╝ "
echo "██╔══██╗██║   ██║██║     ██╔═██╗ "
echo "██████╔╝╚██████╔╝╚██████╗██║  ██╗"
echo "╚═════╝  ╚═════╝  ╚═════╝╚═╝  ╚═╝"
echo -e "${NC}"
echo -e "${YELLOW}Agent Management Platform${NC}"
echo ""

# 检查是否已安装
if [ -d "$INSTALL_DIR" ]; then
    warn "检测到已安装 LongClaw at $INSTALL_DIR"
    read -p "是否重新安装? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        log "取消安装"
        exit 0
    fi
fi

# 检查依赖
check_dep() {
    if ! command -v $1 &> /dev/null; then
        error "缺少依赖: $1"
    fi
}

log "检查系统依赖..."
check_dep python3
check_dep node
check_dep npm

# 创建目录
log "创建安装目录..."
sudo mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"
sudo chmod 755 "$INSTALL_DIR" "$DATA_DIR" "$LOG_DIR"

# 获取当前目录 (假设脚本在项目根目录)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 复制文件
log "复制文件..."
rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='.pytest_cache' --exclude='*.log' \
      "$SCRIPT_DIR/backend/" "$INSTALL_DIR/backend/"
rsync -a --exclude='node_modules' --exclude='dist' \
      "$SCRIPT_DIR/frontend/" "$INSTALL_DIR/frontend/"

# 安装后端依赖
log "安装后端依赖..."
cd "$INSTALL_DIR/backend"
python3 -m venv "$DATA_DIR/venv"
source "$DATA_DIR/venv/bin/activate"
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 安装前端依赖
log "安装前端依赖..."
cd "$INSTALL_DIR/frontend"
npm install

# 创建 .env 配置
log "创建配置文件..."
cat > "$INSTALL_DIR/backend/.env" << 'EOF'
# Server
HOST=0.0.0.0
PORT=8001
DEBUG=false

# Database
DB_HOST=localhost
DB_PORT=3306
DB_NAME=longclaw
DB_USER=longclaw
DB_PASSWORD=longclaw123

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Auth
API_KEY=YOUR_API_KEY

# LLM Configuration
LLM_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o
EOF

# 创建启动脚本
log "创建启动脚本..."
cat > "$INSTALL_DIR/start.sh" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="/var/lib/longclaw"

source "$DATA_DIR/venv/bin/activate"
export PYTHONPATH="$SCRIPT_DIR"

cd "$SCRIPT_DIR"
nohup python -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 > /var/log/longclaw/backend.log 2>&1 &

cd "$SCRIPT_DIR/frontend"
nohup npm run dev > /var/log/longclaw/frontend.log 2>&1 &

echo "LongClaw 已启动!"
echo "前端: http://localhost:5173"
echo "后端: http://localhost:8001"
EOF
chmod +x "$INSTALL_DIR/start.sh"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✓ 安装完成!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  安装位置: ${CYAN}$INSTALL_DIR${NC}"
echo ""
echo -e "  ${YELLOW}下一步操作:${NC}"
echo ""
echo -e "  1. 配置数据库:"
echo -e "     确保 MySQL/MariaDB 运行中，并创建数据库:"
echo -e "     ${CYAN}CREATE DATABASE longclaw CHARACTER SET utf8mb4;${NC}"
echo ""
echo -e "  2. 编辑配置文件:"
echo -e "     ${CYAN}vim $INSTALL_DIR/backend/.env${NC}"
echo -e "     设置您的 LLM API Key"
echo ""
echo -e "  3. 启动服务:"
echo -e "     ${CYAN}$INSTALL_DIR/start.sh${NC}"
echo ""
echo -e "  4. 访问:"
echo -e "     前端: ${CYAN}http://localhost:5173${NC}"
echo -e "     后端: ${CYAN}http://localhost:8001${NC}"
echo ""
