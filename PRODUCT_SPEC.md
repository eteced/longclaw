# LongClaw - Multi-Agent Task Server 产品设计文档

## 1. 概述

LongClaw 是一个多 Agent 任务管理系统，灵感来自 OpenClaw 但专注于任务驱动的多 Agent 协作。

### 核心理念
- **Channel → Resident Agent → Task Owner Agent → Worker Agents**
- 常驻 Agent 是用户的第一接触点，拥有不同性格
- 任务 Owner Agent 负责拆解、规划、跟踪
- Worker Agent 做简单具体的任务，跑完就销毁
- 所有通信有记录，支持断线重连

### 技术选型
- **后端**: Python (FastAPI) - 异步友好，AI生态好
- **数据库**: MariaDB - 持久化存储
- **前端**: React + TailwindCSS - Dashboard
- **LLM调用**: OpenAI API 兼容接口（支持多provider）
- **消息队列**: Redis（轻量，用于任务分发和状态同步）
- **进程管理**: asyncio + subprocess

---

## 2. 架构设计

### 2.1 Agent 层级

```
Channel (QQ/Telegram/Web/API)
    │
    ▼
┌─────────────┐
│ Resident    │  ← 常驻，有性格，处理闲聊+任务分发
│ Agent       │
└──────┬──────┘
       │ 任务来了，创建
       ▼
┌─────────────┐
│ Task Owner  │  ← 任务负责人，拆解/规划/跟踪
│ Agent       │
└──────┬──────┘
       │ 拆解为子任务，创建
       ▼
┌─────────────┐
│ Worker      │  ← 具体干活的，简单任务，跑完销毁
│ Agent(s)    │
└─────────────┘
```

### 2.2 核心组件

```
longclaw/
├── backend/
│   ├── main.py                  # FastAPI 入口
│   ├── config.py                # 配置管理
│   ├── database.py              # MariaDB 连接
│   ├── models/                  # SQLAlchemy 模型
│   │   ├── agent.py             # Agent 表
│   │   ├── task.py              # Task 表
│   │   ├── message.py           # 消息记录表
│   │   └── channel.py           # Channel 配置表
│   ├── services/
│   │   ├── agent_service.py     # Agent 生命周期管理
│   │   ├── task_service.py      # Task 创建/更新/终止
│   │   ├── llm_service.py       # LLM 调用封装
│   │   ├── channel_service.py   # Channel 消息收发
│   │   └── scheduler_service.py # 轮询和自动化
│   ├── agents/
│   │   ├── base_agent.py        # Agent 基类
│   │   ├── resident_agent.py    # 常驻 Agent
│   │   ├── owner_agent.py       # 任务 Owner Agent
│   │   └── worker_agent.py      # Worker Agent
│   ├── channels/
│   │   ├── base_channel.py      # Channel 基类
│   │   ├── qqbot_channel.py     # QQ Channel
│   │   └── web_channel.py       # Web Dashboard Channel
│   └── api/                     # REST API
│       ├── agents.py
│       ├── tasks.py
│       ├── messages.py
│       └── channels.py
├── frontend/                    # Dashboard
│   └── ...
├── docker-compose.yml
├── Dockerfile
└── README.md
```

---

## 3. 数据模型

### 3.1 agents 表
```sql
CREATE TABLE agents (
    id VARCHAR(36) PRIMARY KEY,          # UUID
    agent_type ENUM('resident', 'owner', 'worker'),
    name VARCHAR(100),                   # Agent 名称
    personality TEXT,                    # 人设/性格描述
    status ENUM('idle', 'running', 'paused', 'terminated', 'error'),
    parent_agent_id VARCHAR(36),         # 父 Agent ID (owner→resident, worker→owner)
    task_id VARCHAR(36),                 # 所属任务 ID
    model_config JSON,                   # 使用的模型配置
    system_prompt TEXT,                  # 系统提示词
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    terminated_at TIMESTAMP NULL
);
```

### 3.2 tasks 表
```sql
CREATE TABLE tasks (
    id VARCHAR(36) PRIMARY KEY,
    title VARCHAR(255),
    description TEXT,
    status ENUM('planning', 'running', 'paused', 'completed', 'terminated', 'error'),
    owner_agent_id VARCHAR(36),          # 负责的 Owner Agent
    channel_id VARCHAR(36),
    original_message TEXT,               # 触发任务的原始消息
    plan JSON,                           # 任务计划（结构化）
    summary TEXT,                        # 任务总结（完成后生成）
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    completed_at TIMESTAMP NULL,
    terminated_at TIMESTAMP NULL,
    FOREIGN KEY (owner_agent_id) REFERENCES agents(id),
    FOREIGN KEY (channel_id) REFERENCES channels(id)
);
```

### 3.3 subtasks 表
```sql
CREATE TABLE subtasks (
    id VARCHAR(36) PRIMARY KEY,
    task_id VARCHAR(36),
    parent_subtask_id VARCHAR(36),       # 支持嵌套
    title VARCHAR(255),
    description TEXT,
    status ENUM('pending', 'running', 'completed', 'failed', 'skipped'),
    worker_agent_id VARCHAR(36),
    summary TEXT,                        # 子任务完成总结
    result JSON,                         # 结构化结果
    order_index INT,
    created_at TIMESTAMP,
    completed_at TIMESTAMP NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (worker_agent_id) REFERENCES agents(id)
);
```

### 3.4 messages 表（所有通信记录）
```sql
CREATE TABLE messages (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36),         # 会话 ID
    sender_type ENUM('channel', 'resident', 'owner', 'worker', 'system'),
    sender_id VARCHAR(36),
    receiver_type ENUM('channel', 'resident', 'owner', 'worker', 'user'),
    receiver_id VARCHAR(36),
    message_type ENUM('text', 'task', 'report', 'error', 'system'),
    content TEXT,
    metadata JSON,                       # 附件、引用等
    task_id VARCHAR(36),                 # 关联任务
    subtask_id VARCHAR(36),              # 关联子任务
    created_at TIMESTAMP,
    INDEX idx_conversation (conversation_id),
    INDEX idx_task (task_id),
    INDEX idx_sender (sender_id)
);
```

### 3.5 conversations 表
```sql
CREATE TABLE conversations (
    id VARCHAR(36) PRIMARY KEY,
    task_id VARCHAR(36),
    agent_a_id VARCHAR(36),
    agent_b_id VARCHAR(36),
    channel_id VARCHAR(36),
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    INDEX idx_task (task_id)
);
```

### 3.6 channels 表
```sql
CREATE TABLE channels (
    id VARCHAR(36) PRIMARY KEY,
    channel_type ENUM('qqbot', 'telegram', 'web', 'api'),
    config JSON,                         # Channel 特定配置
    resident_agent_id VARCHAR(36),       # 该 Channel 绑定的常驻 Agent
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP
);
```

---

## 4. Agent 设计

### 4.1 BaseAgent 基类

```python
class BaseAgent:
    id: str
    type: str  # resident/owner/worker
    status: str  # idle/running/paused/terminated
    
    async def send_message(self, to_agent_id, content)
    async def receive_message(self, from_agent_id, content)
    async def think(self, messages) -> str  # 调用 LLM
    async def run(self)  # 主循环
    async def terminate(self)
    async def get_summary(self) -> str  # 生成总结
```

### 4.2 Resident Agent（常驻）

**职责：**
- 接收 Channel 消息
- 闲聊、简单问答直接处理
- 识别任务请求，创建 Task 和 Owner Agent
- 转发 Task Owner 的进度消息给用户
- 处理用户的反馈和修改意见

**人设示例：**
```
你叫老六，是一个靠谱的AI助手，性格有点皮。当用户给你任务时，你会：
1. 确认理解任务
2. 创建任务负责人来跟进
3. 定期向用户汇报进度
```

### 4.3 Task Owner Agent（任务负责人）

**职责：**
- 拆解任务为子任务（调用 LLM 生成结构化计划）
- 为每个子任务创建 Worker Agent
- 监控 Worker 进度
- 汇总结果，生成任务报告
- 遇到阻塞时向 Resident Agent 汇报
- 定期输出进度摘要（用于断线恢复）

**Owner 系统提示词模板：**
```
你是一个任务负责人。你当前的任务是：{task_description}

你的职责：
1. 将任务拆解为具体的、可独立执行的子任务
2. 每个子任务应该简单到只需一个 Worker Agent 就能完成
3. 按顺序或并行派发子任务给 Worker Agent
4. 跟踪每个 Worker 的进度
5. 汇总所有子任务结果，生成最终报告

输出格式：
- 任务计划：JSON 格式的子任务列表
- 进度更新：定期向 Resident Agent 报告
- 最终报告：包含所有子任务结果的汇总

重要：每个子任务必须足够简单，Worker 只需要做一件事。
```

### 4.4 Worker Agent（临时工人）

**职责：**
- 执行具体的单一任务
- 完成后输出 summary
- 支持断线恢复（通过 summary 继续工作）

**Worker 系统提示词模板：**
```
你是一个任务执行者。你的任务是：{subtask_description}

上下文（来自父任务）：
{parent_task_context}

要求：
1. 专注完成这一个具体任务
2. 完成后输出简洁的总结（不超过 200 字）
3. 总结应包含：做了什么、结果如何、遇到的问题

注意：你不需要理解整个项目，只需要完成分配给你的这个子任务。
```

---

## 5. 任务生命周期

### 5.1 流程图

```
用户发送消息
    │
    ▼
Channel 收到消息 → 存入 messages 表
    │
    ▼
Resident Agent 判断：
    ├── 简单问题 → 直接回复（不创建任务）
    └── 复杂任务 → 创建 Task 记录
                    │
                    ▼
              创建 Owner Agent
                    │
                    ▼
              Owner Agent 分析任务
                    │
                    ├── 生成任务计划（LLM 输出 JSON）
                    │   └── 存入 tasks.plan
                    │
                    ▼
              逐个/并行创建 Subtask
                    │
                    ▼
              为每个 Subtask 创建 Worker Agent
                    │
                    ▼
              Worker 执行 → 完成输出 summary
                    │
                    ▼
              Owner 收集结果 → 汇总报告
                    │
                    ▼
              任务完成 → 更新 task.summary
                    │
                    ▼
              Resident 通知用户 → Task 标记 completed
```

### 5.2 断线恢复

每个 Agent 定期（每完成一步操作）将状态写入数据库：
- Owner: 当前执行到哪个子任务、哪些已完成、哪些失败
- Worker: 当前工作进展、中间结果

恢复时：
1. 从数据库加载最近的 summary
2. 继续未完成的子任务
3. 已完成的跳过（用已有的 summary）

### 5.3 任务终止

- Dashboard 上点击"终止任务"
- 释放 Owner Agent 和所有 Worker Agent
- 保留 Task 记录和已完成的 summary
- 状态标记为 `terminated`，可从 summary 重新启动

---

## 6. API 设计

### 6.1 Tasks API
```
GET    /api/tasks                    # 任务列表（支持分页、过滤）
GET    /api/tasks/:id                # 任务详情（含子任务列表）
POST   /api/tasks/:id/terminate      # 终止任务
POST   /api/tasks/:id/resume         # 从 summary 恢复任务
GET    /api/tasks/:id/messages       # 任务相关消息
GET    /api/tasks/:id/timeline       # 任务时间线

Subtasks:
GET    /api/tasks/:id/subtasks
GET    /api/subtasks/:id
```

### 6.2 Agents API
```
GET    /api/agents                   # Agent 列表
GET    /api/agents/:id               # Agent 详情
GET    /api/agents/:id/messages      # Agent 的消息记录
GET    /api/agents/:id/summary       # Agent 的最新 summary
```

### 6.3 Channels API
```
GET    /api/channels                 # Channel 列表
POST   /api/channels                 # 创建 Channel
PUT    /api/channels/:id             # 更新 Channel 配置
```

### 6.4 WebSocket（实时更新）
```
WS     /ws/tasks                     # 任务状态变更推送
WS     /ws/tasks/:id                 # 单个任务实时消息流
WS     /ws/agents                    # Agent 状态变更推送
```

---

## 7. Dashboard 设计

### 7.1 页面结构

```
Dashboard
├── 任务概览（首页）
│   ├── 统计卡片：运行中/已完成/已终止的任务数
│   ├── 活跃 Agent 数量
│   └── 最近活动列表
│
├── 任务列表
│   ├── 筛选：按状态、时间范围、Channel
│   ├── 每个任务卡片：标题、状态、负责人、进度条、时间
│   └── 操作：查看详情、终止、恢复
│
├── 任务详情页
│   ├── 任务信息：标题、描述、状态、时间
│   ├── 任务计划：子任务列表 + 状态
│   ├── 对话记录：按时间线显示所有相关消息
│   ├── Agent 树：任务负责人 → Workers 的层级关系
│   ├── 操作按钮：终止任务
│   └── Summary：任务总结
│
├── Agent 管理
│   ├── 常驻 Agent 列表（配置人设、绑定 Channel）
│   ├── 活跃 Agent 实时状态
│   └── Agent 对话记录
│
└── Channel 管理
    ├── Channel 列表
    ├── 绑定常驻 Agent
    └── 消息日志
```

---

## 8. 调度与轮询机制

### 8.1 Scheduler Service

```python
class SchedulerService:
    """后台定时任务"""
    
    async def tick(self):
        """每秒执行一次"""
        await self.check_pending_tasks()       # 检查待执行的任务
        await self.check_running_agents()      # 检查运行中的 Agent
        await self.check_stale_agents()        # 检查超时的 Agent
        await self.process_message_queue()     # 处理消息队列
        await self.broadcast_updates()         # 推送 WebSocket 更新
```

### 8.2 消息队列

Agent 之间的通信通过数据库消息表 + Redis pub/sub：
1. 发送方写入 messages 表
2. 通过 Redis pub/sub 通知接收方
3. 接收方从数据库读取消息
4. 支持异步和同步两种模式

---

## 9. 分阶段实施计划

### Phase 1: 基础框架（核心）
- [ ] 项目初始化（FastAPI + MariaDB + Redis）
- [ ] 数据模型和数据库 migration
- [ ] Agent 基类和生命周期管理
- [ ] LLM 调用服务
- [ ] 消息系统（数据库存储 + Redis pub/sub）
- [ ] 基础 REST API

### Phase 2: Agent 实现
- [ ] Resident Agent（Web Channel）
- [ ] Task Owner Agent（任务拆解 + 规划）
- [ ] Worker Agent（执行 + summary）
- [ ] Agent 间通信管道

### Phase 3: Dashboard
- [ ] React 前端框架搭建
- [ ] 任务概览页
- [ ] 任务列表页（分页、过滤）
- [ ] 任务详情页（计划、消息、Agent 树）
- [ ] WebSocket 实时更新
- [ ] 终止/恢复任务操作

### Phase 4: Channel 集成
- [ ] QQBot Channel
- [ ] Telegram Channel
- [ ] API Channel

### Phase 5: 高级功能
- [ ] 断线恢复
- [ ] 任务暂停/恢复
- [ ] Agent 性格配置 UI
- [ ] 任务模板
- [ ] 权限管理

---

## 10. 配置示例

```yaml
# longclaw.yaml
server:
  host: 0.0.0.0
  port: 8001

database:
  host: localhost
  port: 3306
  name: longclaw
  user: longclaw
  password: ${DB_PASSWORD}

redis:
  host: localhost
  port: 6379

llm:
  default_provider: openai
  providers:
    openai:
      api_key: ${OPENAI_API_KEY}
      base_url: https://api.openai.com/v1
      model: gpt-4o
    deepseek:
      api_key: ${DEEPSEEK_API_KEY}
      base_url: https://api.deepseek.com/v1
      model: deepseek-chat

channels:
  qqbot:
    enabled: true
    config:
      app_id: ${QQ_APP_ID}
      app_secret: ${QQ_APP_SECRET}

resident_agents:
  - name: "老六"
    personality: "靠谱、有点皮"
    channels: [qqbot, web]
    model: deepseek-chat
```

---

*文档版本: v0.1*
*创建时间: 2026-03-19*
*状态: 设计中*
