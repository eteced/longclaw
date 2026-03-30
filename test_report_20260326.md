# LongClaw 集成测试报告 - 2026-03-26

## 测试任务
要求编写一个能批量转换wav到ogg的C++项目，转换代码可以参考开源项目，注意不允许直接使用某个lib，而应该是了解转换算法后直接重新实现一个。

---

## 🔴 严重问题（导致核心功能不可用）

### BUG-1: subtasks 表缺少 `updated_at` 列 → 所有新任务立即 error
- **现象**: 通过 Chat 发送任务后，任务瞬间变为 error 状态，进度 0%
- **根因**: SQLAlchemy 模型定义了 `updated_at` 字段，但数据库 `subtasks` 表中不存在该列
- **错误日志**:
  ```
  pymysql.err.OperationalError: (1054, "Unknown column 'subtasks.updated_at' in 'RETURNING'")
  INSERT INTO subtasks (...) VALUES (...) RETURNING subtasks.updated_at
  ```
- **影响**: **所有新任务都无法执行**，OwnerAgent 在创建第一个子任务时就崩了
- **复现**: 发送任何新任务即可 100% 复现
- **历史任务**: 之前完成的两个任务 (owner_agent_id=null) 可能是在不同数据库结构下运行的

### BUG-2: 任务详情 API 返回 500 Internal Server Error
- **现象**: 在 Tasks 列表页点击 "View details" 显示 "Failed to load task details"
- **相关**: 调用 `GET /api/tasks/{id}` 和 `GET /api/tasks/{id}/subtasks` 都返回空响应或 500
- **可能关联**: 与 BUG-1 的数据库列缺失问题相关

### BUG-3: 任务详情 API 返回空响应
- **现象**: `GET /api/tasks/{id}` 返回空 body（不是 404，而是 200 + 空）
- **与 BUG-2 合并**: 详情接口完全不工作

---

## 🟡 中等问题（影响体验但不阻塞）

### BUG-4: Chat 页面 WebSocket 持续显示 "重连中..."
- **现象**: 进入 Chat 页面后一直显示 "重连中..."，但聊天功能（发送/接收消息）实际是正常的
- **影响**: 用户会误以为连接有问题
- **注意**: 消息发送和接收是工作的（能看到老六的回复），说明 WebSocket 实际已连接但状态判断有误

### BUG-5: Dashboard 的 Active Agents 数量显示不准确
- **现象**: Dashboard 显示 "Active Agents: 0"，但实际上老六 agent 状态应该是 running
- **原因**: 可能是 agent 的 terminated_at 字段不为 null（老六曾经被 terminate 过，DB 里 terminated_at = "2026-03-26T01:22:55"），导致统计逻辑排除了它
- **关联**: 老六在 Agents 页面显示为 "error" 状态

### BUG-6: 老六 Agent 状态为 error（但实际在运行）
- **现象**: Agents 页面显示老六状态为 "error"，但实际上它能正常响应聊天消息
- **根因**: DB 中 `terminated_at` 有值，且 `error_message` 可能为 null。后端加载已有 agent 时没有正确重置状态
- **日志佐证**: 后端启动时 `Updated agent status to running`，但前端获取到的状态仍是 error

### BUG-7: 所有子任务均超时（历史问题）
- **现象**: 之前完成的两个任务中，所有子任务都显示超时，没有实际产出代码
- **影响**: Agent 回复的是"蓝图"和"建议"，而不是实际可运行的代码
- **设计疑问**: 子任务超时时间是否设置得太短？或者子任务执行机制本身有问题？

---

## 🟢 轻微问题 / 改进建议

### UI-1: 任务列表中相同标题难以区分
- 两个任务标题完全一样（都是 wav-to-ogg 转换），列表中无法快速区分
- 建议：增加任务 ID 的缩写显示，或者创建时间更醒目

### UI-2: 进度列所有任务都显示 0%
- 即使状态为 "completed"，进度也显示 0%
- 进度追踪似乎没有正确更新

### UI-3: 已完成任务的 Owner Agent 显示 "-"
- 之前完成的两个任务 owner_agent_id 为 null
- 新任务（error 的）有 owner_agent_id
- 说明之前可能没有 owner agent 的概念？现在新增了但历史数据不兼容

---

## 设计预期检查

### ✅ 符合预期的部分
- 任务创建流程：Chat 发送 → 任务创建 → 触发 Agent 规划子任务
- Agent 规划能力：老六能将任务拆解为合理的子任务（WAV解析、Vorbis编码、OGG封装、CMake构建等）
- 前端导航结构：Dashboard/Tasks/Agents/Channels/Models/Prompts/System/Chat
- 任务状态筛选：支持按状态过滤
- 基础 API 框架：健康检查、任务列表、Agent 列表等 API 均正常

### ❌ 不符合预期的部分
- **核心流程完全不可用**：任何新任务都会因为数据库字段缺失而失败
- WebSocket 状态不准确（显示重连但实际工作）
- Agent 状态不准确（显示 error 但实际运行）
- 子任务执行全部超时，没有产出实际代码
- 任务详情页完全不可用

---

---

## 补充测试（初始化后重测）

按照 INTEGRATION_TEST_GUIDE.md 重新执行了初始化流程：
1. `PYTHONPATH=. python3 scripts/init_db.py --force`
2. 重启后端

### 初始化脚本自身问题
- 初始化脚本在验证阶段报错：`AttributeError: type object 'SystemConfig' has no attribute 'id'`（脚本退出码 1）
- 但 agent 和 channel 实际上创建成功了
- 配置项创建数量为 0（可能因为系统配置表名不匹配：脚本用 `system_config`，但后端模型可能用 `system_configs`）

### 重新测试结果
- ✅ 老六 Agent 状态正确显示 running
- ✅ Web Channel 正常创建
- ✅ Health check 通过
- ❌ **发送新任务后仍然立即 error**（同样的 subtasks.updated_at 错误）
- 根因确认：**初始化脚本只清空数据和插入初始数据，不会修改表结构**。SQLAlchemy ORM 的 subtask 模型有 updated_at 字段，但数据库表中没有这个列。需要手动 ALTER TABLE 或在初始化脚本中加 migration。

---

## 测试结论

**当前项目处于不可用状态**。最关键的 BUG-1（数据库字段缺失）导致所有新任务创建后立即失败。建议 CC 优先修复此问题，然后再进行功能测试。

**修复优先级**:
1. 🔴 BUG-1: 数据库 schema 同步 — subtasks 表缺少 updated_at 列（ALTER TABLE 或 migration）
2. 🔴 初始化脚本: 修复 SystemConfig.id 报错 + 配置项未创建问题
3. 🔴 BUG-2/3: 修复任务详情 API
4. 🟡 BUG-5/6: 修复 Agent 状态加载逻辑
5. 🟡 BUG-4: 修复 WebSocket 状态显示
6. 🟡 BUG-7: 调查子任务超时原因，考虑增加超时时间或优化执行机制
