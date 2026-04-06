#!/bin/bash
#
# LongClaw 部署包打包脚本
# ================================
# 此脚本将 LongClaw 打包为一个 tar.gz 文件，方便分发和部署
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
OUTPUT_DIR="$PROJECT_DIR/deploy/output"
PACKAGE_NAME="longclaw"
VERSION=$(date +%Y%m%d%H%M)

echo "=============================================="
echo "  LongClaw 部署包打包工具"
echo "=============================================="
echo ""

# 创建输出目录
mkdir -p "$OUTPUT_DIR"

# 创建临时目录
TEMP_DIR=$(mktemp -d)
BUILD_DIR="$TEMP_DIR/longclaw"

echo "[1/6] 创建打包目录..."
mkdir -p "$BUILD_DIR"

# 复制部署脚本
echo "[2/6] 复制部署脚本..."
cp "$SCRIPT_DIR/install.sh" "$BUILD_DIR/"

# 复制后端源代码（排除敏感文件）
echo "[3/6] 复制后端源代码..."
rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='.pytest_cache' --exclude='*.log' --exclude='node_modules' \
      --exclude='.env' --exclude='.env.*' \
      "$PROJECT_DIR/backend/" "$BUILD_DIR/backend/"

# 复制前端源代码（排除敏感文件）
echo "[4/6] 复制前端源代码..."
rsync -a --exclude='node_modules' --exclude='dist' --exclude='.cache' \
      --exclude='.env' --exclude='.env.*' \
      "$PROJECT_DIR/frontend/" "$BUILD_DIR/frontend/"

# 复制配置文件（不包含敏感信息）
cp "$PROJECT_DIR/backend/.env.example" "$BUILD_DIR/backend/.env.example" 2>/dev/null || true
cp "$PROJECT_DIR/backend/requirements.txt" "$BUILD_DIR/"

# 注意：不复制 .env 文件，部署时需要重新生成

# 复制脚本
mkdir -p "$BUILD_DIR/scripts"
rsync -a --exclude='__pycache__' "$PROJECT_DIR/scripts/" "$BUILD_DIR/scripts/"

# 创建版本说明
cat > "$BUILD_DIR/VERSION.txt" << EOF
LongClaw Deployment Package
===========================

Version: $VERSION
Created: $(date '+%Y-%m-%d %H:%M:%S')

Package Contents:
- install.sh: 一键安装部署脚本
- backend/: 后端源代码
- frontend/: 前端源代码
- scripts/: 初始化脚本

Requirements:
- Python 3.10+
- Node.js 18+
- MySQL/MariaDB 5.7+
- Redis 6+

Quick Start:
1. Extract this package to target machine
2. Run: chmod +x install.sh && ./install.sh
3. Follow the interactive prompts
EOF

# 创建快速开始指南
cat > "$BUILD_DIR/README.md" << 'EOF'
# LongClaw 部署指南

## ⚠️ 安全警告 ⚠️

**LongClaw 安全性有限，请务必遵守以下部署要求：**

### 部署环境要求
- **禁止** 直接部署在有公网IP的个人电脑上
- **禁止** 直接暴露到公网
- **只允许** 在以下环境中部署：
  - 内部虚拟机（Internal VM）
  - Docker 容器（需网络隔离）
  - 物理隔离的硬件设备（如树莓派、家庭服务器）
  - 内部网络环境

### 必须的安全措施
1. 使用 VPN 或反向代理提供外部访问
2. 务必修改默认的 API_KEY
3. 数据库密码必须使用强密码
4. 启用防火墙，只开放必要端口

### 不适合的场景
- ❌ 直接部署在云服务器（需要额外安全层）
- ❌ 直接对外提供公共服务
- ❌ 在公共WiFi环境下使用

## 系统要求

- **Python**: 3.10 或更高版本
- **Node.js**: 18 或更高版本
- **npm**: 8 或更高版本
- **MySQL/MariaDB**: 5.7 或更高版本 (支持 UTF8MB4)
- **Redis**: 6 或更高版本
- **内存**: 最少 2GB，推荐 4GB+

## 快速开始

### 1. 运行安装脚本

```bash
chmod +x install.sh
./install.sh
```

安装脚本会引导你完成以下配置：
- 数据库连接信息
- Redis 连接信息
- API 密钥设置（务必设置强密码！）
- LLM 模型配置
- 服务端口配置

### 2. 启动服务

安装完成后，服务会自动启动。如果没有自动启动，可以使用：

```bash
# 启动后端
cd backend
source venv/bin/activate
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8001

# 启动前端
cd frontend
npm run dev
```

### 3. 访问服务

- 前端界面: http://localhost:5173
- 后端 API: http://localhost:8001
- API 文档: http://localhost:8001/docs

## 配置说明

### 环境变量

配置文件位于 `backend/.env`，主要配置项：

```env
# 服务器配置
HOST=0.0.0.0
PORT=8001

# 数据库配置
DB_HOST=localhost
DB_PORT=3306
DB_NAME=longclaw
DB_USER=longclaw
DB_PASSWORD=your_strong_password_here

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379

# API 认证（必须设置强密码，建议32位以上）
API_KEY=your_strong_api_key_here

# LLM 模型配置
LLM_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=gpt-4o
```

### 数据库初始化

如果需要重新初始化数据库：

```bash
cd /opt/longclaw
source venv/bin/activate
PYTHONPATH=. python scripts/init_db.py --force
```

## 管理命令

```bash
# 停止服务
pkill -f uvicorn
pkill -f vite

# 检查后端状态
curl http://localhost:8001/health

# 查看后端日志
tail -f backend.log
```

## 常见问题

### Q: 安装脚本提示缺少依赖
A: 请使用包管理器安装，例如：
```bash
# Ubuntu/Debian
sudo apt-get install python3 python3-pip nodejs npm mysql-client redis-server

# CentOS/RHEL
sudo yum install python3 python3-pip nodejs npm mysql redis
```

### Q: 数据库连接失败
A: 检查 MySQL/MariaDB 是否运行：
```bash
sudo systemctl status mysql
```

### Q: Redis 连接失败
A: 检查 Redis 是否运行：
```bash
sudo systemctl status redis
```

### Q: 前端无法访问后端 API
A: 检查后端服务是否正常运行：
```bash
curl http://localhost:8001/health
```

## 技术支持

如有问题，请联系开发者。
EOF

# 打包
echo "[5/6] 正在打包..."
cd "$TEMP_DIR"
tar -czvf "$OUTPUT_DIR/${PACKAGE_NAME}-${VERSION}.tar.gz" longclaw/

# 清理
rm -rf "$TEMP_DIR"

echo "[6/6] 打包完成!"
echo ""
echo "=============================================="
echo "  打包完成!"
echo "=============================================="
echo ""
echo "  输出文件: $OUTPUT_DIR/${PACKAGE_NAME}-${VERSION}.tar.gz"
echo "  文件大小: $(du -h "$OUTPUT_DIR/${PACKAGE_NAME}-${VERSION}.tar.gz" | cut -f1)"
echo ""
echo "  分发到目标机器后，解压并运行:"
echo "    tar -xzvf ${PACKAGE_NAME}-${VERSION}.tar.gz"
echo "    cd longclaw"
echo "    chmod +x install.sh"
echo "    ./install.sh"
echo ""
