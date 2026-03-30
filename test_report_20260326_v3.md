# LongClaw 集成测试报告 #3 - 2026-03-26 12:08

## 测试条件
- 按 INTEGRATION_TEST_GUIDE.md 执行 `init_db.py --force`（验证阶段报错 `No module named 'aiohttp'`，但 agent/channel 创建成功）
- 重启后端
- 发送任务：编写批量转换 wav 到 ogg 的 C++ 项目
- 监控约 20 分钟

---

## ✅ 已修复的问题

### subtasks.updated_at 列 ✅
- 数据库已有 `updated_at` 列，不再报 `Unknown column` 错误

### Agent 状态展示 ✅
- Dashboard 正确显示 Running Tasks: 1, Active Agents: 1+
- Owner/Worker Agent 创建并运行正常
- Chat 页面能看到完整的 AI 回复（技术方案 + 项目结构建议）

---

## 🔴 仍然存在的问题

### BUG-1: 任务详情 API 全部 500
- `GET /api/tasks/{id}` → Internal Server Error
- `GET /api/tasks/{id}/subtasks` → Internal Server Error
- 错误：`TypeError: object NoneType can't be used in 'await' expression`
- **影响**：前端任务详情页不可用，"View Agent" 按钮跳转到 Agents 页面而非任务详情

### BUG-2: 任务完成但不标记 completed
- 4 个子任务全部 COMPLETED，OwnerAgent 状态 idle，但任务状态仍为 running
- plan/summary/result 字段全部为空/false
- **根因**：OwnerAgent 收集完子任务结果后，合成最终回复的逻辑可能未正确更新任务状态

### BUG-3: 老六 Resident Agent 被 scheduler 误标 error
- 日志：`Agent has not updated recently, marking as error`
- 老六在 OwnerAgent 执行子任务期间没有活动，被 scheduler 超时机制误判
- **影响**：Dashboard 上老六显示 error，但实际仍在工作

### BUG-4: 初始化脚本验证阶段报错
- `No module named 'aiohttp'`（之前是 `SystemConfig has no attribute 'id'`）
- agent/channel 实际创建成功，但验证失败导致配置项未创建

### BUG-5: Chat API 返回空响应
- POST /api/chat/send 的 response body 为空
- 前端 Chat 页面通过 WebSocket 拿到了回复，但 HTTP response 没有

### BUG-6: Agents Tree View 不显示 Owner/Worker
- 前端 Agents 页面只显示老六，Tree View 下也没有展开 Owner 和 Worker 节点
- API 能查到 6 个 agent

---

## 🟡 工具/基础设施问题

### 搜索引擎全面超时
- 百度、Bing、Google、DuckDuckGo Lite 全部 15s timeout
- agent-browser 被多个 worker 复用导致 `Event stream closed`
- Worker 触发了 `max consecutive searches (3), forcing final response` 限制
- **根因**：agent-browser 是单实例，多个 Worker 并发调用时会互相干扰

### 子任务 result 字段为 NULL
- 4 个子任务都有 summary（搜索结果汇总），但 result 字段全部为 NULL
- **影响**：任务只有"调研报告"，没有实际代码产出

---

## 📊 功能验证总结

| 功能 | 状态 | 备注 |
|------|------|------|
| 健康检查 | ✅ | /health 正常 |
| 数据库初始化 | ⚠️ | 部分成功，验证阶段报错 |
| Chat 发送任务 | ✅ | 前端 WebSocket 能收到回复 |
| 任务创建 | ✅ | 任务正确创建为 running |
| Agent 调度链路 | ✅ | Resident → Owner → 4 Workers |
| 子任务执行 | ✅ | 4/4 COMPLETED |
| 任务完成 | ❌ | 任务卡在 running 不结束 |
| 任务详情 API | ❌ | 全部 500 |
| Agent Tree View | ❌ | 只显示 Resident |
| Dashboard 统计 | ⚠️ | Running Tasks 正确，但老六误标 error |
| 搜索工具 | ❌ | 全面超时，agent-browser 并发冲突 |
| 实际代码产出 | ❌ | 子任务只产出调研摘要，result 全 NULL |

---

## 🎯 对比核心改进诉求

### 20260324 需求
1. **流式输出** — ⚠️ 未明确验证（Chat 页面能显示回复，不确定是否流式）
2. **Reflect 模块** — ❌ 未观察到
3. **WebSocket** — ⚠️ 前端 Chat 能工作，但 HTTP response 空
4. **Agent 调用链路可见性** — ⚠️ API 能查到，但前端 Tree View 不展示
5. **Channel→Agent 对话可见性** — ⚠️ Chat 页面有对话，但 Agent→Worker 的不可见

### 20260326 需求
1. **前端看不到 Agent 间创建和运行流程** — ❌ 未满足（Tree View 只显示 Resident）
2. **子 task 全 Fail 时任务状态不应为 complete** — N/A（子任务全 COMPLETED 但任务不结束，是另一个问题）

---

## 结论

相比 v1/v2，CC 修复了 subtasks 表结构和 Agent 状态显示，**任务终于能跑起来了**（Worker 执行子任务、Chat 页面有回复）。但仍有多个阻塞问题：
1. 任务完成后不标记 completed（最严重）
2. 任务详情 API 全部 500
3. 搜索工具在并发场景下全面失效
4. 前端 Tree View 不展示完整 Agent 层级
