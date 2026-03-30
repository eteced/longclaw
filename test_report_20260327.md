# LongClaw 集成测试报告

**测试日期**: 2026-03-27 22:28 ~ 22:50  
**测试方式**: 浏览器 + API（从头体验完整流程）  
**测试任务**: 编写批量转换 WAV 到 OGG 的 C++ 项目（要求自行实现编码算法）

---

## 📋 测试流程

1. 初始化数据库 (`init_db.py --force`) ✅
2. 打开前端 Dashboard ✅
3. 进入 Chat 页面，发送任务消息 ✅
4. 等待任务执行，观察 Agent 调度 ✅
5. 检查各管理页面（Agents, Tasks, Channels, Models, Prompts, System）
6. 检查 API 响应
7. 测试 LLM Speed Test

---

## 🐛 发现的 Bug 和问题

### 🔴 严重问题（影响核心功能）

#### 1. Chat 页面 WebSocket 始终显示"重连中..."
- **现象**: Chat 页面右上角始终显示 ⚠️"重连中..."，从未变成已连接状态
- **影响**: 用户无法确认连接状态；根据设计文档，应该有 WebSocket 实时通信，但看起来 WebSocket 可能未正常工作
- **位置**: Chat 页面标题右侧

#### 2. Agent 只显示了 Resident，Owner/Worker Agent 前端不可见
- **现象**: Agents 页面（List View 和 Tree View）只显示"老六"一个 Agent。通过 API 可以查到 Owner Agent 和 5 个 Worker Agent，但前端完全不显示
- **影响**: 用户无法看到 Agent 调度链路（Resident → Owner → Worker），完全违背核心改进诉求 20260326 第1条和第6条关于"用户必须透明知道 Agent 正在做什么"
- **严重程度**: 🔴 极高 — 这是核心设计目标

#### 3. Resident Agent 状态异常 (error)
- **现象**: 老六的状态显示为 "error"，但 `error_message` 字段为 None
- **影响**: 常驻 Agent 处于错误状态，可能导致后续消息无法正常处理
- **位置**: Agents 页面

#### 4. 任务完成后状态未更新（一直 running）
- **现象**: 所有 5 个 Subtask 状态都是 COMPLETED，但 Task 状态仍然是 "running"，Owner Agent 也还在 running
- **影响**: 任务永远不会结束，用户收不到结果回复
- **根本原因推测**: Owner Agent 在所有 Worker 完成后没有执行汇总（synthesize）步骤
- **严重程度**: 🔴 极高 — 任务卡死

#### 5. Chat 页面没有收到任何 AI 回复
- **现象**: 发送消息后，Chat 页面只显示用户发送的消息，AI 回复区域一直为空（只有"AI 正在思考..."），从未收到过实际回复
- **影响**: 用户发出的任务没有任何反馈
- **与 Bug #4 相关**: 因为任务卡在 running 状态，所以 Resident Agent 永远不会把结果返回给用户

#### 6. Task Detail API 和 Subtask API 返回 500 错误
- **现象**: `GET /api/tasks/{id}` 和 `GET /api/tasks/{id}/subtasks` 都返回 500 Internal Server Error
- **错误类型**: `TypeError: object NoneType can't be used in 'await' expression`
- **影响**: 无法在前端查看任务详情和子任务列表

#### 7. Task 的 channel_id 为 null
- **现象**: 通过 Chat 发送创建的 Task，其 `channel_id` 字段为 null
- **影响**: 无法追溯任务来源的 Channel
- **位置**: Tasks API 返回的数据

---

### 🟡 中等问题（影响体验）

#### 8. Task 列表的 Owner Agent 列只显示 "View Agent" 链接
- **现象**: Tasks 列表页 Owner Agent 列没有显示 Agent 名称，只有一个 "View Agent" 链接文本
- **期望**: 应该显示类似 "OwnerAgent-6abdba (running)" 这样的信息
- **位置**: Tasks 列表页

#### 9. Task 的 plan 和 summary 始终为 null
- **现象**: 任务从创建到 Worker 全部完成，plan 和 summary 字段一直是 null
- **影响**: 用户无法看到 Owner Agent 的任务规划和最终摘要
- **位置**: Task API

#### 10. Owner Agent 没有任何消息记录
- **现象**: `GET /api/agents/{owner_id}/messages` 返回空数组 `[]`
- **影响**: 无法审计 Owner Agent 的决策过程（如何拆解任务、如何调度 Worker）
- **设计期望**: 核心改进诉求要求用户能透明看到 Agent 间的通讯

#### 11. Worker 搜索结果质量差
- **现象**: 5 个 Subtask 中有 2 个返回"达到最大工具调用次数，任务可能未完全完成"，其余 3 个虽然 COMPLETED 但摘要显示"未找到"相关资料
- **分析**: 这可能是 LLM 模型能力问题，也可能是 tool_max_rounds=6 太小导致搜索不够充分
- **注**: 这不一定是代码 bug，但反映了系统在实际使用中的效果

#### 12. init_db.py 缺少 aiohttp 依赖
- **现象**: 初始化脚本的 health_check 阶段因 `ModuleNotFoundError: No module named 'aiohttp'` 失败
- **影响**: 初始化虽然完成了（数据已写入），但脚本以非零退出码退出，且最后的验证步骤未执行
- **位置**: scripts/init_db.py

---

### 🟢 正常工作的功能

- ✅ Dashboard 页面正常显示统计数据
- ✅ Tasks 列表页能正常显示任务（虽然详情 API 500）
- ✅ Channels 页面正常
- ✅ Models 页面正常（含 LLM Speed Test）
- ✅ System Config 页面正常（23 个配置项）
- ✅ Prompts 页面正常（4 种 Agent Prompt 都能查看）
- ✅ Chat 消息发送成功（API 层面）
- ✅ Agent 调度链路实际执行了（Resident → Owner → 5 Workers）
- ✅ LLM Speed Test 功能正常（Prefill 561ms, 19.44 tokens/s）

---

## 📊 核心改进诉求符合度检查

| 需求编号 | 需求内容 | 符合度 | 说明 |
|---------|---------|--------|------|
| 20260324-1 | LLM 流式输出 | ❌ 未见 | 没有看到流式输出相关功能 |
| 20260324-2 | LLM API 畅通检查 | ⚠️ 部分 | Speed Test 可用，但自动推断超时的联动未见 |
| 20260324-3 | Reflect 模块 | ⚠️ 部分 | 配置项存在（reflect_check_interval, reflect_stuck_threshold），但未见实际工作 |
| 20260324-4 | WebSocket | ❌ | WebSocket 连接一直显示"重连中..." |
| 20260324-5 | Agent 记忆系统 | ⚠️ 部分 | 配置项存在（memory_*），但未见实际记忆功能 |
| 20260324-6 | Agent 调用链路透明 | ❌ | 前端完全不显示 Owner/Worker Agent |
| 20260324-7 | Reflect 自动修复 | ❌ | Owner Agent 卡死在 running，Reflect 未介入 |
| 20260324-8 | Channel 可与任何 Agent 对话 | ❌ | 未实现（前端无此入口） |
| 20260324-9 | Agent 可执行本地命令 | ⚠️ | 配置存在（command_blacklist, command_timeout），但未实际测试 |
| 20260326-1 | 前端显示 Agent 通讯链路 | ❌ | 前端只显示老六 |
| 20260326-2 | 子任务全 Fail 时任务不应 Complete | ⚠️ | 当前任务一直 running，所以没触发此情况 |
| 20260326-3 | LLM 速度测试 + 自动推断超时 | ⚠️ 部分 | Speed Test 可用，但自动推断未见 |
| 20260326-4 | Agent 上下文上限 + Compact | ⚠️ | 配置存在，Compact 触发未见 |
| 20260326-5 | Agent 记忆关联 | ❌ | 未见实现 |
| 20260326-6 | Agents 页应显示所有运行中 Agent | ❌ | 只显示老六 |

---

## 🔑 总结

**最关键的 3 个问题**（建议优先修复）：

1. **任务完成后状态不更新**（Bug #4 + #5）：所有 Worker 完成后 Task 卡在 running，用户永远收不到回复。这是导致整个流程断裂的根本原因。

2. **前端不显示 Owner/Worker Agent**（Bug #2）：通过 API 能查到这些 Agent 存在，但前端完全不展示。这是核心设计目标之一。

3. **Task Detail / Subtask API 500 错误**（Bug #6）：`TypeError: object NoneType can't be used in 'await' expression`，导致无法查看任务详情。
