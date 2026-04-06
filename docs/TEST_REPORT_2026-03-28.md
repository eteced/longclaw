# LongClaw 集成测试报告 (2026-03-28 第二轮)

## 测试任务
通过 Chat 页面向 Resident Agent 发送任务："编写一个能批量转换wav到ogg的C++项目，转换代码可以参考开源项目，不允许直接使用lib，需要了解算法后重新实现。"

## 测试环境
- 后端: localhost:8001 (uvicorn)
- 前端: localhost:5173 (vite dev)
- LLM: Qwen3.5-122B via llama.cpp (172.16.1.150:3721)
- 浏览器: agent-browser CLI (独立 session)
- API Key: YOUR_API_KEY

---

## ✅ 已修复（对比第一轮报告）

| # | 问题 | 状态 |
|---|------|------|
| 1 | WebSocket 连接失败（"重连中..."） | ✅ 修复，显示"已连接" |
| 2 | 导航栏缺少 Console 入口 | ✅ 修复，导航栏有 Console 链接 |
| 2b | Console 页面内容为空 | ✅ 修复，显示 Agent/Channel/Task/消息统计 |
| 3 | 时间显示错误（about 8 hours ago） | ✅ 修复，正确显示中文相对时间 |
| 6 | 子任务 worker_agent_id 为 null | ✅ 修复，Worker ID 正确绑定 |
| 11 | init_db.py 脚本报错 | ✅ 修复，初始化正常执行 |

---

## 🔴 新发现 BUG

### BUG-A: /api/messages/task/{id} 返回 500 Internal Server Error
- **现象**: 任务详情页加载失败，显示 "Failed to load task details"
- **原因**: API `/api/messages/task/{task_id}` 返回 500
- **影响**: 任务详情页完全无法使用
- **严重度**: **P0** — 核心页面不可用
- **备注**: 任务 API 和 Agents API 本身返回正常，问题出在 messages 接口

### BUG-B: Tasks 列表 PROGRESS 列显示错误
- **现象**: 已完成的任务，PROGRESS 列显示 "terminated 0%"
- **实际**: 5 个子任务全部 completed，任务状态 completed
- **影响**: 用户无法正确判断任务完成进度
- **严重度**: **P0**
- **可能原因**: 前端将 OwnerAgent 的 terminated 状态错误地显示在 PROGRESS 列

### BUG-C: 任务完成后 Resident Agent 状态变为 error
- **现象**: 任务完成后，老六的状态从 running 变为 error
- **实际**: error_message 为 None，没有实际错误
- **影响**: 用户看到 Resident Agent 状态异常
- **严重度**: **P1**
- **可能原因**: 任务完成后 Resident Agent 回调处理有 bug，错误设置了状态

### BUG-D: Agents 页面 "All Types" 不显示 Owner/Worker
- **现象**: 默认 All Types 筛选只显示 Resident Agent
- **实际**: 通过类型筛选（Owner/Worker）可以看到对应 Agent
- **影响**: 用户无法一眼看到所有 Agent，默认视图不完整
- **严重度**: **P1**
- **备注**: Console 页面能正确显示所有 7 个 Agent

### BUG-E: 子任务进度永远显示 0/5 (0%)
- **现象**: 即使 5 个子任务全部 running/completed，进度仍显示 0/5 (0%)
- **影响**: 进度条没有意义
- **严重度**: **P1**
- **上次记录**: 第一轮就发现，仍未修复

### BUG-F: Plan 字段始终为 null
- **现象**: Owner Agent 拆解了任务但 plan 字段为 null
- **影响**: 用户看不到任务执行计划
- **严重度**: **P2**

### BUG-G: Scheduler 仍然每秒轮询
- **现象**: 日志中每秒都在查询 tasks + agents 表
- **上次记录**: 第一轮就发现，仍未修复
- **严重度**: **P2**
- **备注**: scheduler_check_interval=1（秒）

### BUG-H: 搜索引擎普遍超时
- **现象**: 百度/Bing 15 秒超时，Worker 搜索多次失败
- **影响**: 搜索任务大部分返回"未找到"
- **严重度**: **P1**
- **上次记录**: 第一轮就发现，虽有改善但仍存在

---

## ⚠️ 设计预期偏差

### 1. Worker 搜索结果质量极低
- 所有 5 个子任务中，4 个搜索结果总结为"未找到"
- Worker 连续搜索 3 次就被强制停止
- LLM（Qwen3.5-122B 量化模型）对 tool 调用后结果处理能力不足
- **核心改进诉求（20260326 第1条）要求 Agent 间通讯透明化** — 但 Messages API 500 导致完全看不到

### 2. Owner 汇总超时
- Summary 开头就是"抱歉，整合结果超时"
- Owner Agent 在收到 5 个 Worker 结果后，LLM 汇总耗时过长导致超时
- 结果只简单拼接了子任务结果，没有真正整合

### 3. Agent 间通讯不可见
- 核心改进诉求反复要求：用户必须透明知道 Agent 在做什么
- Resident→Owner、Owner→Worker 的对话和调度过程不可见
- Messages API 500 错误导致连仅有的消息都看不了

---

## ✅ 正常工作

- ✅ Dashboard 页面统计正确（任务分类、Agent 数量）
- ✅ Chat 页面 WebSocket 连接正常（"已连接"）
- ✅ Chat 页面发送消息正常，"AI 正在思考..." 提示正常
- ✅ Resident→Owner→Worker 调度流程工作
- ✅ 子任务拆解质量不错（5 个子任务，覆盖关键技术点）
- ✅ Worker Agent 正确绑定到子任务
- ✅ Console 页面完整功能（Agent/Channel/统计/干预按钮）
- ✅ Console 显示所有 7 个 Agent
- ✅ Agents 页面支持类型筛选（Owner/Worker 可见）
- ✅ 子任务详情显示 Worker ID 和完整描述
- ✅ Models 页面 LLM Speed Test 功能存在
- ✅ System 页面配置项完整
- ✅ 时间显示正确（中文相对时间）
- ✅ 数据库初始化脚本正常

---

## 优先级建议

| 优先级 | BUG | 描述 |
|--------|-----|------|
| **P0** | A | /api/messages/task/{id} 500 错误 |
| **P0** | B | Tasks PROGRESS 列显示错误 |
| **P1** | C | 任务完成后 Resident Agent 变 error |
| **P1** | D | Agents 页面 All Types 不显示 Owner/Worker |
| **P1** | E | 子任务进度永远 0% |
| **P1** | H | 搜索引擎超时 |
| **P2** | F | Plan 字段始终 null |
| **P2** | G | Scheduler 每秒轮询 |
