# LongClaw 集成测试报告 - 2026-04-02

## 测试概要

- **测试时间**: 2026-04-02 00:04 ~ 00:20
- **测试方式**: 清库后通过浏览器测试复杂任务
- **测试任务**: "搜索今天有哪些重要的科技新闻，每条新闻给出标题、来源和主要内容摘要，用列表形式呈现"

---

## ✅ 正常工作的功能

### 1. 完整 Agent 调用链路存在
- **Resident Agent (老六)** 接收用户消息
- **OwnerAgent** 创建并管理任务
- **WorkerAgents** 并行执行子任务
- API 确认链路: `7d876302 (Resident) → 18f8bf4f (Owner) → Workers (61004e20, 6b5ec873, b6b43696)`

### 2. 任务计划与拆分
OwnerAgent 正确将任务拆分为 4 个 subtasks:
- Subtask 1: 国内科技新闻搜索
- Subtask 2: 国际科技新闻搜索
- Subtask 3: AI 人工智能新闻搜索
- Subtask 4: 结果汇总

### 3. OwnerAgent 自我迭代
OwnerAgent 能够创建多个迭代（iter1, iter2, iter3, iter4）来改进搜索结果，说明任务规划能力正常。

### 4. Provider Scheduler 基础配置
```json
{
  "service_mode": "parallel",
  "max_parallel_requests": 3
}
```

### 5. Resident Agent 的 Slot 分配
```json
{
  "provider": "openai",
  "model": "minimax-m2.7",
  "slot_id": "c21a6ff2-42aa-4aca-aea5-0f38a2b47c48",
  "slot_index": 2
}
```

---

## ❌ 发现的问题

### 问题 1: 清库不彻底
**描述**: init_db.py 执行后，agents 表仍有 29 个 agents（14 个 resident agents，都是"老六"）

**原因**: agents 表有外键约束 `model_slots_ibfk_1`，无法直接 TRUNCATE

**日志**:
```
[WARNING] - 跳过: agents ((pymysql.err.IntegrityError) (1451, 'Cannot delete or update a parent row: a foreign key constraint fails (`longclaw`.`model_slots`, CONSTRAINT `model_slots_ibfk_1`)')
```

---

### 问题 2: subtask_stats 不同步
**描述**: 任务终止后，API 返回 `subtask_stats.total: 0`，但实际有 15 个 subtasks

**影响**: 前端显示 Progress 为 "0/0 0%"

**示例**:
```
"subtask_stats": {"total": 0, "completed": 0, "running": 0, "failed": 0, "pending": 0}
实际 subtasks 数组有 15 个元素
```

---

### 问题 3: Owner/Worker Agents 没有 model_assignment
**描述**: Provider Schedule 只给 Resident Agent 分配 slot，OwnerAgent 和 WorkerAgents 的 `model_assignment` 都是 null

**期望** (根据核心改进诉求 20260331):
> 按照如下规则进行分配：
> 1. 当 Resident Owner 需要立刻回复用户时，把资源分配给它否则回收
> 2. 当 Reflect 机制需要检查当前 worker 是否完成，并给 worker 发消息时，分配给它否则回收
> 3. 当 Owner Agent 尚未进行任务规划和创建 worker 或者它底下没有 worker 正在运行时分配给它，否则回收
> 4. 当 worker 没有在等待工具链调用完成，正在运行时分配给它，否则回收

**实际情况**: 只有 Resident Agent 有 slot 分配

---

### 问题 4: 前端页面加载慢/卡住
**描述**: 多次遇到 "Resource temporarily unavailable (os error 11)" 错误

**影响**: 无法正常浏览前端页面

---

### 问题 5: 任务卡住，需要手动终止
**描述**: 任务执行 10+ 分钟后（13/15 子任务完成），OwnerAgent 陷入循环重试，无法自行结束

**日志**:
```
total: 15, completed: 13, running: 2, failed: 0, pending: 0
# 10分钟后仍然是这状态
```

**Workarounds**: 需要手动调用 `POST /api/tasks/{id}/terminate` 终止

**OwnerAgent 当时在做的**:
- "检查网络连接后重新发起搜索请求"
- "如果网络持续不稳定，建议用户提供具体的科技话题或新闻网站"

---

### 问题 6: Provider Schedule 前端显示不完整
**描述**: Models 页面能看到 Provider Scheduler 区域显示 "3 slots allocated" 和 slot 分配给 "老六 resident_reply"

**但是**:
- OwnerAgent 和 WorkerAgents 没有显示在 Provider Scheduler 中
- 没有展示汇总表格（agent 和分配资源位）

**期望** (根据核心改进诉求 20260331):
> 你同时需要在前端显示你把模型分配给了哪个agent，并在model configuration页面展示一个汇总的表格（即agent和分配资源位）

---

## 📊 Provider Schedule 实现状态

| 需求项 | 状态 | 说明 |
|--------|------|------|
| Service Mode 改为最大并行数 | ✅ | `service_mode: "parallel"` |
| 每个 Provider 最大并行数 | ✅ | `max_parallel_requests: 3` |
| 资源分配优先级规则 | ❌ | 只给 Resident Agent 分配 |
| 优先级1: Resident Reply | ⚠️ | Resident 有 slot |
| 优先级2: Reflect 检查 | ❌ | 未实现 |
| 优先级3: Owner 未规划/无 worker | ❌ | Owner 无 slot |
| 优先级4: Worker 正在运行 | ❌ | Worker 无 slot |
| 前端显示分配给哪个 agent | ⚠️ | 只显示 Resident |
| 前端汇总表格 | ❌ | 未实现 |

---

## 🔍 建议排查

1. **清库脚本**: 需要先删除 model_slots 表，再清 agents 表
2. **subtask_stats**: 任务终止时没有更新统计
3. **Provider Schedule**: Owner/Worker agents 的 slot 分配逻辑未实现
4. **任务卡住**: OwnerAgent 在网络失败后没有正确的退出机制
5. **前端**: 页面加载性能问题

---

## 📝 核心改进诉求对照

### 20260324
- [x] LLM 流式输出
- [ ] Reflect 模块
- [ ] Agent 记忆系统
- [x] Resident -> Owner -> Task Agent 链路（已存在但需完善）

### 20260326
- [ ] 前端显式显示 Agent 间通讯
- [ ] 子任务全 fail 时任务状态不是 complete
- [ ] LLM 速度测试和超时推断
- [ ] Agent 最大上下文配置
- [ ] Agent 记忆关联

### 20260331
- [x] Provider 最大并行数配置
- [ ] 按优先级规则分配资源
- [ ] 前端显示资源分配表格
