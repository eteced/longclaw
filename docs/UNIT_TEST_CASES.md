# LongClaw 集成测试用例 (轻量级)

> 目的：用对 LLM 压力极小的任务，验证 Agent 调度链路和子任务依赖机制

---

## 系统配置

### 两阶段依赖确认
系统默认启用两阶段依赖确认功能：
1. **第一阶段**: LLM 生成子任务描述
2. **第二阶段**: LLM 分析依赖关系和优先级

相关配置项（在 `system_configs` 表）：
- `owner_confirm_dependencies`: `true` - 启用两阶段依赖确认（推荐）
- `force_complex_task`: `false` - 强制所有任务走复杂任务流程（用于测试）

### 强制复杂任务模式
在测试消息中加入 `[COMPLEX]` 关键字，可以强制系统使用 OwnerAgent 进行任务拆解。
这样可以确保测试任务一定会走复杂任务流程，而不受简单任务判断逻辑影响。

---

## 测试任务模板

### Task-A: 双城市天气对比（推荐，测试并行+串行）

**发送内容：**
```
[COMPLEX] 帮我完成以下三步任务：第一步，搜索"2026年3月29日北京天气"；第二步，搜索"2026年3月29日上海天气"；第三步，根据前两步的结果，对比两个城市哪个更适合出行，给出一句推荐。请按顺序执行，第三步依赖前两步的结果。
```

**预期行为：**
1. Resident 判断为复杂任务 → 创建 Task + OwnerAgent
2. Owner 拆解为 3 个 subtask：
   - #0: 搜索北京天气（可并行）
   - #1: 搜索上海天气（可并行，与 #0 无依赖）
   - #2: 对比并推荐（**依赖 #0 和 #1**）
3. #0 和 #1 并行执行，完成后 #2 才开始
4. Owner 汇总结果，回复用户

**验证要点：**
- [ ] Owner 是否正确识别出 #0/#1 可并行，#2 依赖前两者
- [ ] #2 是否在 #0 和 #1 都完成后才开始（不要提前开始）
- [ ] Plan 字段是否被正确填充（当前 BUG：始终为 null）
- [ ] 所有 subtask 完成后，任务状态是否正确更新
- [ ] Resident 最终状态是否保持正常（非 error）

**预估 token 消耗：** 每步约 200-400 token，总计 < 1500 token

---

### Task-B: 两步简单查询（测试串行依赖）

**发送内容：**
```
[COMPLEX] 先帮我搜索"Python最新稳定版本号是多少"，然后用搜索到的版本号，再搜索"这个版本的Python有什么新特性"，最后把结果告诉我。
```

**预期行为：**
1. Owner 拆解为 2 个 subtask：
   - #0: 搜索 Python 版本号
   - #1: 用版本号搜索新特性（**强依赖 #0**）
2. 严格串行执行

**验证要点：**
- [ ] #1 是否等待 #0 完成
- [ ] #1 的描述中是否包含了 #0 的结果信息

**预估 token 消耗：** 每步约 200 token，总计 < 600 token

---

### Task-C: 三个并行信息收集（测试纯并行）

**发送内容：**
```
[COMPLEX] 帮我同时查三样东西：1.今天比特币价格 2.今天以太坊价格 3.今天黄金价格。查完后做一个简单的价格排名，从高到低列出来。
```

**预期行为：**
1. Owner 拆解为 4 个 subtask：
   - #0/#1/#2: 分别搜索三种价格（纯并行）
   - #3: 排名汇总（依赖 #0/#1/#2）
2. 三个搜索全部并行完成后，汇总任务开始

**验证要点：**
- [ ] 三个搜索任务是否同时启动
- [ ] Worker 数量是否 >= 3（并行执行）

**预估 token 消耗：** 每步约 150-300 token，总计 < 1200 token

---

## 自动化测试脚本

### Python 自动化测试

运行以下命令执行自动化测试脚本：

```bash
cd /home/claw/.openclaw/workspace/longclaw
python backend/tests/test_agent_pipeline.py
```

测试脚本会自动：
1. 检查服务器状态
2. 发送测试消息（包含 [COMPLEX] 关键字）
3. 等待任务完成
4. 验证所有检查点
5. 输出测试报告

### 手动 API 验证

在任务发布后，可通过以下 API 调用手动验证：

```bash
API="http://localhost:8001"
KEY="longclaw_admin_2026"
TASK_ID="<从响应中获取>"

# 1. 等待任务创建
sleep 3

# 2. 检查 OwnerAgent 是否创建
echo "=== Agents ==="
curl -s -H "X-API-Key: $KEY" "$API/api/agents" | python3 -c "
import sys,json; d=json.load(sys.stdin)
for a in d['items']:
    print(f'{a[\"agent_type\"]:10} {a[\"status\"]:10} {a[\"name\"]}')
"

# 3. 检查子任务数量和依赖
echo "=== Subtasks ==="
curl -s -H "X-API-Key: $KEY" "$API/api/tasks/$TASK_ID/subtasks" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'Total subtasks: {len(d)}')
for s in d:
    print(f'  #{s[\"order_index\"]} | {s[\"status\"]:10} | parent={s.get(\"parent_subtask_id\",\"none\")} | {s[\"title\"][:50]}')
"

# 4. 等待完成后检查状态
sleep 60
echo "=== Final Status ==="
curl -s -H "X-API-Key: $KEY" "$API/api/tasks/$TASK_ID" | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'Task status: {d[\"status\"]}')
print(f'Plan: {\"有内容\" if d.get(\"plan\") else \"null ❌\"}')
print(f'Summary: {str(d.get(\"summary\",\"\"))[:100]}')
"
```

---

## 验证 Checklist（适用于所有测试任务）

| # | 检查项 | Task-A | Task-B | Task-C |
|---|--------|--------|--------|--------|
| 1 | Resident → Owner 链路正确 | ☐ | ☐ | ☐ |
| 2 | Owner 正确拆分子任务 | ☐ | ☐ | ☐ |
| 3 | Worker 数量匹配子任务数 | ☐ | ☐ | ☐ |
| 4 | 并行子任务同时启动 | ☐ | N/A | ☐ |
| 5 | 串行子任务按顺序执行 | ☐ | ☐ | ☐ |
| 6 | Plan 字段非 null | ☐ | ☐ | ☐ |
| 7 | 所有 subtask 状态正确（失败=failed） | ☐ | ☐ | ☐ |
| 8 | 任务最终状态正确 | ☐ | ☐ | ☐ |
| 9 | Resident 状态保持正常（非 error） | ☐ | ☐ | ☐ |
| 10 | Chat 页面有明确的执行状态提示 | ☐ | ☐ | ☐ |
| 11 | Tasks 列表 Progress 正确显示 | ☐ | ☐ | ☐ |
| 12 | 子任务依赖关系正确设置 (depends_on) | ☐ | ☐ | ☐ |
| 13 | 优先级字段存在且有值 | ☐ | ☐ | ☐ |

---

*创建时间: 2026-03-29*
