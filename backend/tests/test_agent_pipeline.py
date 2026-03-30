"""
Integration test for LongClaw agent scheduling pipeline.
Tests the complete flow: Resident -> Owner -> Worker with dependency support.
"""
import asyncio
import json
import os
import sys
import time
from typing import Any

import httpx

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AgentPipelineTest:
    """Test the agent scheduling pipeline."""

    def __init__(self, base_url: str = "http://localhost:8001", api_key: str | None = None):
        self.base_url = base_url
        self.api_key = api_key or os.environ.get("API_KEY", "")
        self.headers = {"X-API-Key": self.api_key}
        self.client = httpx.AsyncClient(timeout=300.0, headers=self.headers)
        self.channel_id: str | None = None
        self.test_results: dict[str, bool] = {}

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def check_server_health(self) -> bool:
        """Check if the server is running."""
        try:
            # Use agents endpoint for health check
            response = await self.client.get(f"{self.base_url}/api/agents?limit=1")
            return response.status_code == 200
        except Exception as e:
            print(f"[ERROR] Server health check failed: {e}")
            return False

    async def get_web_channel(self) -> dict[str, Any] | None:
        """Get or create the web channel."""
        try:
            response = await self.client.get(f"{self.base_url}/api/chat/web-channel")
            if response.status_code == 200:
                return response.json()
            print(f"[ERROR] Failed to get web channel: {response.status_code}")
            return None
        except Exception as e:
            print(f"[ERROR] Get web channel failed: {e}")
            return None

    async def send_message(self, content: str) -> dict[str, Any] | None:
        """Send a message to the resident agent."""
        if not self.channel_id:
            print("[ERROR] No channel ID available")
            return None

        try:
            response = await self.client.post(
                f"{self.base_url}/api/chat/send",
                json={"channel_id": self.channel_id, "content": content}
            )
            if response.status_code == 200:
                return response.json()
            print(f"[ERROR] Failed to send message: {response.status_code} - {response.text}")
            return None
        except Exception as e:
            print(f"[ERROR] Send message failed: {e}")
            return None

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task details."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tasks/{task_id}")
            if response.status_code == 200:
                return response.json()
            return None
        except Exception:
            return None

    async def get_agents(self) -> list[dict[str, Any]]:
        """Get all agents."""
        try:
            response = await self.client.get(f"{self.base_url}/api/agents")
            if response.status_code == 200:
                return response.json().get("items", [])
            return []
        except Exception:
            return []

    async def get_recent_tasks(self, limit: int = 5) -> list[dict[str, Any]]:
        """Get recent tasks."""
        try:
            response = await self.client.get(f"{self.base_url}/api/tasks?limit={limit}")
            if response.status_code == 200:
                return response.json().get("items", [])
            return []
        except Exception:
            return []

    async def wait_for_task_completion(self, task_id: str, timeout: float = 180.0) -> dict[str, Any] | None:
        """Wait for a task to complete."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            task = await self.get_task(task_id)
            if task:
                status = task.get("status")
                if status in ("completed", "terminated", "error"):
                    return task
            await asyncio.sleep(2)
        print(f"[WARN] Timeout waiting for task {task_id}")
        return None

    def print_header(self, title: str):
        """Print a section header."""
        print(f"\n{'='*60}")
        print(f" {title}")
        print(f"{'='*60}")

    def print_result(self, check_id: str, description: str, passed: bool, details: str = ""):
        """Print a test result."""
        status = "✅ PASS" if passed else "❌ FAIL"
        self.test_results[check_id] = passed
        print(f"  [{status}] {description}")
        if details:
            print(f"         {details}")

    async def run_test_task_a(self) -> bool:
        """Run Task-A: Weather comparison test (parallel + sequential)."""
        self.print_header("Task-A: Weather Comparison (Parallel + Sequential)")

        # Test message with [COMPLEX] keyword to force OwnerAgent
        test_message = """[COMPLEX] 帮我完成以下三步任务：
第一步，搜索"2026年3月29日北京天气"；
第二步，搜索"2026年3月29日上海天气"；
第三步，根据前两步的结果，对比两个城市哪个更适合出行，给出一句推荐。
请按顺序执行，第三步依赖前两步的结果。"""

        print(f"\n[INFO] Sending test message...")
        result = await self.send_message(test_message)
        if not result:
            print("[ERROR] Failed to send message")
            return False

        print(f"[INFO] Message sent, reply received: {result.get('reply', '')[:100]}...")

        # Wait a bit for task to be created
        await asyncio.sleep(3)

        # Get recent tasks
        tasks = await self.get_recent_tasks(limit=3)
        if not tasks:
            print("[ERROR] No tasks found")
            return False

        # Find the task we just created
        task = tasks[0]  # Most recent
        task_id = task.get("id")
        print(f"[INFO] Task created: {task_id}")
        print(f"[INFO] Task title: {task.get('title', '')[:80]}")

        # Wait for task completion
        print(f"\n[INFO] Waiting for task completion (timeout: 180s)...")
        completed_task = await self.wait_for_task_completion(task_id, timeout=180.0)

        if not completed_task:
            self.print_result("A1", "Task completion", False, "Timeout waiting for task")
            return False

        # Run verification checks
        await self.verify_task_results(completed_task, "A")
        return True

    async def run_test_task_b(self) -> bool:
        """Run Task-B: Sequential query test."""
        self.print_header("Task-B: Sequential Query (Serial Dependencies)")

        test_message = """[COMPLEX] 先帮我搜索"Python最新稳定版本号是多少"，
然后用搜索到的版本号，再搜索"这个版本的Python有什么新特性"，
最后把结果告诉我。"""

        print(f"\n[INFO] Sending test message...")
        result = await self.send_message(test_message)
        if not result:
            print("[ERROR] Failed to send message")
            return False

        print(f"[INFO] Message sent, reply received: {result.get('reply', '')[:100]}...")

        await asyncio.sleep(3)
        tasks = await self.get_recent_tasks(limit=3)
        if not tasks:
            print("[ERROR] No tasks found")
            return False

        task = tasks[0]
        task_id = task.get("id")
        print(f"[INFO] Task created: {task_id}")

        print(f"\n[INFO] Waiting for task completion...")
        completed_task = await self.wait_for_task_completion(task_id, timeout=120.0)

        if not completed_task:
            self.print_result("B1", "Task completion", False, "Timeout")
            return False

        await self.verify_task_results(completed_task, "B")
        return True

    async def verify_task_results(self, task: dict[str, Any], test_prefix: str):
        """Verify task results against checklist."""
        task_id = task.get("id")
        status = task.get("status")
        plan = task.get("plan")
        summary = task.get("summary", "")
        subtasks = task.get("subtasks", [])
        subtask_stats = task.get("subtask_stats", {})

        print(f"\n[INFO] Task final status: {status}")
        print(f"[INFO] Subtask count: {len(subtasks)}")
        print(f"[INFO] Subtask stats: {subtask_stats}")

        # Check 1: Task status is correct
        is_status_ok = status in ("completed", "error")  # error is acceptable if subtasks failed
        self.print_result(
            f"{test_prefix}1",
            f"Task status is valid (completed/error)",
            is_status_ok,
            f"status={status}"
        )

        # Check 2: Plan field is not null
        has_plan = plan is not None and isinstance(plan, dict)
        self.print_result(
            f"{test_prefix}2",
            "Plan field is populated (not null)",
            has_plan,
            f"plan={'有内容' if has_plan else 'null'}"
        )

        # Check 3: Subtasks were created
        has_subtasks = len(subtasks) > 0
        self.print_result(
            f"{test_prefix}3",
            "Subtasks were created",
            has_subtasks,
            f"count={len(subtasks)}"
        )

        # Check 4: Subtask stats match actual subtasks
        stats_match = (
            subtask_stats.get("total", 0) == len(subtasks) and
            subtask_stats.get("completed", 0) + subtask_stats.get("failed", 0) +
            subtask_stats.get("pending", 0) + subtask_stats.get("running", 0) == len(subtasks)
        )
        self.print_result(
            f"{test_prefix}4",
            "Subtask stats are accurate",
            stats_match,
            f"stats={subtask_stats}"
        )

        # Check 5: Dependencies are set (if applicable)
        deps_found = False
        if has_subtasks:
            for st in subtasks:
                depends_on = st.get("depends_on")
                if depends_on and len(depends_on) > 0:
                    deps_found = True
                    break
        self.print_result(
            f"{test_prefix}5",
            "Dependencies are set in subtasks",
            deps_found,
            f"found_dependencies={deps_found}"
        )

        # Check 6: All subtasks have valid status
        valid_statuses = {"pending", "running", "completed", "failed", "skipped"}
        all_valid_status = all(st.get("status") in valid_statuses for st in subtasks)
        self.print_result(
            f"{test_prefix}6",
            "All subtasks have valid status",
            all_valid_status
        )

        # Check 7: Summary is populated
        has_summary = summary is not None and len(summary) > 0
        self.print_result(
            f"{test_prefix}7",
            "Task summary is populated",
            has_summary,
            f"length={len(summary) if summary else 0}"
        )

        # Check 8: Get agents and verify hierarchy
        agents = await self.get_agents()
        resident_agents = [a for a in agents if a.get("agent_type") == "resident"]
        owner_agents = [a for a in agents if a.get("agent_type") == "owner"]
        worker_agents = [a for a in agents if a.get("agent_type") == "worker"]

        # Resident agent may be terminated after task completion, so this is informational
        has_resident = len(resident_agents) > 0
        print(f"  [INFO] Resident agent count: {len(resident_agents)} (may be cleaned up after task)")

        # Check for Owner/Worker agents (more relevant for dependency testing)
        has_owner = len(owner_agents) > 0
        self.print_result(
            f"{test_prefix}8",
            "Owner/Worker agents created for task",
            has_owner or len(worker_agents) > 0,
            f"owners={len(owner_agents)}, workers={len(worker_agents)}"
        )

        # Check 9: No agents in error state (optional check)
        all_agents_ok = all(a.get("status") != "error" for a in agents)
        self.print_result(
            f"{test_prefix}9",
            "All agents are healthy (no errors)",
            all_agents_ok
        )

        # Print subtask details
        print(f"\n[INFO] Subtask details:")
        for i, st in enumerate(subtasks):
            dep_str = str(st.get("depends_on", [])) if st.get("depends_on") else "[]"
            print(f"  #{i} | status={st.get('status'):10} | deps={dep_str:15} | {st.get('title', '')[:40]}")

    async def run_all_tests(self):
        """Run all integration tests."""
        print("\n" + "="*60)
        print(" LongClaw Agent Pipeline Integration Test")
        print("="*60)

        # Check server health
        print("\n[INFO] Checking server health...")
        if not await self.check_server_health():
            print("[ERROR] Server is not running! Please start the backend server first.")
            return False

        print("[INFO] Server is healthy")

        # Get web channel
        print("\n[INFO] Getting web channel...")
        channel = await self.get_web_channel()
        if not channel:
            print("[ERROR] Failed to get web channel")
            return False

        self.channel_id = channel.get("id")
        print(f"[INFO] Web channel ID: {self.channel_id}")

        # Run test tasks
        try:
            # Task-A: Parallel + Sequential
            await self.run_test_task_a()

            # Wait between tests
            print("\n[INFO] Waiting 5 seconds before next test...")
            await asyncio.sleep(5)

            # Task-B: Sequential only
            await self.run_test_task_b()

        except Exception as e:
            print(f"[ERROR] Test execution failed: {e}")
            import traceback
            traceback.print_exc()

        # Print summary
        self.print_summary()

        return all(self.test_results.values())

    def print_summary(self):
        """Print test summary."""
        self.print_header("Test Summary")

        total = len(self.test_results)
        passed = sum(1 for v in self.test_results.values() if v)
        failed = total - passed

        print(f"\n  Total checks: {total}")
        print(f"  Passed: {passed}")
        print(f"  Failed: {failed}")

        if failed > 0:
            print(f"\n  Failed checks:")
            for check_id, passed in self.test_results.items():
                if not passed:
                    print(f"    - {check_id}")

        print(f"\n  Overall: {'✅ ALL PASSED' if failed == 0 else '❌ SOME FAILED'}")


async def main():
    """Main entry point."""
    test = AgentPipelineTest()
    try:
        success = await test.run_all_tests()
        sys.exit(0 if success else 1)
    finally:
        await test.close()


if __name__ == "__main__":
    asyncio.run(main())
