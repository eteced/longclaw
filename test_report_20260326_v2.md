# LongClaw 集成测试报告 #2 - 2026-03-26 10:12

## 测试条件
- 按 INTEGRATION_TEST_GUIDE.md 执行初始化 (`init_db.py --force`)
- 重启后端
- 发送任务：批量转换 wav 到 ogg 的 C++ 项目

## 🔴 未修复的问题

### BUG-1 (仍存在): subtasks 表缺少 `updated_at` 列
- **现象**: 所有新任务创建后立即 error
- **错误**: `Unknown column 'subtasks.updated_at' in 'RETURNING'`
- **数据库确认**: `DESCRIBE subtasks` 显示无 `updated_at` 列
- **根因**: CC 本次修改未涉及此列的添加。ORM 定义了该字段但数据库表没有

### BUG-2/3 (仍存在): 任务详情 API 返回 500 / 空响应
- `GET /api/tasks/{id}` → 空 body
- `GET /api/tasks/{id}/subtasks` → Internal Server Error

## 🟡 已改善的问题

### BUG-5/6: ✅ 老六 Agent 状态显示改善
- 之前：error + terminated_at 有值
- 现在：running + terminated_at 为 null
- Dashboard Active Agents 显示 1（之前是 0）
- 但 OwnerAgent 仍显示 error（因为子任务创建失败导致）

## 🟢 新发现

### 初始化脚本 BUG (仍存在)
- 验证阶段报错 `SystemConfig has no attribute 'id'`
- 配置项创建数量 0（已存在的配置不会被重新插入，所以如果后端启动时已自动创建配置则无影响）
- 后端启动日志显示 `Created default config: agent_max_context_tokens=8192` 等，说明后端自带了配置创建逻辑

### Dashboard 统计
- Running Tasks: 0（应显示 error 的 1 个？或者 error 确实不算 running）
- Completed Tasks: 0 ✅（正确，没有完成的）
- Active Agents: 1 ✅（改善，之前是 0）
- 能看到 OwnerAgent 和老六的名字

---

## 结论

CC 本次修改改善了 Agent 状态显示，但**核心阻塞问题未修复**：subtasks 表缺少 updated_at 列导致所有新任务都无法执行。

**CC 需要做的事**：
1. 在 subtasks 表添加 `updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP`
2. 修复任务详情 API（可能和 #1 有关联）
3. 修复初始化脚本 SystemConfig.id 报错
