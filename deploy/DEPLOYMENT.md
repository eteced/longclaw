# LongClaw 部署文档

## 部署概览

**项目名称**: LongClaw
**部署目标**: root@YOUR_SERVER_IP
**部署日期**: 2026-04-04
**部署方式**: SSH 远程部署
**部署状态**: ✅ 成功

---

## 部署步骤总结

### 1. 打包项目 (本地)

```bash
cd /home/claw/.openclaw/workspace/longclaw
chmod +x deploy/package.sh
./deploy/package.sh
```

生成部署包: `deploy/output/longclaw-202604041900.tar.gz`

### 2. 传输到目标服务器

```bash
sshpass -p 'YOUR_SSH_PASSWORD' scp deploy/output/longclaw-*.tar.gz root@YOUR_SERVER_IP:/root/
```

### 3. 在目标服务器上解压

```bash
ssh root@YOUR_SERVER_IP
cd /root
tar -xzvf longclaw-*.tar.gz
cd longclaw
chmod +x install.sh
```

### 4. 运行安装脚本

```bash
./install.sh
```

---

## 实际部署过程记录

### 环境准备

| 步骤 | 操作 | 结果 |
|------|------|------|
| 1 | SSH 连接测试 | ✅ 成功 |
| 2 | 传输部署包 (265KB) | ✅ 成功 |
| 3 | 检测操作系统 | ✅ Ubuntu 22.04.3 LTS |

### 依赖安装

| 依赖 | 安装方式 | 状态 |
|------|---------|------|
| Python | 系统自带 | ✅ 3.10.12 |
| Node.js | 手动安装 v18.20.0 | ✅ 成功 |
| MySQL | apt-get install | ✅ 成功 |
| Redis | apt-get install | ✅ 成功 |
| python3-venv | apt-get install | ✅ 成功 |
| cryptography | pip install | ✅ 成功 |

### 服务配置

| 步骤 | 操作 | 状态 |
|------|------|------|
| 1 | MySQL 服务启动 | ✅ 成功 |
| 2 | Redis 服务启动 | ✅ 成功 |
| 3 | Python 虚拟环境创建 | ✅ 成功 |
| 4 | Python 依赖安装 | ✅ 成功 |
| 5 | npm 依赖安装 | ✅ 成功 |
| 6 | 前端构建 (内存优化) | ✅ 成功 |
| 7 | 数据库表创建 | ✅ 成功 |
| 8 | 数据库初始化 | ✅ 成功 |

### 服务启动

| 服务 | 端口 | 状态 |
|------|------|------|
| 后端 (FastAPI) | 8001 | ✅ 运行中 |
| 前端 (Vite) | 5173 | ✅ 运行中 |

---

## 服务地址

| 服务 | 地址 | 状态 |
|------|------|------|
| 前端界面 | http://YOUR_SERVER_IP:5173 | ✅ 正常 |
| 后端 API | http://YOUR_SERVER_IP:8001 | ✅ 正常 |
| API 文档 | http://YOUR_SERVER_IP:8001/docs | ✅ 正常 |
| 健康检查 | http://YOUR_SERVER_IP:8001/health | ✅ `{"status":"healthy"}` |

---

## ⚠️ 安全配置 (重要!)

### API Key 配置

**当前默认 API Key**: `YOUR_API_KEY`

⚠️ **安全警告**: 默认 API Key 仅为测试用途，**必须**在生产环境修改！

#### 修改 API Key

1. 编辑配置文件:
```bash
nano /root/longclaw/backend/.env
```

2. 修改 `API_KEY` 值:
```env
API_KEY=your_secure_api_key_here
```

3. 重启服务使配置生效:
```bash
pkill -f uvicorn
cd /root/longclaw && source backend/venv/bin/activate && PYTHONPATH=/root/longclaw nohup python -c "
import uvicorn
uvicorn.run('backend.main:app', host='0.0.0.0', port=8001, log_level='info')
" > /var/log/longclaw/backend.log 2>&1 &
```

#### API Key 使用方式

调用 API 时需要在请求头中携带 API Key:
```bash
curl -X GET http://localhost:8001/api/system-config \
  -H "X-API-Key: your_api_key_here"
```

### LLM API Key 配置

当前 LLM API Key 配置在 `backend/.env` 中:

```env
OPENAI_API_KEY=YourOpenAIKey
OPENAI_BASE_URL=YourOpenAIProvider
```

如需修改 LLM 配置，请编辑 `backend/.env` 并重启服务。

---

## 遇到的问题及解决

### 问题 1: Node.js 版本过低

**问题描述**: 系统预装 Node.js 12.22.9，前端需要 Node.js 18+
**解决方式**: 从 npmmirror 下载 Node.js 18.20.0 预编译包手动安装

```bash
cd /tmp
wget https://npmmirror.com/mirrors/node/v18.20.0/node-v18.20.0-linux-arm64.tar.xz
tar -xf node-v18.20.0-linux-arm64.tar.xz
mv node-v18.20.0-linux-arm64 /opt/node
ln -sf /opt/node/bin/node /usr/local/bin/node
ln -sf /opt/node/bin/npm /usr/local/bin/npm
```

### 问题 2: 前端构建内存不足

**问题描述**: 构建时出现 `FATAL ERROR: NewSpace::Rebalance Allocation failed - JavaScript heap out of memory`
**解决方式**: 增加 Node.js 内存限制

```bash
NODE_OPTIONS='--max-old-space-size=4096' npm run build
```

### 问题 3: MySQL 认证方式

**问题描述**: `RuntimeError: 'cryptography' package is required for sha256_password or caching_sha2_password auth methods`
**解决方式**: 安装 cryptography 包

```bash
pip install cryptography
```

### 问题 4: 数据库表未创建

**问题描述**: init_db.py 执行时提示表不存在
**解决方式**: 手动调用 create_tables() 创建表

```python
async with db_manager.engine.begin() as conn:
    await conn.run_sync(Base.metadata.create_all)
```

### 问题 5: PYTHONPATH 问题

**问题描述**: 启动后端时 `ModuleNotFoundError: No module named 'backend'`
**解决方式**: 设置正确的 PYTHONPATH

```bash
PYTHONPATH="/root/longclaw" python -c "import uvicorn; uvicorn.run('backend.main:app', ...)"
```

---

## 关键配置

### 后端环境变量 (backend/.env)

```env
# 服务器
HOST=0.0.0.0
PORT=8001

# 数据库
DB_HOST=localhost
DB_PORT=3306
DB_NAME=longclaw
DB_USER=longclaw
DB_PASSWORD=longclaw123

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# API 认证 ⚠️ 请修改为安全的随机字符串
API_KEY=YOUR_API_KEY

# LLM 模型配置 ⚠️ 请使用你自己的 API Key
LLM_DEFAULT_PROVIDER=openai
OPENAI_API_KEY=YourOpenAIKey
OPENAI_BASE_URL=YourOpenAIProvider
OPENAI_MODEL=minimax-m2.7
```

### 新增配置项 (Chrome 进程管理)

```env
chrome_max_processes=10        # Chrome 最大进程数
chrome_cleanup_interval=60     # 清理检查间隔(秒)
chrome_session_max_age=120    # 孤儿会话判定时间(秒)
tool_search_timeout=30        # 网页搜索超时(秒)
tool_fetch_timeout=30        # 网页抓取超时(秒)
```

---

## 服务管理

### 启动服务

```bash
# 后端
cd /root/longclaw
source backend/venv/bin/activate
PYTHONPATH=/root/longclaw nohup python -c "
import uvicorn
uvicorn.run('backend.main:app', host='0.0.0.0', port=8001, log_level='info')
" > /var/log/longclaw/backend.log 2>&1 &

# 前端
cd /root/longclaw/frontend
nohup npm run dev > /var/log/longclaw/frontend.log 2>&1 &
```

### 停止服务

```bash
pkill -f uvicorn
pkill -f vite
```

### 查看日志

```bash
# 后端日志
tail -f /var/log/longclaw/backend.log

# 前端日志
tail -f /var/log/longclaw/frontend.log
```

### 健康检查

```bash
curl http://localhost:8001/health
```

---

## 数据库信息

| 项目 | 值 |
|------|-----|
| 数据库名 | longclaw |
| 用户名 | longclaw |
| 密码 | longclaw123 |
| 表数量 | 13 |
| 系统配置项 | 33 |
| 预设配置方案 | 5 |
| Resident Agent ID | 0a3bff71-854b-4275-adf1-8c5931317897 |
| Agent Name | 老六 |
| Web Channel ID | 56b99561-2f4a-446f-a163-9a9932a17a05 |

---

## 项目结构

```
/root/longclaw/
├── backend/                 # Python/FastAPI 后端
│   ├── agents/             # Agent 核心模块
│   ├── api/               # API 路由
│   ├── channels/          # 渠道模块
│   ├── middleware/        # 中间件
│   ├── models/            # 数据模型 (13个表)
│   ├── services/          # 服务层
│   ├── scripts/           # 初始化脚本
│   ├── main.py            # FastAPI 应用入口
│   ├── database.py        # 数据库配置
│   ├── config.py          # 配置管理
│   ├── requirements.txt    # Python 依赖
│   ├── venv/              # Python 虚拟环境
│   └── .env               # 环境变量配置
├── frontend/               # React/TypeScript 前端
│   ├── src/               # 源代码
│   ├── dist/              # 构建输出
│   ├── node_modules/      # npm 依赖
│   ├── package.json       # npm 依赖
│   └── vite.config.ts     # Vite 配置
├── deploy/                 # 部署相关
│   ├── package.sh         # 打包脚本
│   ├── install.sh         # 安装脚本 (已更新)
│   └── DEPLOYMENT.md      # 部署文档
└── scripts/               # 脚本目录
```

---

## 部署检查清单

- [ ] ⚠️ 修改默认 API Key (安全必需!)
- [ ] ⚠️ 修改 MySQL 数据库密码 (安全必需!)
- [ ] ⚠️ 修改 LLM API Key (如使用自己的 API)
- [x] MySQL 数据库创建成功
- [x] Redis 服务运行正常
- [x] Python 虚拟环境创建成功
- [x] Python 依赖安装完成
- [x] npm 依赖安装完成
- [x] 前端构建成功
- [x] 数据库初始化完成
- [x] 后端服务启动成功 (端口 8001)
- [x] 前端服务启动成功 (端口 5173)
- [x] API 健康检查通过
- [x] 浏览器访问前端界面正常

---

## 后续维护

### 重新初始化数据库

```bash
cd /root/longclaw
source backend/venv/bin/activate
PYTHONPATH=/root/longclaw python backend/scripts/init_db.py --force
```

### 更新代码后重新部署

1. 本地重新打包: `./deploy/package.sh`
2. 传输: `scp deploy/output/longclaw-*.tar.gz root@YOUR_SERVER_IP:/root/`
3. 解压覆盖: `cd /root && tar -xzvf longclaw-*.tar.gz`
4. 重启服务: `pkill -f uvicorn; pkill -f vite; ./install.sh`

---

**部署完成时间**: 2026-04-04 19:13 (UTC+8)
