# LongClaw 项目概览

> 最后更新：2026-03-24

## 1. 项目简介

LongClaw 是一个可自托管的 AI Agent 平台，支持多 Agent 协作、任务自动拆解与并行执行。

### 核心能力

- **自然语言任务处理**：用户输入自然语言任务 → 自动判断是否需要拆解 → 拆解为并行子任务 → Agent 执行 → 汇总结果
- **Web 搜索与抓取**：通过 agent-browser CLI（Playwright 浏览器自动化）实现多搜索引擎支持
- **多 LLM Provider**：支持 OpenAI-compatible API，当前默认使用本地量化模型 Qwen3.5-122B
- **Web Dashboard**：完整的 React 前端，支持 Agent、Task、Prompt、System Config 等管理

---

## 2. 技术栈详情

| 组件 | 技术栈 | 版本要求 | 说明 |
|------|--------|---------|------|
| 后端框架 | Python + FastAPI + Uvicorn | Python 3.12+, FastAPI 0.109+ | 异步 REST API |
| 数据库 | MariaDB (MySQL compatible) + SQLAlchemy | SQLAlchemy 2.0+ | 异步 ORM，连接池 |
| 缓存 | Redis | 5.0+ | 消息发布/订阅 |
| 前端框架 | React 18 + TypeScript + Vite | React 18.2+ | SPA，TailwindCSS |
| LLM | OpenAI-compatible API | - | 支持本地/云端模型 |
| 搜索工具 | agent-browser CLI | - | Playwright 浏览器自动化 |
| HTTP 客户端 | httpx | 0.26+ | 异步 HTTP，支持流式 |
| HTML 解析 | BeautifulSoup4 + lxml | 4.12+ | 网页内容解析 |

### 依赖清单 (requirements.txt)

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
sqlalchemy>=2.0.0
aiomysql>=0.2.0
pymysql>=1.1.0
redis>=5.0.0
httpx>=0.26.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
python-dotenv>=1.0.0
uuid6>=2023.5.2
pytest>=7.4.0
pytest-asyncio>=0.23.0
```

### 前端依赖 (package.json)

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.22.0",
    "axios": "^1.6.7",
    "date-fns": "^3.3.1",
    "lucide-react": "^0.344.0"
  },
  "devDependencies": {
    "typescript": "^5.2.2",
    "vite": "^5.1.4",
    "tailwindcss": "^3.4.1"
  }
}
```

---

## 3. 系统架构

### 3.1 Agent 层级结构

```
┌─────────────────────┐
│   ResidentAgent     │  ← 常驻 Agent，接收用户消息
│     (老六)           │     - 简单问题直接回复
│                     │     - 复杂任务 → 创建 Task
└──────────┬──────────┘
           │ Task (PLANNING)
           ▼
┌─────────────────────┐
│    OwnerAgent       │  ← 任务调度 Agent（生命周期：任务完成即销毁）
│                     │     - 拆解为 SubTasks
│                     │     - 创建 WorkerAgents 并行执行
│                     │     - 汇总所有结果
└──────────┬──────────┘
           │ SubTasks (并行)
      ┌────┴────┬────────┐
      ▼         ▼        ▼
   ┌─────┐  ┌─────┐  ┌─────┐
   │ W1  │  │ W2  │  │ W3  │  ← WorkerAgent / SubAgent
   │     │  │     │  │     │     - 使用 web_search / web_fetch
   └─────┘  └─────┘  └─────┘     - 获取信息并返回结果
```

### 3.2 完整数据流

```
用户消息
  │
  ▼
POST /api/chat/send
  │
  ▼
ResidentAgent.on_message()
  │
  ├── 简单问题 → LLM 直接回复
  │
  └── 复杂任务 → 创建 Task(PLANNING)
        │
        ├── 直接工具调用模式
        │     └── ResidentAgent._execute_with_tools()
        │           └── LLM + web_search/web_fetch 循环
        │
        └── OwnerAgent 调度模式
              │
              ├── 1. LLM 拆解为 N 个 SubTask
              │
              ├── 2. 创建 N 个 WorkerAgent 并行执行
              │     └── WorkerAgent._execute_with_tools()
              │           └── LLM + web_search/web_fetch 循环
              │                 └── 搜索次数限制（连续 3 次后强制停止）
              │
              └── 3. OwnerAgent._synthesize_results()
                    └── LLM 整合所有子任务结果
              │
              ▼
        Task 状态更新为 COMPLETED
              │
              ▼
        ResidentAgent 收到通知，回复用户
  │
  ▼
消息存入 messages 表
  │
  ▼
前端 polling 获取新消息（2秒间隔）
```

### 3.3 各 Agent 详细说明

| Agent 类型 | 生命周期 | 职责 | 持久化 | 文件位置 |
|-----------|---------|------|--------|---------|
| ResidentAgent | 常驻（服务运行期间） | 接收用户消息、创建Task、回复结果 | ✅ 数据库 | `agents/resident_agent.py` |
| OwnerAgent | 任务级（任务完成后销毁） | 任务拆解、Worker调度、结果汇总 | ❌ 不持久化 | `agents/owner_agent.py` |
| WorkerAgent | 子任务级（执行完销毁） | 使用工具执行具体子任务，更新 DB 状态 | ❌ 不持久化 | `agents/worker_agent.py` |
| SubAgent | 同 WorkerAgent（基类） | 轻量级执行 Agent，不更新 DB 状态 | ❌ 不持久化 | `agents/sub_agent.py` |

### 3.4 Agent 继承关系

```
BaseAgent (抽象基类)
    │
    ├── ResidentAgent (持久化到 DB)
    │
    └── SubAgent (轻量级，不持久化)
          │
          └── WorkerAgent (继承 SubAgent，增加 DB 状态更新)
```

---

## 4. 目录结构

```
longclaw/
├── .env                              # 环境配置文件
├── backend/
│   ├── main.py                       # FastAPI 入口 + lifespan 管理
│   ├── config.py                     # Settings (pydantic-settings)
│   ├── database.py                   # DatabaseManager (SQLAlchemy async)
│   ├── migrate.py                    # 数据库迁移脚本
│   │
│   ├── agents/                       # Agent 实现
│   │   ├── __init__.py
│   │   ├── base_agent.py             # BaseAgent 抽象基类
│   │   ├── resident_agent.py         # ResidentAgent（常驻）
│   │   ├── owner_agent.py            # OwnerAgent（任务调度）
│   │   ├── worker_agent.py           # WorkerAgent（执行子任务）
│   │   └── sub_agent.py              # SubAgent（轻量执行）
│   │
│   ├── api/                          # REST API 路由
│   │   ├── __init__.py               # API Router 汇总
│   │   ├── chat.py                   # 聊天 API + 初始化引导
│   │   ├── tasks.py                  # 任务管理 API
│   │   ├── agents.py                 # Agent 管理 API
│   │   ├── channels.py               # 频道管理 API
│   │   ├── messages.py               # 消息查询 API
│   │   ├── model_config.py           # LLM 模型配置 API
│   │   ├── prompts.py                # Agent Prompt 管理 API
│   │   └── system_config.py          # 系统配置 API
│   │
│   ├── models/                       # SQLAlchemy ORM 模型
│   │   ├── __init__.py
│   │   ├── agent.py                  # Agent ORM (类型、状态、父子关系)
│   │   ├── agent_prompt.py           # AgentPrompt ORM (类型级/实例级)
│   │   ├── channel.py                # Channel ORM (WEB/QQBOT/TELEGRAM/API)
│   │   ├── conversation.py           # Conversation ORM
│   │   ├── message.py                # Message ORM (发送者/接收者类型)
│   │   ├── model_config.py           # ModelConfig ORM (LLM配置)
│   │   ├── subtask.py                # Subtask ORM (状态、结果)
│   │   ├── system_config.py          # SystemConfig ORM (键值对)
│   │   └── task.py                   # Task ORM (状态、计划、摘要)
│   │
│   ├── services/                     # 业务服务层
│   │   ├── __init__.py
│   │   ├── llm_service.py            # LLM 调用（OpenAI compatible）
│   │   ├── tool_service.py           # 工具系统（web_search/web_fetch）
│   │   ├── task_service.py           # 任务 CRUD + Subtask 管理
│   │   ├── agent_service.py          # Agent CRUD
│   │   ├── agent_registry.py         # Agent 内存注册表
│   │   ├── agent_prompt_service.py   # Agent Prompt 管理
│   │   ├── channel_service.py        # Channel CRUD
│   │   ├── config_service.py         # 系统配置（DB 读写 + 缓存）
│   │   ├── message_service.py        # 消息 CRUD + 发布通知
│   │   ├── model_config_service.py   # 模型配置管理
│   │   └── scheduler_service.py      # 调度器（检测未分配Task、不活跃Agent）
│   │
│   ├── channels/                     # 通信频道实现
│   │   ├── __init__.py
│   │   ├── base_channel.py           # Channel 抽象基类
│   │   └── web_channel.py            # Web Channel 实现
│   │
│   ├── middleware/
│   │   └── auth.py                   # API Key 认证中间件
│   │
│   ├── scripts/
│   │   └── init_db.py                # 数据库初始化脚本
│   │
│   └── requirements.txt
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── services/
│       │   └── api.ts                # API 客户端
│       ├── components/
│       │   └── index.ts              # 通用组件
│       ├── types/
│       │   └── index.ts              # TypeScript 类型定义
│       └── pages/
│           ├── index.ts
│           ├── HomePage.tsx          # Dashboard 总览
│           ├── ChatPage.tsx          # 聊天（核心页面）
│           ├── TasksPage.tsx         # 任务列表
│           ├── TaskDetailPage.tsx    # 任务详情（子任务列表）
│           ├── AgentsPage.tsx        # Agent 管理
│           ├── ChannelsPage.tsx      # 频道管理
│           ├── ModelConfigPage.tsx   # LLM 模型配置
│           ├── PromptConfigPage.tsx  # Agent Prompt 配置
│           ├── SystemConfigPage.tsx  # 系统参数配置
│           └── LoginPage.tsx         # API Key 登录
│
├── scripts/
│   └── init_db.py                    # 顶层初始化脚本入口
│
└── docs/
    └── PROJECT_OVERVIEW.md           # 本文档
```

---

## 5. 数据库设计

### 5.1 表一览

| 表名 | 用途 | 主要字段 |
|------|------|---------|
| `agents` | Agent 实例 | id, agent_type, name, status, parent_agent_id, task_id |
| `channels` | 通信频道 | id, channel_type, resident_agent_id, is_active |
| `conversations` | 对话 | id, task_id, agent_a_id, agent_b_id, channel_id |
| `messages` | 消息记录 | id, sender_type, sender_id, receiver_type, receiver_id, content |
| `tasks` | 任务 | id, title, status, owner_agent_id, plan, summary |
| `subtasks` | 子任务 | id, task_id, title, status, worker_agent_id, result |
| `system_configs` | 系统配置 | config_key, config_value, description |
| `model_configs` | LLM 模型配置 | id, default_provider, providers (JSON) |
| `agent_prompts` | Agent 提示词 | id, agent_type, agent_id, system_prompt |

### 5.2 核心表结构

#### agents 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| agent_type | ENUM | RESIDENT / OWNER / WORKER / SUB |
| name | VARCHAR(100) | Agent 名称 |
| personality | TEXT | 性格描述 |
| status | ENUM | IDLE / RUNNING / PAUSED / TERMINATED / ERROR |
| error_message | TEXT | 错误信息 |
| parent_agent_id | VARCHAR(36) FK | 父 Agent ID |
| task_id | VARCHAR(36) FK | 关联任务 ID |
| model_config | JSON | LLM 配置（别名 llm_config） |
| system_prompt | TEXT | 系统提示词 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |
| terminated_at | DATETIME | 终止时间 |

#### tasks 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| title | VARCHAR(255) | 任务标题 |
| description | TEXT | 任务描述 |
| status | ENUM | PLANNING / RUNNING / PAUSED / COMPLETED / TERMINATED / ERROR |
| owner_agent_id | VARCHAR(36) FK | 绑定的 OwnerAgent |
| channel_id | VARCHAR(36) FK | 来源频道 |
| original_message | TEXT | 原始用户消息 |
| plan | JSON | OwnerAgent 生成的执行计划 |
| summary | TEXT | 执行结果摘要 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |
| completed_at | DATETIME | 完成时间 |
| terminated_at | DATETIME | 终止时间 |

#### subtasks 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| task_id | VARCHAR(36) FK | 所属任务 |
| parent_subtask_id | VARCHAR(36) FK | 父子任务（预留） |
| title | VARCHAR(255) | 子任务标题 |
| description | TEXT | 子任务描述 |
| status | ENUM | PENDING / RUNNING / COMPLETED / FAILED / SKIPPED |
| worker_agent_id | VARCHAR(36) FK | 执行的 WorkerAgent |
| summary | TEXT | 执行摘要 |
| result | JSON | 执行结果 |
| order_index | INT | 执行顺序 |
| created_at | DATETIME | 创建时间 |
| completed_at | DATETIME | 完成时间 |

#### messages 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| conversation_id | VARCHAR(36) FK | 所属对话 |
| sender_type | ENUM | CHANNEL / RESIDENT / OWNER / WORKER / SYSTEM |
| sender_id | VARCHAR(36) | 发送者 ID |
| receiver_type | ENUM | CHANNEL / RESIDENT / OWNER / WORKER / USER |
| receiver_id | VARCHAR(36) | 接收者 ID |
| message_type | ENUM | TEXT / TASK / REPORT / ERROR / SYSTEM |
| content | TEXT | 消息内容 |
| metadata | JSON | 元数据 |
| task_id | VARCHAR(36) FK | 关联任务 |
| subtask_id | VARCHAR(36) FK | 关联子任务 |
| created_at | DATETIME | 创建时间 |

#### channels 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| channel_type | ENUM | QQBOT / TELEGRAM / WEB / API |
| config | JSON | 频道配置 |
| resident_agent_id | VARCHAR(36) FK | 绑定的常驻 Agent |
| is_active | BOOLEAN | 是否激活 |
| created_at | DATETIME | 创建时间 |

#### system_configs 表

| 字段 | 类型 | 说明 |
|------|------|------|
| config_key | VARCHAR(100) PK | 配置键 |
| config_value | TEXT | 配置值 |
| description | VARCHAR(500) | 配置说明 |
| updated_at | DATETIME | 更新时间 |

#### agent_prompts 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| agent_type | ENUM | RESIDENT / OWNER / WORKER / SUB（类型级） |
| agent_id | VARCHAR(36) FK | Agent ID（实例级） |
| system_prompt | TEXT | 系统提示词 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

#### model_configs 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | VARCHAR(36) PK | UUID |
| config_type | VARCHAR(50) | 配置类型（默认 default） |
| default_provider | VARCHAR(100) | 默认 Provider |
| providers | JSON | Provider 列表 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

### 5.3 表关系图

```
agents ──┬──< owned_tasks (Task.owner_agent_id)
         │
         └──< children (Agent.parent_agent_id)

tasks ───┬──< subtasks
         │
         ├──< conversations
         │
         └──< assigned_agents (Agent.task_id)

channels ───< tasks
           └── resident_agent (Agent)

messages ─── conversation
          └── task
          └── subtask

agent_prompts ─── agent (可选，实例级覆盖)
```

---

## 6. 全部 API 接口清单

**认证方式**：所有 API 需要在 Header 中携带 `X-API-Key: longclaw_admin_2026`

### 6.1 Chat API (`/api/chat`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| POST | `/api/chat/send` | 发送消息 | `{channel_id, content}` |
| GET | `/api/chat/messages/{channel_id}` | 获取聊天历史 | `?limit=50&offset=0` |
| GET | `/api/chat/web-channel` | 获取/创建默认 Web Channel | - |
| GET | `/api/chat/init/status` | 检查系统是否已初始化 | - |
| POST | `/api/chat/init` | 执行系统初始化（清空数据） | - |

**Send Response:**
```json
{
  "message_id": "uuid",
  "reply": "Agent 回复内容",
  "created_at": "2026-03-24T10:00:00"
}
```

### 6.2 Tasks API (`/api/tasks`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/tasks` | 任务列表 | `?status=running&channel_id=xxx&limit=20&offset=0` |
| GET | `/api/tasks/{id}` | 任务详情（含子任务） | - |
| POST | `/api/tasks` | 创建任务 | `{title, description?, channel_id?, original_message?}` |
| PATCH | `/api/tasks/{id}` | 更新任务 | `{title?, status?, plan?, summary?}` |
| POST | `/api/tasks/{id}/terminate` | 终止任务 | - |
| GET | `/api/tasks/{id}/subtasks` | 获取子任务列表 | - |
| GET | `/api/tasks/subtasks/{subtask_id}` | 获取子任务详情 | - |

### 6.3 Agents API (`/api/agents`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/agents` | Agent 列表 | `?agent_type=resident&status=running&limit=20&offset=0` |
| GET | `/api/agents/{id}` | Agent 详情 | - |
| GET | `/api/agents/{id}/messages` | Agent 消息历史 | `?limit=50` |
| GET | `/api/agents/{id}/summary` | Agent 摘要 | - |

### 6.4 Channels API (`/api/channels`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/channels` | 频道列表 | `?channel_type=web&is_active=true` |
| POST | `/api/channels` | 创建频道 | `{channel_type, resident_agent_id?, config?}` |
| PUT | `/api/channels/{id}` | 更新频道 | `{resident_agent_id?, config?, is_active?}` |
| DELETE | `/api/channels/{id}` | 删除频道 | - |

### 6.5 Messages API (`/api/messages`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/messages` | 消息列表 | `?conversation_id=xxx&task_id=xxx&limit=50` |
| GET | `/api/messages/{id}` | 消息详情 | - |

### 6.6 System Config API (`/api/system-config`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/system-config` | 获取所有配置 | - |
| GET | `/api/system-config/{key}` | 获取单个配置 | - |
| PUT | `/api/system-config/{key}` | 更新配置 | `{value}` |
| POST | `/api/system-config/reset` | 重置为默认值 | - |

### 6.7 Model Config API (`/api/model-config`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/model-config` | 获取 LLM 模型配置 | - |
| PUT | `/api/model-config` | 更新 LLM 模型配置 | `{default_provider, providers[]}` |
| POST | `/api/model-config/refresh` | 刷新模型列表 | - |

### 6.8 Prompts API (`/api/prompts`)

| 方法 | 路径 | 说明 | 请求体/参数 |
|------|------|------|------------|
| GET | `/api/prompts` | 获取所有 Prompt | - |
| PUT | `/api/prompts/type/{type}` | 更新类型级 Prompt | `{system_prompt}` |
| PUT | `/api/prompts/agent/{id}` | 更新实例级 Prompt | `{system_prompt}` |

### 6.9 其他端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查 |
| GET | `/api/verify` | 验证 API Key |

---

## 7. 核心配置

### 7.1 环境变量 (.env)

```env
# 服务器配置
HOST=0.0.0.0
PORT=8001
DEBUG=true

# 数据库 (MariaDB/MySQL)
DB_HOST=localhost
DB_PORT=3306
DB_NAME=longclaw
DB_USER=longclaw
DB_PASSWORD=longclaw123

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# API 认证
API_KEY=longclaw_admin_2026

# LLM 配置
LLM_DEFAULT_PROVIDER=openai

# OpenAI-compatible API
OPENAI_API_KEY=your_api_key
OPENAI_BASE_URL=http://127.0.0.1:3721/v1
OPENAI_MODEL=Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf

# DeepSeek (可选)
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### 7.2 System Config（Web Dashboard 可配）

这些配置存储在 `system_configs` 表中，可在前端 SystemConfigPage 修改：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `llm_connect_timeout` | 30 | LLM API 连接超时（秒） |
| `llm_request_timeout` | 300 | LLM API 请求超时（秒） |
| `owner_task_timeout` | 600 | Owner Agent 总超时（秒） |
| `resident_chat_timeout` | 600 | Resident Agent 聊天回复超时（秒） |
| `scheduler_agent_timeout` | 300 | Agent 不活跃判定阈值（秒） |
| `scheduler_check_interval` | 1 | Scheduler 检查间隔（秒） |
| `tool_connect_timeout` | 10 | Tool 连接超时（秒） |
| `tool_http_timeout` | 30 | Tool HTTP 超时（秒） |
| `tool_max_rounds` | 6 | 单次任务最大工具调用轮数 |
| `worker_subtask_timeout` | 180 | Worker 单个子任务超时（秒） |

### 7.3 Agent Prompt 管理

Prompt 支持两级配置：

1. **类型级 Prompt**：RESIDENT / OWNER / WORKER / SUB 四种类型，所有同类型 Agent 共享
2. **实例级 Prompt**：可以为单个 Agent 实例覆盖默认 Prompt

**优先级**：实例级 > 类型级 > 代码默认

**获取逻辑**（`agent_prompt_service.py`）：
```python
async def get_agent_prompt(session, agent_id, agent_type):
    # 1. 先查实例级覆盖
    instance_prompt = await get_instance_prompt(session, agent_id)
    if instance_prompt:
        return instance_prompt
    # 2. 再查类型级默认
    return await get_type_prompt(session, agent_type)
```

### 7.4 默认 System Prompt 示例

**ResidentAgent (老六)**:
```
你叫老六，是一个靠谱的AI助手，性格有点皮。直接用中文回复。

## 时间认知
- 系统消息中包含当前日期和时间...

## 工作流程
当用户需要搜索信息、查询资料时：
1. 分析任务是否涉及时间敏感信息
2. 使用 web_search 工具搜索相关信息
3. 根据搜索结果，使用 web_fetch 获取详细内容
4. 整合信息，给用户一个完整、有帮助的回答
...
```

**OwnerAgent**:
```
你是一个任务调度专家，负责分析用户任务并拆解为可并行执行的子任务。

## 核心原则
### 1. 先评估信息缺口
### 2. 最大化并行化
### 3. 子任务描述要具体明确

## 输出格式
```json
{
  "analysis": "任务分析说明",
  "subtasks": [{"id": "1", "description": "...", "tools_needed": ["web_search"]}]
}
```
...
```

---

## 8. 工具系统设计

### 8.1 架构概述

`tool_service.py` 提供统一的工具管理接口：

```
ToolService
├── web_search(query) → 搜索互联网
│   ├── 搜索引擎顺序：百度 → Bing → DuckDuckGo Lite → Google
│   └── 通过 agent-browser CLI 执行
├── web_fetch(url) → 获取网页内容
│   └── 通过 agent-browser CLI 执行
└── register_tool() → 注册自定义工具
```

### 8.2 工具定义格式

```python
@dataclass
class ToolDefinition:
    name: str                    # 工具名称
    description: str             # 工具描述
    parameters: dict[str, Any]   # JSON Schema 参数定义
    function: Callable           # 执行函数

@dataclass
class ToolResult:
    success: bool
    content: str
    error: str | None
    metadata: dict[str, Any]
```

### 8.3 web_search 实现

**搜索引擎优先级**：百度 → Bing → DuckDuckGo Lite → Google

**执行流程**：
```python
async def _web_search(self, query: str) -> ToolResult:
    # 1. 构建各搜索引擎 URL
    engines = [
        {"name": "百度", "url": f"https://www.baidu.com/s?wd={quote_plus(query)}"},
        {"name": "Bing", "url": f"https://www.bing.com/search?q={quote_plus(query)}"},
        ...
    ]

    # 2. 依次尝试每个引擎
    for engine in engines:
        success, output = await self._run_agent_browser(
            session_name=f"search_{engine['name'].lower()}",
            url=engine["url"],
            timeout=15.0
        )

        # 3. 解析 accessibility tree 输出
        results = self._parse_snapshot_for_search(output)
        if results:
            return self._format_search_results(query, results, engine["name"])

    # 4. 所有引擎都失败
    return ToolResult(success=False, error="所有搜索引擎都失败")
```

**输出格式**：
```
搜索 '比特币价格' 找到 5 个结果 (via Bing):
1. 比特币实时价格 - 币安
   URL: https://www.binance.com/...
   摘要: 比特币当前价格 $67,234.50，24小时涨幅 2.3%
2. ...
```

### 8.4 web_fetch 实现

```python
async def _web_fetch(self, url: str) -> ToolResult:
    # 1. 使用 agent-browser 打开页面并获取 snapshot
    success, output = await self._run_agent_browser(
        session_name=f"fetch_{hashlib.md5(url.encode()).hexdigest()[:8]}",
        url=url,
        timeout=30.0
    )

    # 2. 解析 accessibility tree 提取文本内容
    text = self._parse_snapshot_for_content(output)

    # 3. 截断超长内容
    if len(text) > 8000:
        text = text[:8000] + "\n... (内容已截断)"

    return ToolResult(success=True, content=text, metadata={"url": url, "content_length": len(text)})
```

### 8.5 搜索防滥用机制

**连续搜索计数器**（在 `sub_agent.py` 中实现）：

```python
consecutive_search_count = 0
MAX_CONSECUTIVE_SEARCHES = 3

# 在工具调用循环中
if has_web_search:
    consecutive_search_count += 1
    if consecutive_search_count >= MAX_CONSECUTIVE_SEARCHES:
        # 强制停止，注入提示消息
        self._execution_messages.append(ChatMessage(
            role="tool",
            content="已达到最大连续搜索次数限制（3次）。请根据已有的搜索结果整理回答。",
            tool_call_id=tool_call.id
        ))
else:
    # 其他工具调用重置计数器
    consecutive_search_count = 0
```

**工具调用轮数限制**：
- 默认最大 6 轮（可通过 `tool_max_rounds` 配置）
- 每轮包含一次 LLM 调用 + 可能的多次工具调用

---

## 9. 安装部署完整流程

### 9.1 前置要求

- Python 3.12+
- Node.js 18+
- MariaDB / MySQL
- Redis
- agent-browser CLI

### 9.2 安装 agent-browser CLI

```bash
npm install -g agent-browser
agent-browser install  # 安装 Playwright 浏览器
```

### 9.3 后端安装与配置

```bash
# 1. 进入项目目录
cd longclaw

# 2. 创建 Python 虚拟环境
python3 -m venv backend/venv
source backend/venv/bin/activate

# 3. 安装依赖
pip install -r backend/requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入数据库密码、LLM API Key 等
```

### 9.4 数据库初始化

```bash
# 方式一：使用迁移脚本
cd backend
python3 -m migrate

# 方式二：使用初始化脚本（会清空数据）
echo "yes" | PYTHONPATH=$(pwd) python3 scripts/init_db.py
```

### 9.5 前端安装

```bash
cd longclaw/frontend
npm install
```

### 9.6 启动服务

**启动后端**：
```bash
cd longclaw
source backend/venv/bin/activate
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001

# 或使用 reload 模式开发
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload
```

**启动前端**：
```bash
cd longclaw/frontend
npm run dev -- --host 0.0.0.0
```

### 9.7 访问服务

- 前端 Dashboard: http://localhost:5173
- API Key 登录: 使用 `.env` 中的 `API_KEY`（默认 `longclaw_admin_2026`）
- API 文档: http://localhost:8001/docs

### 9.8 数据库重置

```bash
cd longclaw
echo "yes" | PYTHONPATH=$(pwd) python3 backend/scripts/init_db.py

# 重启后端让内存中的 Agent 更新
kill $(pgrep -f "uvicorn backend.main")
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8001
```

---

## 10. 前端页面说明

### 10.1 页面列表

| 页面 | 路由 | 文件 | 功能 |
|------|------|------|------|
| 登录页 | `/login` | `LoginPage.tsx` | API Key 认证 |
| Dashboard | `/` | `HomePage.tsx` | 统计概览、最近任务/Agent |
| 聊天 | `/chat` | `ChatPage.tsx` | 与 Resident Agent 对话 |
| 任务列表 | `/tasks` | `TasksPage.tsx` | 查看所有任务 |
| 任务详情 | `/tasks/:id` | `TaskDetailPage.tsx` | 查看子任务 |
| Agent 管理 | `/agents` | `AgentsPage.tsx` | 查看所有 Agent |
| 频道管理 | `/channels` | `ChannelsPage.tsx` | 管理通信频道 |
| 模型配置 | `/models` | `ModelConfigPage.tsx` | 配置 LLM Provider |
| Prompt 配置 | `/prompts` | `PromptConfigPage.tsx` | 编辑 Agent Prompt |
| 系统配置 | `/system` | `SystemConfigPage.tsx` | 调整系统参数 |

### 10.2 ChatPage 核心逻辑

```tsx
// 聊天页面主要功能：
// 1. 自动检查系统初始化状态
// 2. 获取/创建 Web Channel
// 3. 2秒轮询获取新消息
// 4. 发送消息并等待回复（最长 10 分钟超时）

// 发送消息流程
const handleSend = async () => {
  // 1. 添加临时用户消息（立即显示）
  setMessages(prev => [...prev, tempUserMsg]);

  // 2. 发送 POST 请求
  const response = await fetch('/api/chat/send', {
    method: 'POST',
    body: JSON.stringify({ channel_id, content }),
    signal: controller.signal, // 10 分钟超时
  });

  // 3. 收到回复后更新消息列表
  setMessages(prev => [...prev, userMsg, replyMsg]);
};
```

### 10.3 API 客户端 (`services/api.ts`)

```typescript
class ApiClient {
  private apiKey: string | null = null;

  setApiKey(key: string | null) { this.apiKey = key; }
  getApiKey() { return this.apiKey; }

  // 统一请求方法，自动添加 X-API-Key header
  private async request<T>(endpoint: string, options = {}): Promise<T> {
    const response = await fetch(`/api${endpoint}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': this.apiKey || '',
        ...options.headers,
      },
    });
    // 处理 401 自动登出
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent('auth:unauthorized'));
    }
    return response.json();
  }
}
```

---

## 11. 已知限制和改进方向

### 11.1 当前限制

| 限制 | 说明 | 影响 |
|------|------|------|
| 模型遵循度不足 | 本地 Qwen3.5 量化模型对复杂 prompt 指令遵循度不够 | 不主动 web_fetch 详情页，倾向于重复搜索 |
| 搜索速度慢 | agent-browser 每次需要启动浏览器渲染页面 | 单次搜索 5-20 秒 |
| 仅 Web Channel | 暂无 Telegram/Discord/QQ Bot 等接入 | 只能通过 Web 界面使用 |
| 无 WebSocket | 前端用 2 秒 polling 获取新消息 | 实时性差，资源浪费 |
| 单机部署 | 无分布式支持，Agent 都在同一进程 | 无法水平扩展 |
| 无流式输出 | LLM 回复一次性返回 | 用户需等待完整生成 |
| 工具仅搜索 | 目前只有 web_search / web_fetch | 无代码执行、文件操作等 |
| 无用户系统 | 只有一个 API Key 认证 | 无多用户/权限管理 |
| 无 Agent 记忆 | 对话历史限制在内存中（最多 20 条） | 无法跨会话记忆 |

### 11.2 改进方向

| 改进项 | 优先级 | 说明 |
|--------|--------|------|
| 流式输出 (SSE) | 高 | 提升 LLM 回复的前端体验 |
| WebSocket | 高 | 替代 polling，实现实时通信 |
| 更多 Channel | 中 | 实现 Telegram Bot、QQ Bot |
| 更多工具 | 中 | shell_command、文件操作、代码执行 |
| Agent 记忆系统 | 中 | 跨会话记忆，向量数据库存储 |
| 任务模板 | 低 | 常见任务预设，提高效率 |
| Docker 化部署 | 低 | 简化部署流程 |
| 多 LLM Provider | 低 | 增强模型切换灵活性 |
| Agent 评价系统 | 低 | 对执行结果打分优化 |
| 用户系统 | 低 | 多用户、权限管理 |

---

## 附录

### A. 错误处理

**LLM 连接错误**：
```
LLM 连接失败
连接地址: http://127.0.0.1:3721/v1/chat/completions
错误原因: [具体错误]

请检查 Models 配置页面，确保 API 地址和密钥正确。
```

**任务执行超时**：
```
任务执行超时（600秒）。请简化任务或稍后重试。
```

### B. 日志级别

- `DEBUG=true`：详细日志，包括 SQL 语句
- `DEBUG=false`：仅 INFO 及以上级别

### C. 性能参数

| 参数 | 默认值 | 调优建议 |
|------|--------|---------|
| DB 连接池大小 | 10 | 根据并发量调整 |
| DB 最大溢出连接 | 20 | 根据并发量调整 |
| DB 连接回收时间 | 3600s | 防止连接失效 |
| Redis DB | 0 | 可配置多个实例 |

---

*文档基于实际代码内容编写，最后更新时间：2026-03-24*
