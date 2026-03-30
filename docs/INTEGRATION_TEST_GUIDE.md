# LongClaw 集成测试指南

本文档描述如何进行 LongClaw 的集成测试，包括环境准备、初始化、API 调用示例等。

## 目录

- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [数据库初始化](#数据库初始化)
- [API 接口](#api-接口)
- [测试流程](#测试流程)
- [常见问题](#常见问题)

---

## 环境要求

- Python 3.12+
- MySQL 8.0+ 或 MariaDB
- Redis (可选，用于消息推送)
- Node.js 18+ (前端)

### 环境变量

创建 `.env` 文件或在环境中设置：

```bash
# 数据库配置
DATABASE_URL=mysql+aiomysql://user:password@localhost:3306/longclaw

# Redis 配置 (可选)
REDIS_URL=redis://localhost:6379/0

# API 密钥 (用于认证)
API_KEY=your-api-key-here

# LLM 配置
LLM_PROVIDER=openai
LLM_MODEL=gpt-4
LLM_API_KEY=your-llm-api-key
LLM_BASE_URL=https://api.openai.com/v1

# 服务配置
HOST=0.0.0.0
PORT=8001
DEBUG=false
```

---

## 快速开始

### 1. 启动后端服务

```bash
cd /path/to/longclaw

# 安装依赖
cd backend
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
pip install -r requirements.txt

# 启动服务
cd ..
python -m backend.main
```

后端服务将在 `http://localhost:8001` 启动。

### 2. 启动前端服务 (可选)

```bash
cd frontend
npm install
npm run dev
```

前端服务将在 `http://localhost:5173` 启动。

---

## 数据库初始化

### 使用初始化脚本

在清空数据库后，使用初始化脚本创建必要的默认数据：

```bash
cd /path/to/longclaw

# 交互式执行 (会提示确认)
PYTHONPATH=. python3 scripts/init_db.py

# 跳过确认直接执行
PYTHONPATH=. python3 scripts/init_db.py --force
```

### 初始化内容

脚本将执行以下操作：

1. **清空数据表**
   - messages, subtasks, tasks, agents, channels, conversations, knowledge, agent_prompts, system_config

2. **创建系统配置**
   - 超时配置
   - 工具配置
   - 调度器配置
   - Reflect 配置

3. **创建 Resident Agent**
   - 名称: 老六
   - 类型: RESIDENT
   - 默认绑定到 Web Channel

4. **创建 Web Channel**
   - 类型: WEB
   - 绑定 Resident Agent
   - 状态: is_active = true

### 验证初始化

```bash
# 检查后端健康状态
curl http://localhost:8001/health

# 检查 Agent 列表
curl -H "X-API-Key: your-api-key" http://localhost:8001/api/agents

# 检查 Channel 列表
curl -H "X-API-Key: your-api-key" http://localhost:8001/api/channels
```

---

## API 接口

### 认证

所有 API 请求需要在 Header 中携带 API Key：

```
X-API-Key: your-api-key
```

### 核心 API

#### 1. 发送聊天消息

```bash
POST /api/chat/send
Content-Type: application/json
X-API-Key: your-api-key

{
    "channel_id": "channel-uuid",
    "content": "帮我搜索最新的 AI 新闻"
}
```

响应：
```json
{
    "message_id": "msg-uuid",
    "reply": "好的，我来帮你搜索...",
    "created_at": "2026-03-25T10:00:00Z",
    "task_id": "task-uuid"  // 如果创建了任务
}
```

#### 2. 获取 Web Channel 信息

```bash
GET /api/chat/web-channel
X-API-Key: your-api-key
```

响应：
```json
{
    "id": "channel-uuid",
    "channel_type": "web",
    "resident_agent_id": "agent-uuid",
    "is_active": true,
    "created_at": "2026-03-25T10:00:00Z"
}
```

#### 3. 获取任务列表

```bash
GET /api/tasks?status=running&limit=10
X-API-Key: your-api-key
```

#### 4. 获取任务详情

```bash
GET /api/tasks/{task_id}
X-API-Key: your-api-key
```

#### 5. 获取 Agent 列表

```bash
GET /api/agents?agent_type=worker&status=running
X-API-Key: your-api-key
```

#### 6. 获取 Agent 消息

```bash
GET /api/agents/{agent_id}/messages?limit=50
X-API-Key: your-api-key
```

### WebSocket 接口

连接地址: `ws://localhost:8001/api/ws`

#### 消息格式

```javascript
// 订阅频道
{ "action": "subscribe", "channel_id": "channel-uuid" }

// 取消订阅
{ "action": "unsubscribe", "channel_id": "channel-uuid" }

// 心跳
{ "action": "ping" }
```

#### 接收消息类型

- `stream_chunk`: 流式输出块
- `stream_end`: 流式输出结束
- `stream_error`: 流式输出错误
- `message`: 新消息通知
- `agent_update`: Agent 状态更新
- `task_update`: 任务状态更新
- `pong`: 心跳响应

---

## 测试流程

### 基础测试

```bash
# 1. 初始化数据库
PYTHONPATH=. python3 scripts/init_db.py --force

# 2. 启动后端
python -m backend.main &

# 3. 等待服务启动
sleep 5

# 4. 健康检查
curl http://localhost:8001/health

# 5. 获取 Web Channel
curl -H "X-API-Key: test-key" http://localhost:8001/api/chat/web-channel

# 6. 发送测试消息
curl -X POST http://localhost:8001/api/chat/send \
    -H "Content-Type: application/json" \
    -H "X-API-Key: test-key" \
    -d '{"channel_id": "your-channel-id", "content": "你好"}'

# 7. 检查任务状态
curl -H "X-API-Key: test-key" http://localhost:8001/api/tasks
```

### 自动化测试脚本示例

```python
#!/usr/bin/env python3
"""自动化集成测试脚本示例"""

import asyncio
import aiohttp
import json

API_URL = "http://localhost:8001"
API_KEY = "your-api-key"

async def test_integration():
    async with aiohttp.ClientSession() as session:
        headers = {"X-API-Key": API_KEY}

        # 1. 健康检查
        async with session.get(f"{API_URL}/health") as resp:
            assert resp.status == 200
            print("✓ 健康检查通过")

        # 2. 获取 Web Channel
        async with session.get(f"{API_URL}/api/chat/web-channel", headers=headers) as resp:
            assert resp.status == 200
            channel = await resp.json()
            channel_id = channel["id"]
            print(f"✓ 获取 Channel: {channel_id}")

        # 3. 发送消息
        async with session.post(
            f"{API_URL}/api/chat/send",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps({
                "channel_id": channel_id,
                "content": "测试消息：搜索今天的新闻"
            })
        ) as resp:
            assert resp.status == 200
            result = await resp.json()
            print(f"✓ 发送消息成功: {result.get('message_id')}")
            task_id = result.get("task_id")

        # 4. 等待任务完成
        if task_id:
            await asyncio.sleep(5)
            async with session.get(
                f"{API_URL}/api/tasks/{task_id}",
                headers=headers
            ) as resp:
                task = await resp.json()
                print(f"✓ 任务状态: {task['status']}")

        print("\n集成测试完成!")

if __name__ == "__main__":
    asyncio.run(test_integration())
```

### 任务终止测试

测试任务在执行过程中被手动终止的功能。

```python
#!/usr/bin/env python3
"""任务终止功能测试脚本"""

import asyncio
import aiohttp
import json

API_URL = "http://localhost:8001"
API_KEY = "your-api-key"

async def test_task_termination():
    """测试任务终止功能"""
    async with aiohttp.ClientSession() as session:
        headers = {"X-API-Key": API_KEY}

        # 1. 获取 Web Channel
        async with session.get(f"{API_URL}/api/chat/web-channel", headers=headers) as resp:
            channel = await resp.json()
            channel_id = channel["id"]
            print(f"✓ 获取 Channel: {channel_id}")

        # 2. 发送一个复杂任务（会触发 OwnerAgent）
        async with session.post(
            f"{API_URL}/api/chat/send",
            headers={**headers, "Content-Type": "application/json"},
            data=json.dumps({
                "channel_id": channel_id,
                "content": "帮我搜索并对比三款最新的智能手机，分析各自的优缺点"
            })
        ) as resp:
            result = await resp.json()
            task_id = result.get("task_id")
            message_id = result.get("message_id")
            print(f"✓ 创建任务: {task_id}")

        if not task_id:
            print("✗ 未创建任务，跳过终止测试")
            return

        # 3. 等待一小段时间让任务开始执行
        await asyncio.sleep(2)

        # 4. 检查任务状态（应该是 RUNNING）
        async with session.get(f"{API_URL}/api/tasks/{task_id}", headers=headers) as resp:
            task = await resp.json()
            print(f"✓ 任务状态: {task['status']}")
            owner_agent_id = task.get("owner_agent_id")
            print(f"  Owner Agent: {owner_agent_id}")

        # 5. 获取关联的 agents
        async with session.get(
            f"{API_URL}/api/agents?task_id={task_id}",
            headers=headers
        ) as resp:
            agents = await resp.json()
            print(f"✓ 关联 Agents: {len(agents.get('items', []))} 个")
            for agent in agents.get("items", []):
                print(f"  - {agent['agent_type']}: {agent['id']} ({agent['status']})")

        # 6. 终止任务
        print("\n>>> 发送终止请求...")
        async with session.post(
            f"{API_URL}/api/tasks/{task_id}/terminate",
            headers=headers
        ) as resp:
            terminated_task = await resp.json()
            print(f"✓ 任务已终止: {terminated_task['status']}")

        # 7. 验证任务状态
        async with session.get(f"{API_URL}/api/tasks/{task_id}", headers=headers) as resp:
            task = await resp.json()
            assert task["status"] == "terminated", f"预期 terminated，实际 {task['status']}"
            assert task["terminated_at"] is not None, "terminated_at 应该有值"
            print(f"✓ 任务状态验证通过: {task['status']}")

        # 8. 验证 Owner Agent 状态
        if owner_agent_id:
            async with session.get(f"{API_URL}/api/agents/{owner_agent_id}", headers=headers) as resp:
                if resp.status == 200:
                    owner = await resp.json()
                    assert owner["status"] == "terminated", f"Owner Agent 应为 terminated，实际 {owner['status']}"
                    print(f"✓ Owner Agent 状态验证通过: {owner['status']}")

        # 9. 验证所有 Worker Agents 状态
        async with session.get(
            f"{API_URL}/api/agents?task_id={task_id}",
            headers=headers
        ) as resp:
            agents = await resp.json()
            for agent in agents.get("items", []):
                if agent["agent_type"] in ("WORKER", "OWNER"):
                    assert agent["status"] == "terminated", \
                        f"Agent {agent['id']} 应为 terminated，实际 {agent['status']}"
            print(f"✓ 所有 Worker Agents 已终止")

        # 10. 验证子任务状态
        async with session.get(f"{API_URL}/api/tasks/{task_id}/subtasks", headers=headers) as resp:
            subtasks = await resp.json()
            for subtask in subtasks:
                if subtask["status"] not in ("completed", "failed", "terminated"):
                    print(f"  ! 子任务 {subtask['id']} 状态异常: {subtask['status']}")
            print(f"✓ 子任务状态验证完成 ({len(subtasks)} 个)")

        print("\n✅ 任务终止测试通过!")

if __name__ == "__main__":
    asyncio.run(test_task_termination())
```

### 终止功能验证清单

手动验证终止功能时，检查以下项目：

| 检查项 | 预期结果 |
|--------|----------|
| 任务状态 | 变为 `terminated` |
| `terminated_at` 字段 | 有时间戳 |
| Owner Agent 状态 | 变为 `terminated` |
| Worker Agents 状态 | 全部变为 `terminated` |
| 未完成的子任务 | 状态变为 `terminated` |
| 已完成的子任务 | 状态保持不变 |
| Agent 日志 | 显示检测到终止并退出 |

---

## 常见问题

### Q1: 数据库连接失败

检查：
1. MySQL 服务是否启动
2. 数据库 `longclaw` 是否存在
3. 用户名密码是否正确
4. `.env` 文件中的 `DATABASE_URL` 是否正确

```bash
# 创建数据库
mysql -u root -p -e "CREATE DATABASE longclaw CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### Q2: API 返回 401 Unauthorized

检查：
1. 请求 Header 是否包含 `X-API-Key`
2. API Key 是否与 `.env` 中的 `API_KEY` 匹配

### Q3: Agent 超时

Agent 的超时机制：
- Resident Agent: 600秒 (可配置)
- Owner Agent: 600秒 (可配置)
- Worker Agent: 300秒 (可配置)
- 只要 Agent 有进展（LLM 响应、工具调用），超时会自动延长

修改配置：
```bash
# 通过 API 修改
curl -X PUT http://localhost:8001/api/system-config/worker_subtask_timeout \
    -H "Content-Type: application/json" \
    -H "X-API-Key: your-api-key" \
    -d '{"value": "600"}'
```

### Q4: WebSocket 连接失败

检查：
1. 后端服务是否启动
2. 前端 WebSocket URL 是否正确 (`ws://localhost:8001/api/ws`)
3. 防火墙是否阻止 WebSocket 连接

### Q5: 任务一直处于 RUNNING 状态

可能原因：
1. LLM API 响应慢或超时
2. 工具执行耗时较长
3. Agent 遇到错误但未正确处理

排查：
```bash
# 查看 Agent 状态
curl -H "X-API-Key: your-api-key" http://localhost:8001/api/agents

# 查看任务详情
curl -H "X-API-Key: your-api-key" http://localhost:8001/api/tasks/{task_id}

# 查看 Agent 消息
curl -H "X-API-Key: your-api-key" http://localhost:8001/api/agents/{agent_id}/messages
```

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend (React)                      │
│                    http://localhost:5173                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Backend (FastAPI)                         │
│                    http://localhost:8001                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │   Router    │  │  Services   │  │   Models    │         │
│  │  (API/ws)   │  │ (Task/Agent)│  │  (SQLAlchemy)│        │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    MySQL    │     │    Redis    │     │  LLM API    │
│  (Database) │     │  (Pub/Sub)  │     │ (OpenAI等)  │
└─────────────┘     └─────────────┘     └─────────────┘
```

### Agent 调用链路

```
Channel Message
      │
      ▼
ResidentAgent (常驻)
      │ 判断任务复杂度
      ├── 简单任务 → 直接执行
      └── 复杂任务 → 创建 OwnerAgent
                          │
                          ▼
                    OwnerAgent (任务编排)
                          │ 分解任务
                          ▼
                    WorkerAgent x N (并行执行)
                          │ 使用工具
                          ▼
                    结果汇总 → 返回用户
```

---

## 相关文档

- [核心改进诉求](./核心改进诉求20260324.md)
- [API 文档](http://localhost:8001/docs) (启动后端后访问)
- [系统配置说明](../backend/services/config_service.py)

---

## 更新日志

- 2026-03-30: 添加任务终止功能测试案例
- 2026-03-25: 初始版本，添加集成测试指南
