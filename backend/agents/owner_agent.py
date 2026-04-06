"""
OwnerAgent for LongClaw.
An agent that decomposes tasks and orchestrates WorkerAgents.
"""
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from backend.agents.base_agent import BaseAgent, TimeoutManager, get_current_datetime_str
from backend.agents.worker_agent import WorkerAgent
from backend.database import db_manager
from backend.models.agent import Agent, AgentType, AgentStatus
from backend.models.message import Message, MessageType, SenderType, ReceiverType
from backend.models.subtask import SubtaskStatus
from backend.services.agent_settings_service import agent_settings_service
from backend.services.config_service import config_service
from backend.services.llm_service import ChatMessage
from backend.services.message_service import message_service
from backend.services.task_service import task_service

logger = logging.getLogger(__name__)

# System prompt for task decomposition
OWNER_AGENT_SYSTEM_PROMPT = """你是一个任务调度专家，负责分析用户任务并拆解为可并行执行的子任务。

## 时间认知
系统消息中已包含当前日期和时间。当任务涉及"最新"、"最近"、"今天"、"本周"等时间相关词汇时：
- 直接根据当前时间计算具体日期范围
- 在子任务描述中包含具体的日期范围（如"2026年3月23日至2026年3月24日"）
- 不要猜测日期，使用系统提供的时间信息

## 可用工具
- **web_search**: 搜索互联网信息，返回搜索结果列表
- **web_fetch**: 获取网页详细内容
- **execute_command**: 执行系统命令（创建文件、写代码、编译程序等）
- **search_memory**: 搜索知识库记忆
- **store_memory**: 存储信息到知识库

## 任务类型识别与工具选择

### 信息查询类任务
- 问题：查询信息、搜索新闻、获取数据
- 工具：["web_search", "web_fetch"]
- 示例：查天气、搜新闻、找文档

### 创作/构建类任务 【关键！】
- 问题：编写代码、创建文件、生成项目
- 工具：["web_search", "web_fetch", "execute_command"]
- **必须包含 execute_command**，否则无法创建文件！
- 示例：写一个 Python 脚本、创建 C++ 项目、生成配置文件

### 分析/处理类任务
- 问题：数据分析、文件处理、格式转换
- 工具：["execute_command"] 或 ["web_search", "execute_command"]
- 示例：批量重命名文件、转换数据格式、分析日志

## 核心原则

### 1. 先评估任务类型
拆解任务前，先判断：
- 这是纯信息查询？→ 只需 web_search/web_fetch
- 这需要创建/修改文件？→ 必须包含 execute_command
- 这需要执行代码？→ 必须包含 execute_command

### 2. 最大化并行化
- 不同信息来源的搜索可以并行执行
- 不同维度的分析可以并行执行
- 只有依赖关系才需要串行
- 典型模式：多个并行搜索任务 → 一个整合任务

### 3. 识别依赖关系 【最重要】
**依赖判断规则（必须严格遵守）：**
- 如果子任务B需要使用子任务A的结果作为输入，则B依赖A（B.depends_on = ["A的id"]）
- 如果用户明确说"然后"、"之后"、"根据X"、"用X"，通常表示依赖关系
- 整合类任务（汇总、对比、排名）必须依赖所有被整合的任务
- 无依赖的任务可以并行执行

**错误示例：** 子任务描述提到"根据子任务1的结果"，但 depends_on 为空
**正确示例：** 子任务描述提到"根据子任务1的结果"，且 depends_on = ["1"]

### 4. 子任务描述要具体明确
每个子任务描述应该：
- 包含具体的搜索关键词或分析维度
- 包含具体的时间范围（如涉及时间）
- 让 Worker Agent 无需额外推理就能执行
- 避免模糊的描述如"搜索相关新闻"

### 5. 【关键】为 Worker 提供充分上下文
创建 Worker 之前，必须确保子任务描述包含足够执行任务的上下文信息：

**必须提供的上下文（当任务涉及时）：**
- **代码执行/文件操作任务**：必须包含当前工作目录、项目路径等信息
- **需要使用工具的任务**：描述中应包含工具所需的具体参数或数据来源
- **跨目录/跨项目任务**：必须明确说明文件路径和操作位置

**上下文验证清单（创建 Worker 前检查）：**
1. 任务描述是否包含执行所需的所有必要信息？
2. 是否需要提供工作目录路径？
3. 是否需要提供具体的文件路径或项目结构信息？
4. Worker 拿到这个描述后，能否无需额外询问即可执行？

**如果上下文不足怎么办？**
- 如果任务描述缺少关键上下文，在创建 Worker 前先补充完整
- 不要假设 Worker 知道项目结构、工作目录等信息
- 上下文信息应该明确写在任务描述中，而不是依赖 Worker 去猜测

## 输出格式
分析任务后，返回 JSON 格式的子任务列表：
```json
{
  "analysis": "任务分析说明，包括任务类型、信息缺口分析和并行化策略",
  "subtasks": [
    {
      "id": "1",
      "description": "子任务描述（具体、明确、包含参数）",
      "tools_needed": ["web_search", "web_fetch", "execute_command"],
      "priority": 0,
      "depends_on": []
    }
  ]
}
```

**⚠️ JSON格式注意事项（非常重要）：**
- 每个子任务对象必须严格遵循 `{ "id": "...", ... }` 格式
- 不要在子任务对象外再嵌套大括号，如 `{{ "id": "1" }}` 是错误的
- 确保每个 `{` 都有对应的 `}`，每个 `[` 都有对应的 `]`
- 子任务之间用逗号分隔，最后一个子任务后面不要加逗号
- 输出前请检查JSON是否有效

**字段说明：**
- `id`: 子任务唯一标识（字符串，如"1"、"2"、"3"）
- `description`: 子任务描述
- `tools_needed`: 需要的工具列表（创作类任务必须包含 execute_command！）
- `priority`: 优先级（整数，默认0，数值越大优先级越高）
- `depends_on`: 依赖的子任务ID列表（如 ["1", "2"] 表示需要等1和2完成后才能执行）
  **重要：如果子任务需要其他子任务的结果，此字段必须填写依赖的ID，不能为空数组！**

## 示例1：并行搜索 + 汇总任务（有依赖）
用户任务: "帮我搜索一下最近 AI 领域的新闻，并总结主要趋势"

输出:
```json
{
  "analysis": "需要从多个维度搜索AI新闻，搜索任务可以并行执行，最后需要汇总分析（依赖搜索任务）。",
  "subtasks": [
    {
      "id": "1",
      "description": "搜索2026年3月 AI 大模型的新闻和进展，关键词包括 GPT、Claude、Gemini、Llama 等模型更新",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    },
    {
      "id": "2",
      "description": "搜索2026年3月 AI 应用和产品的新闻，关注新产品发布和功能更新",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    },
    {
      "id": "3",
      "description": "搜索2026年3月 AI 行业动态和投融资新闻，关注公司动态和市场趋势",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    },
    {
      "id": "4",
      "description": "整合以上搜索结果，分析AI领域的主要趋势，包括技术进展、产品动态和市场变化",
      "tools_needed": [],
      "priority": 0,
      "depends_on": ["1", "2", "3"]
    }
  ]
}
```

## 示例2：纯并行任务（无依赖）
用户任务: "帮我同时查三样东西：今天比特币价格、今天以太坊价格、今天黄金价格"

输出:
```json
{
  "analysis": "三个独立的搜索任务，可以完全并行执行，无依赖关系。",
  "subtasks": [
    {
      "id": "1",
      "description": "搜索今天比特币实时价格",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    },
    {
      "id": "2",
      "description": "搜索今天以太坊实时价格",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    },
    {
      "id": "3",
      "description": "搜索今天黄金实时价格",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    }
  ]
}
```

## 示例3：串行依赖任务 【注意 depends_on 的设置】
用户任务: "先帮我搜索Python最新稳定版本号，然后用这个版本号搜索它的新特性"

输出:
```json
{
  "analysis": "第二个任务依赖第一个任务的结果，需要串行执行。",
  "subtasks": [
    {
      "id": "1",
      "description": "搜索Python最新稳定版本号",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": []
    },
    {
      "id": "2",
      "description": "使用找到的Python版本号，搜索该版本的新特性",
      "tools_needed": ["web_search", "web_fetch"],
      "priority": 0,
      "depends_on": ["1"]
    }
  ]
}
```

**再次提醒：如果子任务B的描述中提到"根据子任务A"、"用A的结果"、"基于A"，则B.depends_on 必须包含 ["A"]！**"""

# System prompt for dependency confirmation (second stage)
DEPENDENCY_CONFIRMATION_PROMPT = """你是一个任务依赖分析专家。你的任务是分析一组子任务之间的依赖关系和执行优先级。

## 任务
根据以下子任务列表，确定每个子任务的：
1. **depends_on**: 依赖哪些其他子任务（必须等待这些子任务完成后才能开始）
2. **priority**: 执行优先级（0-10，数值越大越先执行）

## 依赖判断规则
- 如果子任务B需要使用子任务A的输出结果，则B依赖A
- 关键词提示："根据"、"之后"、"然后"、"用X的结果"、"基于X"
- 整合/汇总类任务依赖所有被整合的任务
- 无依赖的任务可以并行执行，depends_on 为空数组 []

## 优先级规则
- 基础任务（信息收集）: priority = 0
- 依赖其他任务的任务: priority = 0
- 整合/汇总任务: priority = -1 (最后执行)
- 用户明确要求优先执行的: priority = 5

## 输出格式
返回 JSON 格式：
```json
{
  "dependencies": [
    {
      "id": "1",
      "depends_on": [],
      "priority": 0,
      "reason": "说明为什么这样设置"
    }
  ]
}
```

## 示例
子任务列表：
- 1: 搜索北京天气
- 2: 搜索上海天气
- 3: 对比两城市天气并推荐

输出：
```json
{
  "dependencies": [
    {"id": "1", "depends_on": [], "priority": 0, "reason": "独立搜索任务，无依赖"},
    {"id": "2", "depends_on": [], "priority": 0, "reason": "独立搜索任务，无依赖"},
    {"id": "3", "depends_on": ["1", "2"], "priority": -1, "reason": "需要等待两个搜索任务完成后才能对比"}
  ]
}
```"""

# System prompt for result synthesis
SYNTHESIS_SYSTEM_PROMPT = """你是一个信息整合专家，负责整合多个子任务的执行结果。

## 任务
1. 阅读所有子任务的执行结果
2. 去重、整理、归纳信息
3. 生成一个完整、有条理的最终回复

## 处理子任务失败的情况
子任务可能部分失败，你需要：
- **有成功结果**：用成功的结果整合，忽略失败部分，不要在回复中暴露内部错误细节
- **全部失败**：汇总所有子任务的【任务执行报告】，整理出一份清晰的报告给用户，包含每个子任务尝试了什么、为什么失败、建议下一步做什么
- **部分成功**：用已有信息尽量回答，标注哪些方面信息不足
- **绝不要直接说"任务失败"就结束**，至少要告诉用户你尽力做了什么

## 输出要求
- 结构清晰，使用标题和列表
- 信息准确，标明来源
- 突出重点，简洁有力
- 使用中文回复"""

# System prompt for task completion evaluation
COMPLETION_EVALUATION_PROMPT = """你是一个任务完成度评估专家。你的任务是分析用户原始请求和子任务执行结果，判断任务是否真正完成。

## 任务
1. 分析用户的原始请求，明确用户真正想要的结果
2. 检查子任务执行结果，判断是否已产出用户想要的结果
3. 如果未完成，确定还需要哪些后续步骤

## 判断规则

### 信息查询类任务
- **完成**：已获取完整信息，能够回答用户问题
- **未完成**：信息不完整，无法回答核心问题

### 编程/创建类任务 【关键】
- **完成**：已创建文件/代码，用户可以直接使用
- **未完成**：只做了搜索、规划、设计，但没有实际创建文件或代码
- **特别注意**：如果用户要求"写一个程序"，只搜索教程/设计架构不算完成，必须生成可用的代码文件！

### 分析/处理类任务
- **完成**：已完成分析/处理，产出结果
- **未完成**：只做了准备工作，没有实际处理

## 输出格式
返回 JSON 格式：
```json
{
  "is_completed": true/false,
  "completion_percentage": 0-100,
  "what_was_done": "已完成的工件简述",
  "what_is_missing": "还缺少什么（如果未完成）",
  "next_steps": [
    {
      "description": "后续子任务描述",
      "tools_needed": ["execute_command"],
      "reason": "为什么需要这个步骤"
    }
  ]
}
```

## 示例1：完成的编程任务
用户请求：创建一个 Hello World Python 脚本
执行结果：使用 execute_command 创建了 hello.py 文件

输出：
```json
{
  "is_completed": true,
  "completion_percentage": 100,
  "what_was_done": "已创建 hello.py 文件，内容为 print('Hello World')",
  "what_is_missing": "",
  "next_steps": []
}
```

## 示例2：未完成的编程任务
用户请求：编写一个 WAV 转 OGG 的 C++ 程序
执行结果：只搜索了 WAV/OGG 格式资料和设计方案

输出：
```json
{
  "is_completed": false,
  "completion_percentage": 30,
  "what_was_done": "搜索了音频格式资料，设计了项目架构",
  "what_is_missing": "没有实际编写代码、创建项目文件",
  "next_steps": [
    {
      "description": "根据设计方案，创建 C++ 项目结构和主要源代码文件",
      "tools_needed": ["execute_command"],
      "reason": "需要创建实际的代码文件"
    },
    {
      "description": "编写 WAV 解析模块代码",
      "tools_needed": ["execute_command"],
      "reason": "需要实现 WAV 文件读取功能"
    }
  ]
}
```"""


@dataclass
class SubtaskSpec:
    """Specification for a subtask."""
    id: str
    description: str
    tools_needed: list[str]
    priority: int = 0  # Higher number = higher priority (executed first among parallel tasks)
    depends_on: list[str] | None = None  # List of subtask IDs that must complete first


@dataclass
class SubtaskResult:
    """Result from a SubAgent execution."""
    subtask_id: str
    description: str
    result: str
    success: bool
    error: str | None = None


@dataclass
class CompletionEvaluation:
    """Result of task completion evaluation."""
    is_completed: bool
    completion_percentage: int
    what_was_done: str
    what_is_missing: str
    next_steps: list[dict[str, Any]]  # List of {"description": ..., "tools_needed": ..., "reason": ...}


class OwnerAgent(BaseAgent):
    """OwnerAgent - orchestrates task decomposition and execution.

    This agent:
    - Receives a task from ResidentAgent
    - Decomposes the task into subtasks
    - Creates and runs WorkerAgents in parallel
    - Synthesizes results into a final response
    - Has a short lifecycle (destroyed after task completion)
    - Persists to database for tracking
    """

    def __init__(
        self,
        task_id: str | None = None,
        parent_agent_id: str | None = None,
        timeout: float | None = None,  # None means use config default
        max_subagents: int = 5,
    ) -> None:
        """Initialize the OwnerAgent.

        Args:
            task_id: Associated task ID.
            parent_agent_id: Parent agent (ResidentAgent) ID.
            timeout: Total execution timeout in seconds. None uses config default.
            max_subagents: Maximum number of WorkerAgents to create.
        """
        # Initialize BaseAgent
        super().__init__(
            agent_id=None,  # Will be set after persist
            name="OwnerAgent",
            agent_type=AgentType.OWNER,
            parent_agent_id=parent_agent_id,
            task_id=task_id,
            timeout=timeout or 600,
        )

        # OwnerAgent specific attributes
        self._timeout = timeout  # Will be resolved in execute()
        self._max_subagents = max_subagents
        self._workers: list[tuple[SubtaskSpec, WorkerAgent]] = []
        self._completed = asyncio.Event()

        # Override timeout manager with OwnerAgent-specific settings
        self._timeout_manager = TimeoutManager(
            base_timeout=600,  # 10 minutes base
            max_extension=0,  # No limit - extend as long as there's progress
            min_progress_interval=60,
        )

        # Task context for multi-turn conversation support
        # Stores the original task request to provide context for evaluation and worker responses
        self._task_context: str = ""

    async def persist(self) -> str:
        """Persist the agent to database with OwnerAgent-specific logic.

        Override BaseAgent.persist() to also update task.owner_agent_id.

        Returns:
            Agent ID.
        """
        # Call parent's persist logic
        await super().persist()

        # OwnerAgent-specific: Update task with owner_agent_id
        if self._task_id:
            async with db_manager.session() as session:
                await task_service.update_task(
                    session, self._task_id, owner_agent_id=self._id
                )
                logger.info(f"Updated task {self._task_id} with owner_agent_id={self._id}")

        return self._id

    async def execute(self, user_request: str) -> str:
        """Execute a task by decomposing and orchestrating WorkerAgents.

        Supports iterative execution: if task is not completed after first round,
        will generate follow-up subtasks and continue until completion or max iterations.

        Args:
            user_request: The user's task request.

        Returns:
            Final synthesized response.
        """
        # Persist agent to database first
        if not self._id:
            await self.persist()

        logger.info(f"OwnerAgent {self._id} starting task: {user_request[:100]}...")
        await self._update_status(AgentStatus.RUNNING)

        # Store task context for multi-turn support (evaluation and worker responses)
        self._task_context = user_request

        # Resolve base timeout from config
        # Note: get_float returns None when config value is -1 (unlimited)
        base_timeout = self._timeout or await config_service.get_float("owner_task_timeout", 600.0)
        self._timeout_manager._base_timeout = int(base_timeout) if base_timeout is not None else None
        self._timeout_manager.start()

        # Get max iterations from config (default 5, -1 means unlimited)
        max_iterations = await config_service.get_int("owner_max_iterations", 5)
        # None means unlimited, use a very large number (effectively unlimited)
        effective_max_iterations = max_iterations if max_iterations is not None else 9999
        current_iteration = 0

        # Track all results across iterations
        all_results: list[SubtaskResult] = []

        try:
            # Check if terminated before starting
            if await self._check_terminated():
                return "任务已被终止"

            # Initial task decomposition
            subtasks = await self._decompose_task(user_request)
            self._timeout_manager.record_progress("decompose", f"Decomposed into {len(subtasks)} subtasks")
            logger.info(f"OwnerAgent {self._id} decomposed into {len(subtasks)} subtasks")

            if not subtasks:
                await self._update_status(AgentStatus.ERROR)
                return "抱歉，我无法分析这个任务。请换种方式描述一下？"

            # Iterative execution loop
            while current_iteration < effective_max_iterations:
                current_iteration += 1
                logger.info(f"OwnerAgent {self._id} starting iteration {current_iteration}/{max_iterations if max_iterations else 'unlimited'}")

                # Check termination before executing subtasks
                if await self._check_terminated():
                    return "任务已被终止"

                # Execute current batch of subtasks
                results = await self._execute_subtasks(subtasks, user_request)
                all_results.extend(results)
                self._timeout_manager.record_progress(
                    f"execute_iter_{current_iteration}",
                    f"Executed {len(results)} subtasks in iteration {current_iteration}"
                )
                logger.info(f"OwnerAgent {self._id} iteration {current_iteration} got {len(results)} results")

                # Check termination before evaluation
                if await self._check_terminated():
                    return "任务已被终止"

                # Evaluate task completion
                evaluation = await self._evaluate_completion(user_request, all_results)
                logger.info(
                    f"OwnerAgent {self._id} completion evaluation: "
                    f"{evaluation.completion_percentage}% complete, is_completed={evaluation.is_completed}"
                )

                # If completed or no next steps, break
                if evaluation.is_completed:
                    logger.info(f"OwnerAgent {self._id} task completed after {current_iteration} iterations")
                    break

                if not evaluation.next_steps:
                    logger.info(f"OwnerAgent {self._id} no next steps suggested, proceeding to synthesis")
                    break

                # Check if we have more iterations
                if max_iterations is not None and current_iteration >= max_iterations:
                    logger.warning(
                        f"OwnerAgent {self._id} reached max iterations ({max_iterations}), "
                        f"task only {evaluation.completion_percentage}% complete"
                    )
                    # Add a note about incomplete task to results for better synthesis
                    all_results.append(SubtaskResult(
                        subtask_id="_incomplete_note",
                        description="[系统提示] 达到最大迭代次数，任务可能未完全完成",
                        result=f"任务完成度: {evaluation.completion_percentage}%\n"
                               f"已完成: {evaluation.what_was_done}\n"
                               f"未完成: {evaluation.what_is_missing}",
                        success=False,
                        error=None,
                    ))
                    break

                # Generate follow-up subtasks from next_steps
                # Use iteration number and index to create unique IDs
                subtasks = []
                for i, step in enumerate(evaluation.next_steps):
                    subtasks.append(SubtaskSpec(
                        id=f"iter{current_iteration}_step{i}",
                        description=step.get("description", ""),
                        tools_needed=step.get("tools_needed", ["execute_command"]),
                        priority=0,
                        depends_on=[],  # Follow-up tasks don't have dependencies
                    ))
                logger.info(f"OwnerAgent {self._id} generated {len(subtasks)} follow-up subtasks from next_steps")

                # If no subtasks were generated but task is not complete, create a default continuation
                if not subtasks:
                    logger.warning(f"OwnerAgent {self._id} no follow-up subtasks generated but task incomplete, creating default continuation")
                    subtasks.append(SubtaskSpec(
                        id=f"iter{current_iteration}_continue",
                        description=f"继续执行任务。根据之前的执行结果，完成以下工作：{evaluation.what_is_missing}",
                        tools_needed=["execute_command"],
                        priority=0,
                        depends_on=[],
                    ))

            # Final synthesis
            if await self._check_terminated():
                return "任务已被终止"

            final_response = await self._synthesize_results(user_request, all_results)

            await self._update_status(AgentStatus.DONE)
            self._completed.set()
            return final_response

        except asyncio.TimeoutError:
            current_timeout = self._timeout_manager.get_current_timeout()
            logger.warning(f"OwnerAgent {self._id} timed out after {current_timeout}s")
            await self._update_status(AgentStatus.ERROR)
            return f"任务执行超时（{current_timeout}秒）。请简化任务或稍后重试。"

        except Exception as e:
            logger.exception(f"OwnerAgent {self._id} error: {e}")
            await self._update_status(AgentStatus.ERROR)
            return f"执行任务时出错: {str(e)}"

    async def _decompose_task(self, user_request: str) -> list[SubtaskSpec]:
        """Decompose a task into subtasks using LLM.

        Args:
            user_request: The user's task request.

        Returns:
            List of subtask specifications.
        """
        from backend.services.llm_service import llm_service

        # Load system prompt from database (type-level default) or use code default
        system_prompt = OWNER_AGENT_SYSTEM_PROMPT
        try:
            async with db_manager.session() as session:
                type_settings = await agent_settings_service.get_type_settings(
                    session, AgentType.OWNER
                )
                if type_settings and type_settings.system_prompt:
                    system_prompt = type_settings.system_prompt
                    logger.info("Loaded OWNER system prompt from database")
        except Exception as e:
            logger.warning(f"Failed to load OWNER prompt from database: {e}")

        # Inject current date/time into system prompt
        datetime_str = get_current_datetime_str()
        full_system_prompt = f"{datetime_str}\n\n{system_prompt}"

        messages = [
            ChatMessage(role="system", content=full_system_prompt),
            ChatMessage(role="user", content=f"请分析以下任务并拆解为子任务:\n\n{user_request}"),
        ]

        try:
            response = await llm_service.complete(messages)
            content = response.content

            # Parse subtasks and plan from LLM response
            subtasks, plan_data = self._parse_subtasks_with_plan(content)

            # Check if dependency confirmation is enabled
            confirm_deps = await config_service.get_bool("owner_confirm_dependencies", True)
            if confirm_deps and len(subtasks) > 1:
                # Second stage: confirm dependencies
                subtasks = await self._confirm_dependencies(subtasks)
                # Update plan_data with confirmed dependencies
                plan_data["subtasks"] = [
                    {
                        "id": st.id,
                        "description": st.description,
                        "tools_needed": st.tools_needed,
                        "priority": st.priority,
                        "depends_on": st.depends_on,
                    }
                    for st in subtasks
                ]

            # Save plan to task if we have a task_id
            if self._task_id and plan_data:
                try:
                    async with db_manager.session() as session:
                        await task_service.set_plan(session, self._task_id, plan_data)
                        logger.info(f"Saved plan to task {self._task_id}")
                except Exception as plan_err:
                    logger.warning(f"Failed to save plan to task: {plan_err}")

            # Limit number of subtasks
            return subtasks[:self._max_subagents]

        except Exception as e:
            logger.exception(f"Error decomposing task: {e}")
            # Fallback: create a single subtask with the full request
            return [SubtaskSpec(
                id="1",
                description=user_request,
                tools_needed=["web_search", "web_fetch"],
            )]

    async def _confirm_dependencies(self, subtasks: list[SubtaskSpec]) -> list[SubtaskSpec]:
        """Confirm and update dependencies for subtasks via second LLM call.

        This is a second-stage confirmation that focuses specifically on
        dependency and priority analysis.

        Args:
            subtasks: List of subtask specifications from first stage.

        Returns:
            Updated subtask specifications with confirmed dependencies.
        """
        from backend.services.llm_service import llm_service

        # Build subtask list for the prompt
        subtask_list = "\n".join([
            f"- {st.id}: {st.description[:100]}{'...' if len(st.description) > 100 else ''}"
            for st in subtasks
        ])

        # Load dependency confirmation prompt from database or use default
        dep_prompt = DEPENDENCY_CONFIRMATION_PROMPT
        try:
            async with db_manager.session() as session:
                # Check for custom dependency prompt in system config
                custom_prompt = await config_service.get("owner_dependency_prompt", "")
                if custom_prompt:
                    dep_prompt = custom_prompt
                    logger.info("Using custom dependency confirmation prompt")
        except Exception as e:
            logger.warning(f"Failed to load dependency prompt config: {e}")

        messages = [
            ChatMessage(role="system", content=dep_prompt),
            ChatMessage(role="user", content=f"请分析以下子任务的依赖关系和优先级:\n\n{subtask_list}"),
        ]

        try:
            response = await llm_service.complete(messages)
            content = response.content

            # Parse dependency information
            dep_data = self._parse_dependency_response(content)

            if dep_data:
                # Update subtasks with confirmed dependencies
                dep_map = {d["id"]: d for d in dep_data}
                for st in subtasks:
                    if st.id in dep_map:
                        confirmed = dep_map[st.id]
                        st.depends_on = confirmed.get("depends_on", st.depends_on)
                        st.priority = confirmed.get("priority", st.priority)
                        logger.info(
                            f"Subtask {st.id}: depends_on={st.depends_on}, priority={st.priority}"
                        )
            else:
                logger.warning("Failed to parse dependency response, using original values")

        except Exception as e:
            logger.warning(f"Dependency confirmation failed: {e}, using original values")

        return subtasks

    def _parse_dependency_response(self, content: str) -> list[dict] | None:
        """Parse dependency confirmation response from LLM.

        Args:
            content: LLM response content.

        Returns:
            List of dependency info dicts, or None if parsing failed.
        """
        # Try to find JSON in the response
        json_match = None
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_match = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_match = content[start:end].strip()
        elif "{" in content and "dependencies" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            if end > start:
                json_match = content[start:end]

        if json_match:
            try:
                data = json.loads(json_match)
                return data.get("dependencies", [])
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse dependency JSON: {e}")

        return None

    def _parse_subtasks(self, content: str) -> list[SubtaskSpec]:
        """Parse subtasks from LLM response.

        Args:
            content: LLM response content.

        Returns:
            List of subtask specifications.
        """
        subtasks, _ = self._parse_subtasks_with_plan(content)
        return subtasks

    def _try_repair_json(self, json_str: str) -> str:
        """Attempt to repair common JSON format errors.

        Args:
            json_str: Potentially malformed JSON string.

        Returns:
            Repaired JSON string (best effort).
        """
        import re

        repaired = json_str

        # Fix 1: Remove duplicate opening braces in objects (e.g., {{ -> {)
        # This handles the case where LLM outputs { { "id": "2" } }
        repaired = re.sub(r'\{\s*\{', '{', repaired)

        # Fix 2: Remove duplicate closing braces (e.g., }} -> })
        repaired = re.sub(r'\}\s*\}', '}', repaired)

        # Fix 3: Fix trailing commas before closing brackets/braces
        repaired = re.sub(r',\s*}', '}', repaired)
        repaired = re.sub(r',\s*\]', ']', repaired)

        # Fix 4: Remove multiple consecutive commas
        repaired = re.sub(r',+', ',', repaired)

        # Fix 5: Fix missing commas between array elements
        # This is complex and may introduce issues, so we skip it

        # Fix 6: Remove non-JSON text before/after the main object
        # Find the outermost balanced braces
        if repaired.count('{') > 0 and repaired.count('}') > 0:
            first_brace = repaired.find('{')
            last_brace = repaired.rfind('}')
            if first_brace >= 0 and last_brace > first_brace:
                repaired = repaired[first_brace:last_brace + 1]

        return repaired

    def _extract_subtasks_from_malformed_json(self, json_str: str) -> list[dict]:
        """Extract subtask objects from malformed JSON using regex patterns.

        This is a fallback when JSON parsing completely fails.

        Args:
            json_str: Malformed JSON string.

        Returns:
            List of extracted subtask dictionaries.
        """
        import re

        subtasks = []

        # Pattern to match subtask objects with id, description, tools_needed, etc.
        # This handles cases where JSON is malformed but individual objects are parseable
        pattern = r'\{\s*"id"\s*:\s*"?(\w+)"?\s*,\s*"description"\s*:\s*"([^"]*(?:\\.[^"]*)*)"\s*(?:,\s*"tools_needed"\s*:\s*\[([^\]]*)\])?'

        matches = re.findall(pattern, json_str, re.DOTALL)

        for match in matches:
            subtask_id = match[0]
            description = match[1].replace('\\"', '"').replace('\\n', '\n')

            # Parse tools_needed if present
            tools_str = match[2] if len(match) > 2 else ""
            tools_needed = []
            if tools_str:
                tools_needed = re.findall(r'"([^"]*)"', tools_str)

            if description:  # Only add if we have a description
                subtasks.append({
                    "id": subtask_id,
                    "description": description,
                    "tools_needed": tools_needed if tools_needed else ["web_search", "web_fetch"],
                    "priority": 0,
                    "depends_on": []
                })

        return subtasks

    def _parse_subtasks_with_plan(self, content: str) -> tuple[list[SubtaskSpec], dict[str, Any] | None]:
        """Parse subtasks and plan data from LLM response.

        Enhanced with JSON repair and regex fallback for robustness.

        Args:
            content: LLM response content.

        Returns:
            Tuple of (list of subtask specifications, plan data dict or None).
        """
        subtasks = []
        plan_data = None

        # Try to find JSON in the response
        json_match = None
        # Look for JSON code block
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_match = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_match = content[start:end].strip()
        # Try to find raw JSON object
        elif "{" in content and "subtasks" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            if end > start:
                json_match = content[start:end]

        if json_match:
            # Try direct parsing first
            data = None
            try:
                data = json.loads(json_match)
            except json.JSONDecodeError as e:
                logger.warning(f"Initial JSON parse failed: {e}, attempting repair...")

                # Try to repair the JSON
                repaired_json = self._try_repair_json(json_match)
                try:
                    data = json.loads(repaired_json)
                    logger.info("JSON repair successful")
                except json.JSONDecodeError as e2:
                    logger.warning(f"JSON repair failed: {e2}, trying regex extraction...")

                    # Last resort: extract subtasks using regex
                    extracted = self._extract_subtasks_from_malformed_json(json_match)
                    if extracted:
                        data = {"subtasks": extracted}
                        logger.info(f"Extracted {len(extracted)} subtasks using regex fallback")

            if data:
                # Store the full plan data (including analysis)
                plan_data = {
                    "analysis": data.get("analysis", ""),
                    "subtasks": []
                }
                for item in data.get("subtasks", []):
                    # Validate required fields
                    if not isinstance(item, dict):
                        continue
                    description = item.get("description", "")
                    if not description:
                        continue

                    subtask_spec = SubtaskSpec(
                        id=str(item.get("id", len(subtasks) + 1)),
                        description=description,
                        tools_needed=item.get("tools_needed", ["web_search", "web_fetch"]) or ["web_search", "web_fetch"],
                        priority=item.get("priority", 0) or 0,
                        depends_on=item.get("depends_on", []) or [],
                    )
                    subtasks.append(subtask_spec)
                    # Add to plan data
                    plan_data["subtasks"].append({
                        "id": subtask_spec.id,
                        "description": subtask_spec.description,
                        "tools_needed": subtask_spec.tools_needed,
                        "priority": subtask_spec.priority,
                        "depends_on": subtask_spec.depends_on,
                    })

        # If no subtasks parsed, create a default one with proper task description
        if not subtasks:
            logger.warning("No subtasks parsed from LLM response, using intelligent fallback")
            # Instead of using entire LLM response, extract just the user request portion
            # This typically appears at the beginning or in a specific pattern
            fallback_desc = self._extract_fallback_description(content)
            subtasks.append(SubtaskSpec(
                id="1",
                description=fallback_desc,
                tools_needed=["web_search", "web_fetch", "execute_command"],
                priority=0,
                depends_on=[],
            ))
            plan_data = None  # No valid plan for fallback

        return subtasks, plan_data

    def _extract_fallback_description(self, content: str) -> str:
        """Extract a meaningful task description for fallback subtask.

        Args:
            content: The full LLM response content.

        Returns:
            A concise task description.
        """
        # Try to extract the analysis or summary from the content
        import re

        # Look for analysis section
        analysis_match = re.search(r'"analysis"\s*:\s*"([^"]+)"', content)
        if analysis_match:
            return f"请完成以下任务：{analysis_match.group(1)[:500]}"

        # Look for the original user request pattern
        if "用户任务" in content or "用户请求" in content:
            lines = content.split('\n')
            for i, line in enumerate(lines):
                if "用户任务" in line or "用户请求" in line:
                    # Return next few lines as context
                    context = '\n'.join(lines[i:i+3])
                    return f"请完成以下任务：{context[:500]}"

        # Fallback: use first meaningful sentence
        sentences = re.split(r'[。\n]', content)
        for sentence in sentences:
            if len(sentence) > 20 and not sentence.startswith('{') and not sentence.startswith('```'):
                return f"请完成以下任务：{sentence[:500]}"

        return "请分析并完成用户的任务请求"

    def _build_worker_context(self) -> str:
        """Build system context for workers.

        This context includes important information that workers need
        to properly execute tasks, such as working directory and project paths.

        Returns:
            System context string to be prepended to task descriptions.
        """
        import os

        context_parts = [
            "【系统上下文 - 请在执行任务时注意】",
            f"当前工作目录: {os.getcwd()}",
        ]

        # Add project root if we're in a known project structure
        cwd = os.getcwd()
        if "longclaw" in cwd:
            context_parts.append(f"项目根目录: {cwd}")
            context_parts.append("注意: LongClaw 项目位于当前目录的 longclaw 子目录下")
            context_parts.append("如果需要操作 LongClaw 项目文件，请使用完整路径")

        context_parts.append("=" * 40)

        return "\n".join(context_parts)

    def _validate_task_context(self, spec: SubtaskSpec, description: str) -> bool:
        """Validate that the task description has sufficient context for execution.

        Args:
            spec: The subtask specification.
            description: The task description.

        Returns:
            True if context is sufficient, False otherwise.
        """
        issues = []

        # Check for execute_command tool usage
        if "execute_command" in spec.tools_needed:
            # These keywords suggest the task needs file/directory context
            context_keywords = [
                "目录", "文件夹", "路径", "项目", "文件",
                "path", "directory", "folder", "project", "file",
                "编译", "运行", "执行", "创建", "修改",
                "run", "compile", "execute", "create", "modify"
            ]
            has_context = any(kw in description for kw in context_keywords)
            if not has_context:
                issues.append(
                    f"Subtask {spec.id} uses execute_command but description lacks "
                    "file/directory context keywords"
                )

        # Check description length (very short descriptions likely lack context)
        if len(description) < 20:
            issues.append(
                f"Subtask {spec.id} description is very short ({len(description)} chars), "
                "likely lacks sufficient context"
            )

        if issues:
            logger.warning(" | ".join(issues))
            return False

        return True

    async def _handle_worker_questions(self) -> None:
        """Handle any pending clarification questions from workers.

        This method checks for QUESTION messages from workers and sends
        TEXT responses back to them. Uses LLM to generate intelligent
        context-aware responses based on the task goal and worker question.

        Called when Owner is allocated with WORKER_WAITING_OWNER priority.
        """
        try:
            async with db_manager.session() as session:
                from sqlalchemy import select, and_

                # Find QUESTION messages sent to this Owner
                result = await session.execute(
                    select(Message)
                    .where(
                        and_(
                            Message.receiver_id == self._id,
                            Message.receiver_type == ReceiverType.OWNER,
                            Message.message_type == MessageType.QUESTION
                        )
                    )
                    .order_by(Message.created_at.asc())
                    .limit(10)
                )
                questions = list(result.scalars().all())

                for question in questions:
                    worker_id = question.sender_id
                    worker_name = "Worker"
                    question_content = question.content or ""

                    logger.info(f"Owner handling question from {worker_name} ({worker_id}): {question_content[:100]}...")

                    # Load the full conversation context for this worker
                    # to generate a context-aware response
                    from sqlalchemy import select as sa_select
                    conv_result = await session.execute(
                        sa_select(Message)
                        .where(
                            and_(
                                Message.sender_id == worker_id,
                                Message.task_id == self._task_id,
                            )
                        )
                        .order_by(Message.created_at.asc())
                    )
                    worker_messages = list(conv_result.scalars().all())

                    # Build conversation history for LLM
                    conversation_context = self._build_evaluation_context(
                        question_content,
                        [m.content for m in worker_messages if m.content],
                        is_worker_question=True
                    )

                    # Generate intelligent response using LLM
                    response_content = await self._generate_worker_response(
                        worker_id=worker_id,
                        worker_question=question_content,
                        conversation_context=conversation_context,
                    )

                    # Send TEXT response to worker
                    await message_service.create_message(
                        session,
                        sender_type=SenderType.OWNER,
                        sender_id=self._id,
                        receiver_type=ReceiverType.WORKER,
                        receiver_id=worker_id,
                        content=response_content,
                        message_type=MessageType.TEXT,
                        task_id=self._task_id,
                    )
                    logger.info(f"Owner sent LLM-generated response to {worker_name} ({worker_id})")

        except Exception as e:
            logger.warning(f"Error handling worker questions: {e}")

    async def _generate_worker_response(
        self,
        worker_id: str,
        worker_question: str,
        conversation_context: str,
    ) -> str:
        """Generate an intelligent response to a worker's question using LLM.

        This enables multi-turn conversation between Owner and Workers,
        so Owner can provide context-aware guidance based on the task goal
        and the worker's specific question.

        Args:
            worker_id: ID of the worker asking the question.
            worker_question: The question from the worker.
            conversation_context: Context about the task and prior conversation.

        Returns:
            Generated response to send to the worker.
        """
        from backend.services.llm_service import llm_service

        datetime_str = get_current_datetime_str()
        prompt = f"""{datetime_str}

你是一个任务管理Agent，需要回复Worker的问题。Worker正在执行子任务时遇到了需要澄清的问题。

{conversation_context}

【Worker的问题】
{worker_question}

请回复Worker的问题，提供足够的上下文和指导。回复要简洁、准确，帮助Worker继续执行任务。
如果Worker询问的是任务目标相关的问题，请结合原始任务目标回答。
如果Worker询问的是操作相关的问题，请提供具体的指导。"""

        messages = [
            ChatMessage(role="system", content="你是一个任务管理Agent，负责协调Worker执行任务。"),
            ChatMessage(role="user", content=prompt),
        ]

        try:
            response = await llm_service.complete(messages)
            return response.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate LLM response for worker: {e}")
            # Fallback to simple response
            return (
                f"收到你的问题：{worker_question}\n\n"
                f"请根据任务目标继续执行。如果确实无法执行，请说明原因并报告任务失败。"
            )

    async def _execute_subtasks(self, subtasks: list[SubtaskSpec], user_request: str = "") -> list[SubtaskResult]:
        """Execute subtasks with dependency support and context passing.

        Creates Subtask records in DB and tracks execution.
        Supports both parallel and sequential execution based on dependencies.
        Workers are created lazily when their dependencies are satisfied,
        and receive context from completed dependency tasks.

        Args:
            subtasks: List of subtask specifications.
            user_request: The original user request for context.

        Returns:
            List of subtask results.
        """
        # Create Subtask records in DB (but NOT workers yet - they're created lazily)
        self._workers = []
        db_subtask_ids: dict[str, str] = {}  # spec.id -> db_subtask_id
        spec_by_id: dict[str, SubtaskSpec] = {}  # Map for quick lookup

        if self._task_id:
            async with db_manager.session() as session:
                for i, spec in enumerate(subtasks):
                    # Create Subtask in DB with priority and dependencies
                    db_subtask = await task_service.create_subtask(
                        session,
                        task_id=self._task_id,
                        title=spec.description[:100] + ("..." if len(spec.description) > 100 else ""),
                        description=spec.description,
                        order_index=i,
                        priority=spec.priority,
                        depends_on=spec.depends_on,
                    )
                    db_subtask_ids[spec.id] = db_subtask.id
                    spec_by_id[spec.id] = spec
                    logger.info(f"Created subtask {db_subtask.id} for spec {spec.id}")

        for spec in subtasks:
            spec_by_id[spec.id] = spec

        # Execute with dependency support and context passing
        results: dict[str, SubtaskResult] = {}
        completed_ids: set[str] = set()

        async def run_subtask(spec: SubtaskSpec) -> None:
            """Run a single subtask with context from dependencies and retry on failure."""
            # Get system context that all workers need (working directory, project paths, etc.)
            system_context = self._build_worker_context()

            # Build context from dependency results
            context_parts = []
            if spec.depends_on:
                for dep_id in spec.depends_on:
                    if dep_id in results:
                        dep_result = results[dep_id]
                        if dep_result.success:
                            context_parts.append(f"【依赖任务 {dep_id} 的结果】\n{dep_result.result}")
                        else:
                            context_parts.append(f"【依赖任务 {dep_id} 失败】\n{dep_result.error}")

            # Build enhanced task description with system context and dependency context
            description_parts = [spec.description]

            # Add system context first
            description_parts.append(f"\n{system_context}\n")

            # Add original user request for context - CRITICAL for workers to understand the overall goal
            if user_request:
                description_parts.append(f"\n【原始用户请求】\n{user_request}\n")

            # Add dependency context if available
            if context_parts:
                description_parts.append(f"\n{'='*40}\n以下是依赖任务的执行结果，请在执行时参考：\n\n" + "\n\n".join(context_parts))
                logger.info(f"Subtask {spec.id} enhanced with context from dependencies: {spec.depends_on}")
            else:
                logger.info(f"Subtask {spec.id} has no dependencies, executing directly")

            enhanced_description = "\n".join(description_parts)

            # Validate task context before creating worker
            # This warns if the description seems to lack sufficient context
            has_sufficient_context = self._validate_task_context(spec, enhanced_description)
            if not has_sufficient_context:
                logger.warning(
                    f"Subtask {spec.id} may have insufficient context. "
                    f"Consider adding more details to the task description."
                )

            # Try execution with retry (max 2 attempts)
            max_attempts = 2
            result = None
            worker = None

            for attempt in range(1, max_attempts + 1):
                # Create worker lazily with enhanced description
                worker_name = f"Worker-{spec.id}" + (f"-retry{attempt}" if attempt > 1 else "")
                worker = WorkerAgent(
                    name=worker_name,
                    task_id=self._task_id,
                    subtask_id=db_subtask_ids.get(spec.id),
                    parent_agent_id=self._id,
                    description=enhanced_description,
                    tools=spec.tools_needed,
                    timeout=None,  # Use config default
                )
                self._workers.append((spec, worker))

                # Run the worker
                result = await self._run_worker(spec, worker, enhanced_description, attempt)

                if result.success:
                    logger.info(f"Subtask {spec.id} completed successfully on attempt {attempt}")
                    break
                else:
                    logger.warning(f"Subtask {spec.id} failed on attempt {attempt}/{max_attempts}: {result.error[:100] if result.error else 'unknown error'}")
                    if attempt < max_attempts:
                        logger.info(f"Retrying subtask {spec.id}...")

            results[spec.id] = result
            completed_ids.add(spec.id)
            logger.info(f"Subtask {spec.id} final result: success={result.success}")

        # Build dependency graph and execute in waves
        # A wave consists of all tasks whose dependencies are satisfied
        remaining_specs = list(subtasks)  # [spec, ...]

        while remaining_specs:
            # Check if agent was terminated
            if await self._check_terminated():
                logger.info(f"OwnerAgent {self._id} terminated, stopping execution")
                # Return empty results for remaining specs
                for spec in remaining_specs:
                    results[spec.id] = SubtaskResult(
                        subtask_id=spec.id,
                        description=spec.description,
                        result="",
                        success=False,
                        error="Task terminated by user",
                    )
                break

            # Handle any pending questions from workers before starting new wave
            # This allows Owner to respond to workers that need clarification
            await self._handle_worker_questions()

            # Find tasks whose dependencies are all satisfied
            ready = [
                spec for spec in remaining_specs
                if all(dep_id in completed_ids for dep_id in (spec.depends_on or []))
            ]

            if not ready:
                # This shouldn't happen with valid dependencies, but handle it
                logger.error("Circular dependency detected or invalid depends_on")
                # Mark remaining as failed
                for spec in remaining_specs:
                    results[spec.id] = SubtaskResult(
                        subtask_id=spec.id,
                        description=spec.description,
                        result="",
                        success=False,
                        error="Circular dependency or invalid dependency reference",
                    )
                break

            # Execute ready tasks in parallel
            logger.info(f"Executing wave of {len(ready)} subtasks: {[s.id for s in ready]}")
            await asyncio.gather(*[run_subtask(spec) for spec in ready])

            # Remove completed tasks from remaining
            remaining_specs = [s for s in remaining_specs if s.id not in completed_ids]

        # Return results in original order
        return [results.get(spec.id, SubtaskResult(
            subtask_id=spec.id,
            description=spec.description,
            result="",
            success=False,
            error="Result not found",
        )) for spec in subtasks]

    async def _update_subtask_status(
        self,
        subtask_id: str,
        status: SubtaskStatus,
        summary: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update subtask status in database.

        Args:
            subtask_id: Database subtask ID.
            status: New status.
            summary: Optional summary.
            error: Optional error message.
        """
        try:
            async with db_manager.session() as session:
                result_data = {"error": error} if error else None
                await task_service.update_subtask_status(
                    session,
                    subtask_id,
                    status,
                    summary=summary,
                    result=result_data,
                )
        except Exception as e:
            logger.exception(f"Failed to update subtask {subtask_id} status: {e}")

    async def _run_worker(
        self,
        spec: SubtaskSpec,
        worker: WorkerAgent,
        enhanced_description: str | None = None,
        attempt: int = 1,
    ) -> SubtaskResult:
        """Run a single WorkerAgent.

        Args:
            spec: Subtask specification.
            worker: WorkerAgent instance.
            enhanced_description: Task description with dependency context included.
            attempt: Current attempt number (1-based).

        Returns:
            Subtask result.
        """
        from backend.services.message_service import message_service
        from backend.models.message import SenderType, ReceiverType, MessageType

        # Use enhanced description if provided, otherwise use spec description
        task_to_execute = enhanced_description or spec.description

        # Build attempt suffix for messages
        attempt_suffix = f" (第{attempt}次尝试)" if attempt > 1 else ""

        # Persist worker first to get its ID for message recording
        await worker._persist()

        # Record message: Owner -> Worker (task dispatch)
        # Store full description for complete traceability
        if self._task_id:
            try:
                async with db_manager.session() as session:
                    await message_service.create_message(
                        session,
                        sender_type=SenderType.OWNER,
                        sender_id=self._id,
                        receiver_type=ReceiverType.WORKER,
                        receiver_id=worker.id,
                        content=f"[{worker._name}] 执行子任务 #{spec.id}{attempt_suffix}:\n\n{spec.description}",
                        message_type=MessageType.TASK,
                        task_id=self._task_id,
                        subtask_id=worker._subtask_id,
                    )
            except Exception as msg_err:
                logger.warning(f"Failed to record dispatch message: {msg_err}")

        try:
            result = await worker.execute(task_to_execute)

            # WorkerAgent.execute() handles all exceptions internally and sets its own status.
            # We check the final worker status to determine success.
            is_success = worker.status != AgentStatus.ERROR

            # Record message: Worker -> Owner (task result)
            # Store full result, frontend will handle truncation/expand
            if self._task_id:
                try:
                    async with db_manager.session() as session:
                        status_text = "✅ 完成" if is_success else "❌ 失败"
                        # Record full result for complete traceability
                        await message_service.create_message(
                            session,
                            sender_type=SenderType.WORKER,
                            sender_id=worker.id,
                            receiver_type=ReceiverType.OWNER,
                            receiver_id=self._id,
                            content=f"[{worker._name}] 子任务 #{spec.id} {status_text}{attempt_suffix}\n\n{result}",
                            message_type=MessageType.REPORT if is_success else MessageType.ERROR,
                            task_id=self._task_id,
                            subtask_id=worker._subtask_id,
                        )
                except Exception as msg_err:
                    logger.warning(f"Failed to record result message: {msg_err}")

            # Note: WorkerAgent already updates subtask status internally (COMPLETED on success, FAILED on error)
            # We don't need to override the status here - the backup logic was causing BUG-4

            return SubtaskResult(
                subtask_id=spec.id,
                description=spec.description,
                result=result,
                success=is_success,
                error=None if is_success else result,  # Use result as error message if failed
            )
        except Exception as e:
            logger.exception(f"WorkerAgent {worker.id} failed: {e}")

            # Record error message - store full error for debugging
            if self._task_id:
                try:
                    async with db_manager.session() as session:
                        await message_service.create_message(
                            session,
                            sender_type=SenderType.WORKER,
                            sender_id=worker.id,
                            receiver_type=ReceiverType.OWNER,
                            receiver_id=self._id,
                            content=f"[{worker._name}] 子任务 #{spec.id} ❌ 异常{attempt_suffix}\n\n{str(e)}",
                            message_type=MessageType.ERROR,
                            task_id=self._task_id,
                            subtask_id=worker._subtask_id,
                        )
                except Exception as msg_err:
                    logger.warning(f"Failed to record error message: {msg_err}")

            # Update subtask status to FAILED on error
            if worker._subtask_id:
                try:
                    await self._update_subtask_status(
                        worker._subtask_id,
                        SubtaskStatus.FAILED,
                        error=str(e),
                    )
                except Exception as update_error:
                    logger.warning(f"Failed to update subtask status on error: {update_error}")

            return SubtaskResult(
                subtask_id=spec.id,
                description=spec.description,
                result="",
                success=False,
                error=str(e),
            )

    async def _get_owner_worker_conversation(self) -> str:
        """Load recent conversation history between Owner and Workers.

        This enables multi-turn context for evaluation - the Owner can see
        what questions Workers asked and what answers Owner provided.

        Returns:
            Formatted conversation history string.
        """
        if not self._task_id:
            return ""

        try:
            async with db_manager.session() as session:
                from sqlalchemy import select, or_, and_, asc

                # Get all messages related to this task involving Owner or Workers
                result = await session.execute(
                    select(Message)
                    .where(
                        and_(
                            Message.task_id == self._task_id,
                            or_(
                                Message.sender_type == SenderType.OWNER,
                                Message.sender_type == SenderType.WORKER,
                            )
                        )
                    )
                    .order_by(asc(Message.created_at))
                    .limit(50)
                )
                messages = list(result.scalars().all())

                if not messages:
                    return ""

                # Format conversation
                lines = []
                for msg in messages[-20:]:  # Last 20 messages
                    sender = "Owner" if msg.sender_type == SenderType.OWNER else "Worker"
                    content = msg.content or ""
                    if len(content) > 500:
                        content = content[:500] + "..."
                    lines.append(f"{sender}: {content}")

                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Failed to load owner-worker conversation: {e}")
            return ""

    async def _evaluate_completion(
        self,
        user_request: str,
        results: list[SubtaskResult],
    ) -> CompletionEvaluation:
        """Evaluate if the task is completed based on results.

        Args:
            user_request: Original user request.
            results: List of subtask results from execution.

        Returns:
            CompletionEvaluation with completion status and next steps if needed.
        """
        from backend.services.llm_service import llm_service

        # Build evaluation context using the shared helper
        conversation_history = self._get_owner_worker_conversation()
        context_parts = []

        # Add task context (includes conversation history from ResidentAgent)
        if self._task_context:
            context_parts.append(f"【任务背景】\n{self._task_context}")

        # Add Owner-Worker conversation history for multi-turn context
        if conversation_history:
            context_parts.append(f"【Owner与Worker的对话历史】\n{conversation_history}")

        context_parts.append("=" * 50)
        context_parts.append("\n【子任务执行结果】")
        for i, r in enumerate(results, 1):
            context_parts.append(f"\n子任务 {i}: {r.description}")
            if r.success:
                result_preview = r.result[:2000] if len(r.result) > 2000 else r.result
                context_parts.append(f"结果:\n{result_preview}\n")
            else:
                context_parts.append(f"执行失败: {r.error}\n")

        context = "\n".join(context_parts)

        # Inject current date/time into system prompt
        datetime_str = get_current_datetime_str()
        full_system_prompt = f"{datetime_str}\n\n{COMPLETION_EVALUATION_PROMPT}"

        messages = [
            ChatMessage(role="system", content=full_system_prompt),
            ChatMessage(role="user", content=f"请评估以下任务的完成度:\n\n{context}"),
        ]

        try:
            # Use shorter timeout for evaluation
            timeout = 60  # 1 minute should be enough for evaluation
            response = await asyncio.wait_for(
                llm_service.complete(messages),
                timeout=timeout
            )
            return self._parse_completion_response(response.content)

        except asyncio.TimeoutError:
            logger.warning(f"OwnerAgent {self._id} completion evaluation timed out")
            # Return evaluation that continues execution - don't assume completion!
            # This is critical for iterative execution to work properly
            return CompletionEvaluation(
                is_completed=False,
                completion_percentage=50,
                what_was_done="部分子任务已执行，但评估超时",
                what_is_missing="无法确认任务是否完全完成",
                next_steps=[
                    {
                        "description": "继续执行任务，确保所有要求都已满足",
                        "tools_needed": ["execute_command"],
                        "reason": "评估超时，需要继续推进以确保任务完成"
                    }
                ],
            )
        except Exception as e:
            logger.exception(f"Error evaluating completion: {e}")
            # Return evaluation that continues execution - don't assume completion!
            return CompletionEvaluation(
                is_completed=False,
                completion_percentage=50,
                what_was_done=f"部分子任务已执行，但评估出错: {str(e)}",
                what_is_missing="无法确认任务是否完全完成",
                next_steps=[
                    {
                        "description": "继续执行任务，确保所有要求都已满足",
                        "tools_needed": ["execute_command"],
                        "reason": "评估出错，需要继续推进以确保任务完成"
                    }
                ],
            )

    def _parse_completion_response(self, content: str) -> CompletionEvaluation:
        """Parse completion evaluation response from LLM.

        Args:
            content: LLM response content.

        Returns:
            CompletionEvaluation object.
        """
        # Try to find JSON in the response
        json_match = None
        if "```json" in content:
            start = content.find("```json") + 7
            end = content.find("```", start)
            if end > start:
                json_match = content[start:end].strip()
        elif "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                json_match = content[start:end].strip()
        elif "{" in content and "is_completed" in content:
            start = content.find("{")
            end = content.rfind("}") + 1
            if end > start:
                json_match = content[start:end]

        if json_match:
            try:
                data = json.loads(json_match)
                return CompletionEvaluation(
                    is_completed=data.get("is_completed", True),
                    completion_percentage=data.get("completion_percentage", 100),
                    what_was_done=data.get("what_was_done", ""),
                    what_is_missing=data.get("what_is_missing", ""),
                    next_steps=data.get("next_steps", []),
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse completion JSON: {e}")

        # Fallback: try to detect if task is actually completed based on content
        # If the LLM response contains actual results (not evaluation JSON),
        # the task may already be complete
        content_lower = content.lower()
        completion_indicators = ["完成", "总结", "结果", "汇总", "列表", "如下", "共", "总计"]
        has_results = any(indicator in content for indicator in completion_indicators)

        # Also check if we have successful results in previous iterations
        successful_results = [r for r in results if r.success]

        if has_results or successful_results:
            # Task seems to have useful results, don't create more iterations
            logger.info(f"Completion evaluation fallback: found {len(successful_results)} successful results, synthesizing")
            return CompletionEvaluation(
                is_completed=True,  # Force completion to synthesize results
                completion_percentage=80,
                what_was_done=f"已完成 {len(successful_results)} 个有效子任务",
                what_is_missing="",
                next_steps=[],
            )

        # Only create continuation if we really have no results at all
        logger.warning("Failed to parse completion evaluation and no successful results, assuming NOT completed")
        return CompletionEvaluation(
            is_completed=False,
            completion_percentage=50,
            what_was_done="无法解析评估结果",
            what_is_missing="需要继续执行以确保任务完成",
            next_steps=[
                {
                    "description": "继续执行任务，根据原始用户请求检查是否还有未完成的工作",
                    "tools_needed": ["execute_command"],
                    "reason": "评估解析失败，需要继续推进"
                }
            ],
        )

    def _build_evaluation_context(
        self,
        current_request: str,
        worker_messages: list[str],
        is_worker_question: bool = False,
    ) -> str:
        """Build a context string for LLM evaluation or worker response.

        This provides the full task context including conversation history
        so the LLM can make informed decisions in multi-turn scenarios.

        Args:
            current_request: The current user request or worker question.
            worker_messages: List of prior messages in the conversation.
            is_worker_question: True if this is a worker question context.

        Returns:
            Formatted context string for LLM.
        """
        context_parts = []

        if self._task_context:
            context_parts.append(f"【任务背景】\n{self._task_context}")

        if is_worker_question:
            context_parts.append(f"【Worker的问题】\n{current_request}")
        else:
            context_parts.append(f"【原始用户请求】\n{current_request}")

        if worker_messages:
            context_parts.append(f"【对话历史】\n" + "\n".join(worker_messages[-10:]))

        return "\n\n".join(context_parts)

    async def _synthesize_results(
        self,
        user_request: str,
        results: list[SubtaskResult],
    ) -> str:
        """Synthesize subtask results into final response.

        Args:
            user_request: Original user request.
            results: List of subtask results.

        Returns:
            Synthesized final response.
        """
        from backend.services.llm_service import llm_service

        # Build context for synthesis
        context_parts = [f"原始任务: {user_request}\n"]
        context_parts.append("=" * 50 + "\n")

        for i, r in enumerate(results, 1):
            context_parts.append(f"\n### 子任务 {i}: {r.description}")
            if r.success:
                context_parts.append(f"\n结果:\n{r.result}\n")
            else:
                context_parts.append(f"\n执行失败: {r.error}\n")

        context = "\n".join(context_parts)

        # Inject current date/time into system prompt
        datetime_str = get_current_datetime_str()
        full_system_prompt = f"{datetime_str}\n\n{SYNTHESIS_SYSTEM_PROMPT}"

        messages = [
            ChatMessage(role="system", content=full_system_prompt),
            ChatMessage(role="user", content=f"请整合以下子任务结果，生成最终回复:\n\n{context}"),
        ]

        try:
            # Use the same timeout as configured for owner agent
            timeout = self._timeout_manager.get_current_timeout()
            # None means unlimited, otherwise cap at 5 minutes for synthesis
            effective_timeout = min(timeout, 300) if timeout is not None else None
            response = await asyncio.wait_for(
                llm_service.complete(messages),
                timeout=effective_timeout
            )
            return response.content
        except asyncio.TimeoutError:
            logger.warning(f"OwnerAgent {self._id} synthesis timed out")
            # Fallback: return raw results with a summary message
            fallback_parts = ["抱歉，整合结果超时。以下是各子任务的结果:\n"]
            for i, r in enumerate(results, 1):
                fallback_parts.append(f"\n--- 子任务 {i} ---")
                fallback_parts.append(r.result if r.success else f"失败: {r.error}")
            return "\n".join(fallback_parts)
        except Exception as e:
            logger.exception(f"Error synthesizing results: {e}")
            # Fallback: return raw results
            fallback_parts = ["抱歉，整合结果时出错。以下是各子任务的结果:\n"]
            for i, r in enumerate(results, 1):
                fallback_parts.append(f"\n--- 子任务 {i} ---")
                fallback_parts.append(r.result if r.success else f"失败: {r.error}")
            return "\n".join(fallback_parts)

    async def terminate(self) -> None:
        """Terminate the OwnerAgent and all WorkerAgents."""
        logger.info(f"OwnerAgent {self._id} terminating")

        # Terminate all workers first
        for spec, worker in self._workers:
            try:
                if worker.status not in (AgentStatus.TERMINATED, AgentStatus.ERROR):
                    await worker.terminate()
                    logger.info(f"Terminated WorkerAgent {worker.id}")
            except Exception as e:
                logger.warning(f"Failed to terminate WorkerAgent {worker.id}: {e}")

        self._workers.clear()

        # Now terminate self
        await self._update_status(AgentStatus.TERMINATED)
        logger.info(f"OwnerAgent {self._id} terminated")

    # ==================== BaseAgent Abstract Methods ====================

    async def on_start(self) -> None:
        """Called when the agent starts. OwnerAgent uses execute() instead."""
        pass

    async def on_stop(self) -> None:
        """Called when the agent stops."""
        pass

    async def on_message(self, message: Message) -> None:
        """Handle an incoming message. OwnerAgent doesn't use message queue."""
        logger.warning(f"OwnerAgent {self._id} received unexpected message")

    async def on_idle(self) -> None:
        """Called when the agent is idle. OwnerAgent doesn't use idle state."""
        pass

    async def generate_summary(self) -> str:
        """Generate a summary of the agent's work.

        Returns:
            Summary text.
        """
        if self._workers:
            worker_summaries = []
            for spec, worker in self._workers:
                if worker.result:
                    worker_summaries.append(f"- {spec.id}: {worker.result[:100]}")
            if worker_summaries:
                return f"OwnerAgent 完成了 {len(self._workers)} 个子任务:\n" + "\n".join(worker_summaries)
        return f"OwnerAgent {self._id}: 任务执行完成"
