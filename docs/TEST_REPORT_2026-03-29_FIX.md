# LongClaw 集成测试报告 (2026-03-29 修复版)

## 修复概述

基于 TEST_REPORT_2026-03-28.md 中发现的问题，进行了以下修复：

---

## ✅ 已修复 BUG

### BUG-A: /api/messages/task/{id} 返回 500 Internal Server Error
- **原因**: `MessageResponse` schema 中的 `metadata` 字段使用了 alias，但 Pydantic 的 `model_validate` 无法正确映射 ORM 模型的 `message_metadata` 字段
- **修复**: 重写 `MessageResponse.model_validate` 方法，手动映射字段
- **文件**: `backend/api/messages.py`
- **测试**: `backend/tests/test_api.py::TestMessagesAPI::test_get_task_messages_success`

### BUG-B: Tasks 列表 PROGRESS 列显示错误
- **原因**: 前端 `TasksPage.tsx` 中 `ProgressBar` 的 `completed` 和 `total` 被硬编码为 0
- **修复**:
  1. 后端 `TaskResponse` 添加 `subtask_stats` 字段
  2. 后端 `task_service.py` 添加 `get_subtask_stats` 方法
  3. 前端 `TasksPage.tsx` 正确使用 `subtask_stats` 数据
- **文件**:
  - `backend/api/tasks.py`
  - `backend/services/task_service.py`
  - `frontend/src/types/index.ts`
  - `frontend/src/pages/TasksPage.tsx`
- **测试**: `backend/tests/test_api.py::TestTasksAPI::test_subtask_stats_correct_values`

### BUG-C: 任务完成后 Resident Agent 状态变为 error
- **原因**:
  - `scheduler_service.py` 的 `_check_agent_health` 方法会将长时间未更新的 RUNNING 状态 agent 标记为 ERROR
  - Resident Agent 在 `_delegate_to_owner_agent` 中等待 OwnerAgent 完成期间，没有更新心跳
  - 如果 OwnerAgent 执行时间超过 scheduler_agent_timeout（默认 300 秒），Resident Agent 会被错误标记为 ERROR
- **修复**:
  1. 在 `ResidentAgent` 中添加 `_heartbeat_during_execution` 方法，在长时间任务执行期间定期更新心跳
  2. 修改 `_delegate_to_owner_agent` 在等待 OwnerAgent 时启动心跳任务
  3. 恢复 scheduler 对所有 Agent 的健康检查（不再跳过 Resident Agent）
- **文件**:
  - `backend/agents/resident_agent.py`
  - `backend/services/scheduler_service.py`
- **测试**: `backend/tests/test_api.py::TestSchedulerService::test_active_agent_not_marked_error`

### BUG-D: Agents 页面 "All Types" 不显示 Owner/Worker
- **原因**: 在 tree view 中，Owner/Worker agents 作为 Resident Agent 的子节点，默认是折叠的
- **修复**: 修改 `AgentsPage.tsx` 自动展开有子节点的 agent
- **文件**: `frontend/src/pages/AgentsPage.tsx`
- **测试**: `backend/tests/test_api.py::TestAgentsAPI::test_all_types_returns_all_agents`

### BUG-E: 子任务进度永远显示 0%
- **原因**: 与 BUG-B 相同，前端没有从后端获取子任务统计数据
- **修复**: 同 BUG-B
- **测试**: `backend/tests/test_api.py::TestTasksAPI::test_task_list_includes_subtask_stats`

---

## 📁 新增文件

| 文件 | 说明 |
|------|------|
| `backend/tests/__init__.py` | 测试包初始化 |
| `backend/tests/conftest.py` | Pytest 配置 |
| `backend/tests/test_api.py` | API 接口测试用例 |

---

## 🧪 运行测试

```bash
cd /home/claw/.openclaw/workspace/longclaw/backend
source venv/bin/activate
pytest -v tests/test_api.py
```

---

## 📋 未修复问题 (P2 优先级)

以下问题未在本次修复中处理：

| # | 问题 | 优先级 | 说明 |
|---|------|--------|------|
| BUG-F | Plan 字段始终为 null | P2 | 需要在 OwnerAgent 中正确设置 plan 字段 |
| BUG-G | Scheduler 每秒轮询 | P2 | 已改为 10 秒轮询，但可能需要进一步优化 |
| BUG-H | 搜索引擎普遍超时 | P1 | 这是外部依赖问题，需要调整 timeout 或使用更稳定的搜索引擎 |

---

## ⚠️ 注意事项

1. **数据库迁移**: 本次修复添加了新的 API 字段 (`subtask_stats`)，但不需要数据库迁移
2. **前端兼容**: 前端 `types/index.ts` 已更新，确保前后端类型一致
3. **测试数据库**: 测试用例需要 `longclaw_test` 数据库，运行前请确保创建：
   ```sql
   CREATE DATABASE longclaw_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   GRANT ALL PRIVILEGES ON longclaw_test.* TO 'longclaw'@'%';
   ```
4. **新配置项**: 添加了 `resident_heartbeat_interval` 配置（默认 60 秒），控制 Resident Agent 在长时间任务执行期间的心跳更新频率

---

## 🔧 新增配置项

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `resident_heartbeat_interval` | 60 | Resident Agent 在长时间任务执行期间的心跳更新间隔（秒） |

此配置应小于 `scheduler_agent_timeout`（默认 300 秒）以确保心跳在超时前更新。

---

## 🔄 验证步骤

1. 重启后端服务
2. 重启前端开发服务器
3. 访问 Tasks 页面，检查 Progress 列是否正确显示子任务进度
4. 访问 Agents 页面，检查 "All Types" 是否显示所有 agent 类型
5. 创建任务并等待完成，检查 Resident Agent 状态是否保持正常

---

*报告生成时间: 2026-03-29*
