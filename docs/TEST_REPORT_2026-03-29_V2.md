# LongClaw 集成测试报告 (2026-03-29 第二轮)

## 测试环境
- 后端: http://localhost:8001 (healthy)
- 前端: http://localhost:5173
- 测试时间: 2026-03-29 11:55 ~ 12:15 (Asia/Shanghai)
- 测试用例: 发送一个编程任务（C++ WAV→OGG 批量转换器），观察完整生命周期

---

## 测试流程概述

1. 访问 Dashboard — ✅ 正常
2. 进入 Chat 页面，发送任务 — ✅ 正常
3. 观察任务创建和拆解 — ✅ 正常（5个子任务）
4. 观察 Worker Agent 并行执行 — ⚠️ LLM 超时导致大量失败
5. 观察 Owner 汇总 — ❌ Owner 未完成汇总
6. 观察 Resident 最终状态 — ❌ Resident 被标记为 error
7. 检查 Tasks/Agents/Console 页面 — 混合结果

---

## ✅ 正常工作的部分

### 1. Dashboard
- 统计卡片正确显示 Running Tasks(0→1)、Active Agents(1)
- Recent Tasks / Recent Agents 链接正常

### 2. Chat 页面
- 消息发送正常，发送后显示"AI 正在思考..."
- 输入框在等待期间正确 disable

### 3. 任务拆解 (Resident → Owner → Workers)
- Resident 正确判断为复杂任务，创建了 Task
- OwnerAgent 正确拆解为 5 个并行子任务：
  - #0: 搜索 WAV/OGG 算法原理
  - #1: 设计 C++ 项目架构
  - #2: 编写 WAV 解析模块
  - #3: 编写 Vorbis 编码核心算法
  - #4: 整合模块并生成完整项目
- 所有子任务都有独立的 WorkerAgent，且 parent_id 正确指向 OwnerAgent

### 4. Task Detail 页面
- Subtasks tab 正确展示 5 个子任务及状态
- Agents tab 正确展示 6 个 Agent 的树形结构（Resident → Owner → Workers）
- Progress 在 detail 页显示 "0/5 (5 running)" — 数字正确（列表页有问题，见下方）

### 5. Agents 页面
- List View 正确显示所有 Agent 类型（Resident、Owner、Worker）
- Tree View 正确展示层级关系
- 每个 Agent 的状态、parent、创建时间都正确

### 6. Console 页面
- 显示 Channel 和 Agent 列表
- 提供"干预"按钮（可向任意 Agent/Channel 发送消息）

---

## 🐛 发现的 BUG

### BUG-1: Tasks 列表页 Progress 列显示 "0/0 0%"
- **严重度**: P1（数据展示错误）
- **现象**: Tasks 列表页的 Progress 列始终显示 "0/0 0%"，即使任务有 5 个子任务
- **对比**: Task Detail 页面正确显示 "0/5 (5 running) 0%"
- **说明**: 上次修复 (BUG-B/BUG-E) 添加了后端 `subtask_stats` 字段，但 Tasks 列表页前端可能没有正确读取该字段。列表页和详情页使用的 API 不同（列表用 `/api/tasks`，详情用 `/api/tasks/{id}`），需要确认列表 API 是否也返回了 subtask_stats

### BUG-2: Resident Agent 被错误标记为 error
- **严重度**: P1（Agent 状态错误）
- **现象**: 任务仍在 running 时，Resident Agent 状态变为 error，但 `error_message` 为 null
- **说明**: 上次修复 (BUG-C) 添加了心跳机制，但仍然复现。可能原因：
  - `resident_heartbeat_interval` (默认60s) 仍然大于实际心跳间隔
  - 或心跳未在 Owner 等待期间正确触发
  - 或 scheduler 的 `_check_agent_health` 在心跳更新前就检查了

### BUG-3: 子任务失败但任务状态仍为 running
- **严重度**: P1（状态不一致）
- **现象**: 5 个子任务中 4 个已完成（但都是错误完成），1 个仍在 running，任务状态保持 running
- **期望**: 当所有子任务完成（无论成功失败）时，Owner 应汇总并更新任务状态
- **根因**: OwnerAgent 在等待 Worker 结果汇总时，LLM 调用也超时了，导致 Owner 卡住

### BUG-4: Subtask 标记为 completed 但实际是错误
- **严重度**: P2（状态语义错误）
- **现象**: 4 个 subtask 的 status 为 "completed"，但 summary 内容是 "LLM 请求超时" 或 "达到最大工具调用次数"
- **期望**: LLM 超时或工具调用超限应该是 "failed" 状态，不是 "completed"
- **说明**: 这是核心改进诉求 20260326 第 2 条的持续问题

### BUG-5: Chat 页面"AI 正在思考"提示消失
- **严重度**: P2（用户体验）
- **现象**: 发送消息后先显示"AI 正在思考..."，但刷新或等待一段时间后，该提示消失，输入框仍 disabled，用户不知道系统在做什么
- **期望**: 在任务执行期间持续显示状态（如"正在执行任务..."、显示关联的 Task 链接等）

### BUG-6: Plan 字段始终为 null
- **严重度**: P2（上次报告未修复）
- **现象**: 任务的 plan 字段始终为 null，即使 OwnerAgent 已经完成了子任务拆解
- **说明**: 上次报告 (BUG-F) 标注为 P2 未修复，本次确认仍然存在

### BUG-7: Task Detail 页 Messages tab 显示 0
- **严重度**: P3（可能正常）
- **现象**: Task Detail 的 Messages tab 显示 "Messages (0)"
- **说明**: Worker → Owner 的消息存在 Agent 层面，但可能没有关联到 task 的 messages。如果设计如此则非 BUG，但从用户角度看，用户期望在任务详情页看到所有相关消息

---

## ⚠️ 需要关注的设计问题

### Design-1: LLM 超时处理不够健壮
- 5 个 Worker 中 3 个因 LLM 超时失败，1 个因工具调用上限失败
- 超时后应该有重试机制，或至少标记 subtask 为 failed 并让 Owner 知道
- 建议: Worker 子任务应有重试机制（至少重试 1-2 次）

### Design-2: Owner 汇总也依赖 LLM
- Owner 在所有 Worker 完成后需要调用 LLM 汇总结果
- 如果此时 LLM 也超时（本次测试的情况），整个任务就卡住了
- 建议: Owner 汇总应该有独立的超时和降级策略（如超时时直接拼接 Worker 结果返回）

### Design-3: 搜索引擎 agent-browser session 被劫持
- 测试过程中，浏览器 session 被搜索引擎的验证码页面劫持
- 这不是 LongClaw 的 BUG，但会影响 Worker 使用 web_search 的成功率
- 建议: 每次搜索使用独立 session（从代码看似乎已经在做），但需确认 session 清理

### Design-4: 核心改进诉求的实现进度
以下核心改进诉求（来自 `核心改进诉求.md`）本次测试中未验证到：
- **流式输出 (SSE)**: 未看到流式输出
- **WebSocket**: 前端有 WebSocket 连接（显示"已连接"），但消息推送效果不明显
- **Reflect 模块**: 未看到 Reflect/监督机制的运作
- **Agent 记忆系统**: 未测试
- **Agent 最大上下文配置 + compact**: 未测试
- **任务完成后 Resident → Owner → Worker 的完整通讯透明展示**: 部分实现（Agents 页面可见层级，但消息审计不够）

---

## 📊 总结

| 类别 | 通过 | 问题 |
|------|------|------|
| 基础页面加载 | ✅ | - |
| 任务创建和拆解 | ✅ | - |
| Agent 调度链路 | ✅ | Resident → Owner → Workers 正确 |
| Agent 状态管理 | ⚠️ | Resident 被错误标为 error (BUG-2) |
| Subtask 状态管理 | ❌ | 失败任务标为 completed (BUG-4) |
| Tasks 列表 Progress | ❌ | 显示 0/0 (BUG-1) |
| Plan 字段 | ❌ | 始终 null (BUG-6) |
| Chat 页面状态提示 | ⚠️ | 提示中途消失 (BUG-5) |
| LLM 超时恢复 | ❌ | 无重试，任务卡死 (Design-1/2) |

---

*报告生成时间: 2026-03-29 12:15*
