"""
Tool Service for LongClaw.
Provides tools for agents to use (web search, web fetch, etc.).
"""
import asyncio
import logging
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """Definition of a tool that can be used by agents."""

    name: str
    description: str
    parameters: dict[str, Any]
    function: Callable[..., Any]


@dataclass
class ToolResult:
    """Result of a tool execution."""

    success: bool
    content: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolService:
    """Service for managing and executing tools."""

    def __init__(self) -> None:
        """Initialize the tool service."""
        self._tools: dict[str, ToolDefinition] = {}
        self._agent_browser_path: str | None = None
        self._command_blacklist: list[str] = []
        self._last_cleanup_time: float = 0
        self._cleanup_task: asyncio.Task | None = None
        self._running: bool = False
        # Track active sessions: {session_name: (start_time, agent_id)}
        self._active_sessions: dict[str, tuple[float, str | None]] = {}
        self._sessions_lock = asyncio.Lock()
        # Config values (loaded in init)
        self._chrome_max_processes: int = 10
        self._chrome_cleanup_interval: int = 60
        self._chrome_session_max_age: int = 120
        self._tool_search_timeout: float = 30.0
        self._tool_fetch_timeout: float = 30.0
        self._chrome_executable_path: str | None = None
        self._chrome_args: str = "--no-sandbox,--disable-dev-shm-usage"
        # Detected daemon binary name (varies by platform: x64 vs arm64)
        self._daemon_binary_name: str = "agent-browser"
        # Detected agent-browser version and capabilities
        self._agent_browser_version: str | None = None
        self._supports_batch: bool = False  # batch command exists in 0.24.0+
        self._register_default_tools()

    def _is_command_blacklisted(self, command: str) -> tuple[bool, str]:
        """Check if a command is in the blacklist.

        Args:
            command: The command to check.

        Returns:
            Tuple of (is_blacklisted, reason).
        """
        command_lower = command.lower().strip()

        for blacklisted in self._command_blacklist:
            blacklisted_lower = blacklisted.lower().strip()
            # Check if the blacklisted pattern appears in the command
            if blacklisted_lower in command_lower:
                return True, f"命令包含黑名单项: {blacklisted}"

        return False, ""

    async def _load_blacklist(self) -> None:
        """Load command blacklist from config."""
        from backend.services.config_service import config_service

        blacklist_str = await config_service.get("command_blacklist", "")
        if blacklist_str:
            self._command_blacklist = [
                item.strip() for item in blacklist_str.split(",") if item.strip()
            ]
        logger.info(f"Loaded {len(self._command_blacklist)} blacklisted command patterns")

    async def _load_browser_configs(self) -> None:
        """Load browser cleanup configs from config service."""
        from backend.services.config_service import config_service

        self._chrome_max_processes = await config_service.get_int("chrome_max_processes", 10)
        self._chrome_cleanup_interval = await config_service.get_int("chrome_cleanup_interval", 60)
        self._chrome_session_max_age = await config_service.get_int("chrome_session_max_age", 120)
        self._tool_search_timeout = await config_service.get_float("tool_search_timeout", 30.0)
        self._tool_fetch_timeout = await config_service.get_float("tool_fetch_timeout", 30.0)
        self._chrome_executable_path = await config_service.get("chrome_executable_path", None)
        self._chrome_args = await config_service.get("chrome_args", "--no-sandbox,--disable-dev-shm-usage")

        logger.info(
            f"Loaded browser configs: max_processes={self._chrome_max_processes}, "
            f"cleanup_interval={self._chrome_cleanup_interval}s, "
            f"session_max_age={self._chrome_session_max_age}s, "
            f"search_timeout={self._tool_search_timeout}s, "
            f"fetch_timeout={self._tool_fetch_timeout}s, "
            f"executable_path={self._chrome_executable_path}, "
            f"chrome_args={self._chrome_args}"
        )

    def _register_default_tools(self) -> None:
        """Register default tools."""
        # Web Search tool
        self.register_tool(
            name="web_search",
            description="Search the web for information. Returns a list of search results with titles, URLs, and snippets.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query",
                    }
                },
                "required": ["query"],
            },
            function=self._web_search,
        )

        # Web Fetch tool
        self.register_tool(
            name="web_fetch",
            description="Fetch and extract text content from a web page. Use this to get detailed information from a specific URL.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    }
                },
                "required": ["url"],
            },
            function=self._web_fetch,
        )

        # Execute Command tool
        self.register_tool(
            name="execute_command",
            description="Execute a shell command on the system. Use this for system operations, file management, and running CLI tools. Dangerous commands are blocked by blacklist.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Optional timeout in seconds (default: from config, max: 300)",
                    },
                },
                "required": ["command"],
            },
            function=self._execute_command,
        )

        # Knowledge Search tool
        self.register_tool(
            name="search_memory",
            description="Search the knowledge base for relevant memories. Use this to recall past experiences, learned information, or stored knowledge.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant memories",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category to filter results",
                    },
                },
                "required": ["query"],
            },
            function=self._search_memory,
        )

        # Store Memory tool
        self.register_tool(
            name="store_memory",
            description="Store a key memory in the knowledge base for future retrieval. Use this to remember important information, decisions, or learned lessons.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Short description or key for this memory (max 500 chars)",
                    },
                    "value": {
                        "type": "string",
                        "description": "Full content of the memory",
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category for organizing memories",
                    },
                },
                "required": ["key", "value"],
            },
            function=self._store_memory,
        )

        # Skill Lookup tool
        self.register_tool(
            name="skill_lookup",
            description="检索相关 Skill 知识库。当你不确定如何执行某个操作时，先检索 Skill 获取操作指南。例如：如何从 GitHub 拉取代码、如何使用 grep 命令等。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "检索关键词，例如 'github clone'、'grep 查找'、'pip install'",
                    }
                },
                "required": ["query"],
            },
            function=self._skill_lookup,
        )

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        function: Callable[..., Any],
    ) -> None:
        """Register a new tool.

        Args:
            name: Tool name.
            description: Tool description.
            parameters: JSON Schema for parameters.
            function: Function to execute.
        """
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            function=function,
        )
        logger.debug(f"Registered tool: {name}")

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in OpenAI function calling format.

        Returns:
            List of tool definitions.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def get_tool_names(self) -> list[str]:
        """Get names of all registered tools.

        Returns:
            List of tool names.
        """
        return list(self._tools.keys())

    async def init(self) -> None:
        """Initialize the tool service."""
        # Find agent-browser CLI path
        self._agent_browser_path = shutil.which("agent-browser")
        if self._agent_browser_path:
            logger.info(f"Tool service initialized, agent-browser found at: {self._agent_browser_path}")
        else:
            logger.warning("agent-browser CLI not found in PATH, web search/fetch will be disabled")

        # Detect daemon version and capabilities
        await self._detect_agent_browser_version()
        # Detect daemon binary name by querying the running daemon
        await self._detect_daemon_name()

        # Load command blacklist
        await self._load_blacklist()

        # Load browser cleanup configs
        await self._load_browser_configs()

    async def _detect_agent_browser_version(self) -> None:
        """Detect agent-browser CLI version and capabilities.

        The batch command was added in 0.24.0. We use it when available.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "agent-browser", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            version_str = stdout.decode().strip()
            # Extract version number, e.g. "agent-browser 0.24.0" -> "0.24.0"
            match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_str)
            if match:
                self._agent_browser_version = match.group(1)
                # batch command was added in 0.24.0
                try:
                    parts = self._agent_browser_version.split(".")
                    major, minor = int(parts[0]), int(parts[1])
                    self._supports_batch = (major > 0) or (minor >= 24)
                except (ValueError, IndexError):
                    self._supports_batch = False
                logger.info(
                    f"Detected agent-browser version: {self._agent_browser_version}, "
                    f"batch support: {self._supports_batch}"
                )
            else:
                logger.warning(f"Could not parse agent-browser version: {version_str}")
        except Exception as e:
            logger.warning(f"Could not detect agent-browser version: {e}")

    async def _detect_daemon_name(self) -> None:
        """Detect the actual agent-browser daemon binary name running on this system.

        The daemon binary name differs between platforms:
        - x86_64: agent-browser-linux-x64
        - arm64: agent-browser-linux-arm64

        We detect by finding the running daemon process name.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c",
                "pgrep -f 'agent-browser-linux' | head -1 | xargs -I{} ps -p {} -o comm= 2>/dev/null",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            name = stdout.decode().strip()
            if name:
                self._daemon_binary_name = name
                logger.info(f"Detected agent-browser daemon name: {name}")
        except Exception as e:
            logger.warning(f"Could not detect daemon name: {e}, using default: {self._daemon_binary_name}")

    async def close(self) -> None:
        """Close the tool service."""
        self._running = False
        await self.cleanup_all_browser_sessions_force()
        logger.info("Tool service closed")

    async def _check_and_cleanup_chrome(self) -> None:
        """Check Chrome processes and auto-cleanup if too many.

        This is called before search/fetch operations to prevent
        Chrome processes from accumulating.
        """
        import time

        now = time.time()

        # Skip if not enough time has passed since last cleanup
        if now - self._last_cleanup_time < self._chrome_cleanup_interval:
            return

        self._last_cleanup_time = now

        try:
            # Count Chrome processes started by agent-browser
            count_cmd = "pgrep -f 'agent-browser-chrome-' | wc -l"
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", count_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            count_str = stdout.decode().strip() if stdout else "0"

            try:
                chrome_count = int(count_str)
            except ValueError:
                chrome_count = 0

            if chrome_count >= self._chrome_max_processes:
                logger.warning(
                    f"Chrome process count ({chrome_count}) >= limit ({self._chrome_max_processes}), "
                    f"triggering auto-cleanup of orphaned sessions"
                )
                # Only clean orphaned sessions, not active ones
                await self.cleanup_all_browser_sessions()
            elif chrome_count > 0:
                logger.debug(
                    f"Chrome process count: {chrome_count}/{self._chrome_max_processes}"
                )

        except Exception as e:
            logger.warning(f"Failed to check Chrome processes: {e}")

    async def execute_tool(self, name: str, **kwargs: Any) -> ToolResult:
        """Execute a tool by name.

        Args:
            name: Tool name.
            **kwargs: Tool arguments.

        Returns:
            Tool execution result.
        """
        if name not in self._tools:
            return ToolResult(
                success=False,
                content="",
                error=f"Tool '{name}' not found. Available tools: {list(self._tools.keys())}",
            )

        tool = self._tools[name]

        try:
            logger.info(f"Executing tool: {name} with args: {kwargs}")
            result = await tool.function(**kwargs)

            if isinstance(result, ToolResult):
                return result
            else:
                return ToolResult(success=True, content=str(result))

        except Exception as e:
            logger.exception(f"Error executing tool {name}: {e}")
            return ToolResult(
                success=False,
                content="",
                error=f"Tool execution failed: {str(e)}",
            )

    # ==================== Tool Implementations ====================

    async def _run_agent_browser(
        self,
        session_name: str,
        url: str,
        timeout: float | None,
        agent_id: str | None = None,
    ) -> tuple[bool, str]:
        """Run agent-browser CLI to open a page and get snapshot.

        Uses agent-browser batch for reliable multi-step operations:
        1. open: Navigate to URL (agent-browser open is non-blocking)
        2. wait: Fixed timeout to let page render (avoid waiting for networkidle)
        3. snapshot: Get accessibility tree

        All piped via agent-browser batch --json for clean daemon interaction.

        Args:
            session_name: Browser session name for isolation.
            url: URL to open.
            timeout: Timeout in seconds for total operation (open+wait+snapshot).

        Returns:
            Tuple of (success, output or error message).
        """
        if not self._agent_browser_path:
            return False, "agent-browser CLI not found"

        # Track this session
        import time
        async with self._sessions_lock:
            self._active_sessions[session_name] = (time.time(), agent_id)

        try:
            # Total operation timeout. Defaults:
            # - wait 5000ms (5s) for page to render
            # - snapshot has its own timeout (handled by daemon)
            total_timeout = timeout if timeout is not None else 60.0

            # Build the open command with optional Chrome path/args
            cmd_parts = [self._agent_browser_path, "--session-name", session_name]
            if self._chrome_executable_path:
                cmd_parts.extend(["--executable-path", self._chrome_executable_path])
            if self._chrome_args:
                cmd_parts.extend(["--args", self._chrome_args])

            cmd_str = " ".join(cmd_parts)

            # v0.24.0+: Use fallback instead of batch due to Chrome path bug
            # The batch command doesn't pass --executable-path to the daemon's internal open,
            # so new sessions fail to launch Chrome at the correct path.
            # Fallback properly includes --executable-path in each CLI invocation.
            # v0.20.x: Fall back to chained commands
            # open -> sleep -> wait (10s) -> snapshot --json, all in one bash chain
            # Using wait with ms (not --load domcontentloaded) for deterministic timing
            # Increased wait time to 10s to allow Bing to fully render search results
            bash_cmd = (
                f"{cmd_str} open {url} & "
                f"sleep 2 && "
                f"{cmd_str} wait 10000 && "
                f"{cmd_str} snapshot --json"
            )

            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", bash_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=total_timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                await self._cleanup_browser_session(session_name)
                return False, f"Browser operation timeout after {total_timeout}s"

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                if "Event stream closed" in error_msg or "connection refused" in error_msg.lower():
                    error_msg = f"Browser daemon error: {error_msg}"
                return False, f"Browser command failed: {error_msg}"

            output = stdout.decode() if stdout else ""

            # Cleanup: close the browser session after successful operation
            await self._cleanup_browser_session(session_name)

            return True, output

        except Exception as e:
            return False, str(e)

    async def _cleanup_browser_session(self, session_name: str) -> None:
        """Close browser for a specific session and clean up Chrome processes.

        Args:
            session_name: The session name to clean up.
        """
        if not self._agent_browser_path:
            return

        try:
            # First try graceful close
            close_cmd = f"{self._agent_browser_path} --session-name {session_name} close"
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", close_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.warning(f"Failed to gracefully close session {session_name}: {e}")

        # Force kill any remaining Chrome processes for this session's user data dir
        try:
            # Find Chrome processes with the session's user data dir
            # Session names are like "search_xxx_engine", Chrome uses /tmp/agent-browser-chrome-xxx
            # We need to find and kill Chrome processes started for this session
            kill_cmd = (
                f"pkill -9 -f 'agent-browser-chrome.*{session_name}' 2>/dev/null || true"
            )
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", kill_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=3.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except Exception as e:
            logger.warning(f"Failed to kill Chrome processes for session {session_name}: {e}")

        # Remove from tracking
        async with self._sessions_lock:
            self._active_sessions.pop(session_name, None)

    async def cleanup_all_browser_sessions(self) -> None:
        """Clean up orphaned agent-browser Chrome processes.

        This only cleans up sessions that are tracked and too old (orphaned).
        It will NOT kill sessions that are actively in use or recently started.
        """
        import time
        try:
            now = time.time()
            orphaned_sessions = []

            # Find orphaned sessions (too old and still tracked)
            async with self._sessions_lock:
                for session_name, (start_time, agent_id) in list(self._active_sessions.items()):
                    if now - start_time > self._chrome_session_max_age:
                        orphaned_sessions.append(session_name)

            if not orphaned_sessions:
                logger.debug("No orphaned Chrome sessions to clean up")
                return

            logger.info(f"Cleaning up {len(orphaned_sessions)} orphaned Chrome sessions")

            for session_name in orphaned_sessions:
                await self._cleanup_browser_session(session_name)

        except Exception as e:
            logger.warning(f"Failed to cleanup orphaned browser sessions: {e}")

    async def cleanup_all_browser_sessions_force(self) -> None:
        """Force clean up ALL agent-browser Chrome processes.

        This is called when the service shuts down.
        This will kill all Chrome processes and agent-browser daemon to ensure a clean state.
        """
        try:
            # Step 1: Kill all Chrome processes started by agent-browser (new pattern)
            kill_chrome_cmd = "pkill -9 -f 'agent-browser-chrome-' 2>/dev/null || true"
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", kill_chrome_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            # Step 1b: Kill Chrome processes connecting to agent-browser CDP port (localhost:3000)
            # These are leftover from older agent-browser versions or orphaned sessions
            kill_cdp_chrome_cmd = "pkill -9 -f 'chrome.*localhost:3000' 2>/dev/null || true"
            proc1b = await asyncio.create_subprocess_exec(
                "bash", "-c", kill_cdp_chrome_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc1b.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc1b.kill()
                await proc1b.wait()

            # Step 1c: Kill any remaining Chrome processes started by agent-browser daemon
            # that don't have the agent-browser-chrome pattern (e.g., GUI mode Chrome)
            kill_orphaned_chrome_cmd = (
                "pkill -9 -f '/opt/google/chrome/chrome' 2>/dev/null || "
                "pkill -9 -f '/usr/bin/google-chrome' 2>/dev/null || "
                "pkill -9 -f 'chromium-browser' 2>/dev/null || true"
            )
            proc1c = await asyncio.create_subprocess_exec(
                "bash", "-c", kill_orphaned_chrome_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc1c.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc1c.kill()
                await proc1c.wait()

            # Step 2: Kill all agent-browser session processes
            kill_session_cmd = "pkill -9 -f 'agent-browser.*session' 2>/dev/null || true"
            proc2 = await asyncio.create_subprocess_exec(
                "bash", "-c", kill_session_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc2.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc2.kill()
                await proc2.wait()

            # Step 3: Kill the agent-browser daemon itself
            # Use the detected daemon name, not hardcoded x64
            kill_daemon_cmd = f"pkill -9 -f '{self._daemon_binary_name}' 2>/dev/null || true"
            proc3 = await asyncio.create_subprocess_exec(
                "bash", "-c", kill_daemon_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc3.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc3.kill()
                await proc3.wait()

            # Step 4: Clean up orphaned /tmp/agent-browser-chrome-* directories
            # These are leftover user data dirs from dead Chrome sessions
            cleanup_tmp_cmd = "rm -rf /tmp/agent-browser-chrome-* 2>/dev/null || true"
            proc4 = await asyncio.create_subprocess_exec(
                "bash", "-c", cleanup_tmp_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(proc4.communicate(), timeout=5.0)
            except asyncio.TimeoutError:
                proc4.kill()
                await proc4.wait()

            # Clear tracking
            async with self._sessions_lock:
                self._active_sessions.clear()

            logger.info("All browser sessions and daemon force cleaned up")

        except Exception as e:
            logger.warning(f"Failed to cleanup all browser sessions: {e}")

    def _parse_snapshot_for_search(self, snapshot: str, engine: str) -> list[dict]:
        """Parse agent-browser snapshot output to extract search results.

        The snapshot format is an accessibility tree with indentation.
        Each search result typically has:
        1. A URL (in link or StaticText before the heading)
        2. A heading (the result title)
        3. Optional snippet text

        Args:
            snapshot: Raw snapshot text output.
            engine: Search engine name for parsing hints.

        Returns:
            List of search results with title, url, snippet.
        """
        results = []
        lines = snapshot.strip().split("\n")

        # Patterns for parsing accessibility tree
        heading_pattern = re.compile(r'(\s*)heading\s+"([^"]+)"\s*\[level=(\d+),\s*ref=e(\d+)\]')
        link_pattern = re.compile(r'(\s*)link\s+"([^"]+)"\s*\[ref=e(\d+)\]')
        static_text_pattern = re.compile(r'StaticText\s+"([^"]+)"')
        url_pattern = re.compile(r'https?://[^\s<>"\'\]\)]+', re.IGNORECASE)
        # Pattern to match URL followed by path separator (› or similar)
        url_with_path_pattern = re.compile(r'(https?://[^\s<>"\'\]\)]+)\s*›\s*(\S+)')
        ansi_strip = re.compile(r'\x1b\[[0-9;]*m')

        seen_urls = set()
        pending_url = None  # Track URL seen before the current heading
        pending_url_full = None  # Track full URL with path

        # Single pass: process lines in order
        # URLs can appear before their heading, so we track "pending" URLs
        # When we hit a heading, we pair it with the most recent pending URL
        for i, raw_line in enumerate(lines):
            line = ansi_strip.sub('', raw_line)

            # Skip empty lines
            if not line.strip():
                continue

            # Check for URL in StaticText first (this often precedes the heading)
            for text in static_text_pattern.findall(line):
                # Check if URL has path separator (e.g., "https://www.zhihu.com › question")
                url_with_path_match = url_with_path_pattern.search(text)
                if url_with_path_match:
                    # Reconstruct full URL from "url › path" format
                    base_url = url_with_path_match.group(1)
                    path_part = url_with_path_match.group(2).rstrip('.')
                    full_url = f"{base_url}/{path_part}"
                    skip_patterns = [
                        'google.com/search', 'bing.com/search', 'baidu.com/s?',
                        'duckduckgo.com', 'javascript:', 'about:',
                        'googleads', 'gstatic.com', 'bing.com/th?',
                        'baidu.com/home', 'baidu.com/cache',
                    ]
                    if not any(skip in full_url.lower() for skip in skip_patterns):
                        pending_url = full_url
                        pending_url_full = full_url
                elif url_pattern.search(text):
                    url = url_pattern.search(text).group(0)
                    skip_patterns = [
                        'google.com/search', 'bing.com/search', 'baidu.com/s?',
                        'duckduckgo.com', 'javascript:', 'about:',
                        'googleads', 'gstatic.com', 'bing.com/th?',
                        'baidu.com/home', 'baidu.com/cache',
                    ]
                    if not any(skip in url.lower() for skip in skip_patterns):
                        pending_url = url
                        pending_url_full = url

            # Check for URL in link text
            lm = link_pattern.search(line)
            if lm:
                link_text = lm.group(2)
                if url_pattern.search(link_text):
                    url = url_pattern.search(link_text).group(0)
                    skip_patterns = [
                        'google.com/search', 'bing.com/search', 'baidu.com/s?',
                        'duckduckgo.com', 'javascript:', 'about:',
                        'googleads', 'gstatic.com', 'bing.com/th?',
                        'baidu.com/home', 'baidu.com/cache',
                    ]
                    if not any(skip in url.lower() for skip in skip_patterns):
                        pending_url = url
                        pending_url_full = url

            # Check for heading (this is the result title)
            hm = heading_pattern.search(line)
            if hm:
                title = hm.group(2)
                heading_level = int(hm.group(3))

                # For h2 (level 2) headings in Bing results, these are actual result titles
                if heading_level == 2:
                    result = {'title': title, 'url': '', 'snippet': ''}

                    # Use the pending URL if we have one
                    if pending_url:
                        result['url'] = pending_url

                    # Look for snippet text in subsequent lines (same listitem)
                    heading_indent = len(hm.group(1))
                    snippet_texts = []
                    for j in range(i + 1, min(i + 10, len(lines))):
                        next_line = ansi_strip.sub('', lines[j])
                        # Stop if we hit another heading or go up in indent
                        if heading_pattern.search(next_line):
                            break
                        for text in static_text_pattern.findall(next_line):
                            if url_pattern.search(text):
                                continue
                            if len(text) > 15:
                                skip_ui = ['登录', '注册', 'Sign in', 'Search', '首页', '菜单',
                                           '搜索', '翻译此页', 'Skip to', 'Accessibility']
                                if not any(skip in text for skip in skip_ui):
                                    snippet_texts.append(text[:300])
                        if snippet_texts:
                            break

                    if snippet_texts:
                        result['snippet'] = snippet_texts[0]

                    # Only add if we have a valid result
                    if result['url'] and len(result['title']) > 3:
                        if "广告" not in result['title'] and "Ads" not in result['title'] and "Back to " not in result['title']:
                            if result['url'] not in seen_urls:
                                seen_urls.add(result['url'])
                                results.append(result)

                    # Reset pending URL after use
                    pending_url = None
                    pending_url_full = None

        return results[:10]

    async def _skill_lookup(self, query: str) -> ToolResult:
        """Lookup skills based on query.

        Args:
            query: Search query.

        Returns:
            Matching skills or guidance to perform the operation directly.
        """
        from backend.services.skill_service import skill_service

        try:
            results = await skill_service.search_skills(query)
            if results:
                content = f"找到 {len(results)} 个相关 Skill:\n\n"
                for skill in results:
                    content += f"## {skill['name']}\n"
                    content += f"类别: {skill['category']}\n"
                    content += f"{skill['description']}\n\n"
                    # Include content snippet (first 500 chars)
                    if skill.get('content'):
                        content += f"内容预览:\n{skill['content'][:500]}...\n\n"
                    content += "---\n\n"
                return ToolResult(success=True, content=content)
            else:
                return ToolResult(
                    success=True,
                    content="未找到相关 Skill。\n\n提示：你可以尝试直接描述你要执行的操作，系统会尝试执行。",
                )
        except Exception as e:
            logger.warning(f"Skill lookup error: {e}")
            return ToolResult(
                success=True,
                content=f"Skill 检索遇到问题，但你可以直接描述操作。\n\n错误: {str(e)[:200]}",
            )

    async def _web_search(self, query: str) -> ToolResult:
        """Search the web using agent-browser with multiple search engines.

        Args:
            query: Search query.

        Returns:
            Search results.
        """
        # Auto-cleanup Chrome processes if too many
        await self._check_and_cleanup_chrome()

        if not self._agent_browser_path:
            return ToolResult(
                success=False,
                content="",
                error="agent-browser CLI not found, cannot perform web search",
            )

        # Use configurable timeout from config
        # Note: With the new background open approach, the total timeout should
        # cover browser startup + wait + snapshot. 90s is a good balance.
        search_timeout = max(self._tool_search_timeout, 90.0)

        # Use unique session name for each search to ensure isolation between concurrent workers
        import uuid
        search_session_id = uuid.uuid4().hex[:8]

        # Define search engines with fallback order
        # Bing International → Bing CN → 百度 → DuckDuckGo Lite
        # Can be overridden via search_engines config in system_configs
        default_search_engines = [
            {
                "name": "Bing",
                "url": f"https://www.bing.com/search?q={quote_plus(query)}",
                "session": f"search_{search_session_id}_bing",
            },
            {
                "name": "Bing中国",
                "url": f"https://cn.bing.com/search?q={quote_plus(query)}&setlang=zh-CN",
                "session": f"search_{search_session_id}_bing_cn",
            },
            {
                "name": "百度",
                "url": f"https://www.baidu.com/s?wd={quote_plus(query)}",
                "session": f"search_{search_session_id}_baidu",
            },
            {
                "name": "DuckDuckGo Lite",
                "url": f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}",
                "session": f"search_{search_session_id}_ddg",
            },
        ]

        # Load from config if available, otherwise use defaults
        try:
            from backend.services.config_service import config_service
            engines_config = await config_service.get("search_engines", None)
            if engines_config:
                import json
                engines_list = json.loads(engines_config)
                # Replace {query} placeholder with actual query and filter enabled engines
                search_engines = []
                for engine in engines_list:
                    if engine.get("enabled", True):
                        search_engines.append({
                            "name": engine["name"],
                            "url": engine["url"].replace("{query}", quote_plus(query)),
                            "session": f"search_{search_session_id}_{engine['name']}",
                        })
            else:
                search_engines = default_search_engines
        except Exception:
            search_engines = default_search_engines

        last_error = None
        for engine in search_engines:
            try:
                logger.info(f"Trying search engine: {engine['name']}")
                success, output = await self._run_agent_browser(
                    session_name=engine["session"],
                    url=engine["url"],
                    timeout=search_timeout,
                )

                if not success:
                    logger.warning(f"{engine['name']} failed: {output}")
                    last_error = output
                    continue

                # Return raw JSON snapshot directly to LLM for parsing
                # The LLM can understand the refs structure and extract search results
                try:
                    import json
                    # JSON output may be preceded by ANSI text, find the JSON start
                    json_start = output.find('{')
                    if json_start >= 0:
                        json_str = output[json_start:]
                        data = json.loads(json_str)
                    else:
                        raise ValueError("No JSON found in output")
                    if data.get("success") and data.get("data"):
                        logger.info(f"Search succeeded with {engine['name']}")
                        return ToolResult(
                            success=True,
                            content=json.dumps(data["data"], indent=2, ensure_ascii=False),
                            metadata={
                                "query": query,
                                "engine": engine["name"],
                                "origin": data["data"].get("origin", ""),
                                "result_count": len(data["data"].get("refs", {})),
                            },
                        )
                    else:
                        logger.warning(f"{engine['name']} returned no results, trying next engine")
                        continue
                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    logger.warning(f"{engine['name']} JSON parse error: {e}, trying next engine")
                    continue

            except Exception as e:
                logger.warning(f"{engine['name']} search error: {e}")
                last_error = str(e)
                continue

        # All engines failed
        error_msg = f"所有搜索引擎都失败了: {last_error}" if last_error else "未找到搜索结果"
        return ToolResult(
            success=False,
            content="",
            error=error_msg,
        )

    def _format_search_results(self, query: str, results: list[dict], engine_name: str) -> ToolResult:
        """Format search results into ToolResult."""
        content_parts = [f"搜索 '{query}' 找到 {len(results)} 个结果 (via {engine_name}):\n"]
        for i, r in enumerate(results, 1):
            content_parts.append(f"{i}. {r['title']}")
            content_parts.append(f"   URL: {r['url']}")
            if r['snippet']:
                content_parts.append(f"   摘要: {r['snippet']}")
            content_parts.append("")

        return ToolResult(
            success=True,
            content="\n".join(content_parts),
            metadata={"query": query, "results": results, "result_count": len(results), "engine": engine_name},
        )

    async def _web_fetch(self, url: str) -> ToolResult:
        """Fetch and extract content from a web page using agent-browser.

        Args:
            url: URL to fetch.

        Returns:
            Page content.
        """
        # Auto-cleanup Chrome processes if too many
        await self._check_and_cleanup_chrome()

        if not self._agent_browser_path:
            return ToolResult(
                success=False,
                content="",
                error="agent-browser CLI not found, cannot fetch web page",
            )

        # Get configurable timeout
        fetch_timeout = max(self._tool_fetch_timeout, 90.0)

        try:
            # Use a unique session name for each fetch to ensure isolation between concurrent workers
            import uuid
            session_name = f"fetch_{uuid.uuid4().hex[:8]}"

            logger.info(f"Fetching URL: {url}")
            success, output = await self._run_agent_browser(
                session_name=session_name,
                url=url,
                timeout=fetch_timeout,
            )

            if not success:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"无法获取网页: {output}",
                )

            # Parse snapshot to extract text content
            text = self._parse_snapshot_for_content(output)

            # Truncate if too long
            max_length = 8000
            if len(text) > max_length:
                text = text[:max_length] + "\n... (内容已截断)"

            # Try to extract title from the first line or early content
            title = ""
            lines = text.split("\n")
            if lines:
                title = lines[0][:100]  # First line as title

            content_parts = [f"标题: {title}", f"URL: {url}", "", text]

            return ToolResult(
                success=True,
                content="\n".join(content_parts),
                metadata={
                    "url": url,
                    "title": title,
                    "content_length": len(text),
                },
            )

        except Exception as e:
            logger.exception(f"Error fetching {url}: {e}")
            return ToolResult(
                success=False,
                content="",
                error=f"获取网页时出错: {str(e)}",
            )

    def _parse_snapshot_for_content(self, snapshot: str) -> str:
        """Parse agent-browser snapshot output to extract page text content.

        The snapshot format is an accessibility tree with elements like:
        - heading "Title" [level=X, ref=eXX]
        - paragraph
          - StaticText "Content..."
        - StaticText "Text"

        Args:
            snapshot: Raw snapshot text output.

        Returns:
            Cleaned text content.
        """
        lines = snapshot.strip().split("\n")
        text_parts = []

        # Patterns for parsing accessibility tree
        heading_pattern = re.compile(r'heading\s+"([^"]+)"\s*\[')
        static_text_pattern = re.compile(r'StaticText\s+"([^"]+)"')
        link_pattern = re.compile(r'link\s+"([^"]+)"\s*\[')
        paragraph_marker = re.compile(r'^\s*- paragraph')

        current_heading = None

        for line in lines:
            # Check for heading
            heading_match = heading_pattern.search(line)
            if heading_match:
                heading_text = heading_match.group(1)
                if heading_text and len(heading_text) > 2:
                    current_heading = heading_text
                    text_parts.append(f"\n## {heading_text}\n")

            # Check for paragraph start (indicates new content block)
            if paragraph_pattern.search(line) if (paragraph_pattern := re.compile(r'^\s*- paragraph')) else False:
                continue

            # Extract StaticText content
            static_matches = static_text_pattern.findall(line)
            for text in static_matches:
                # Skip empty or very short text
                if text and len(text) > 1:
                    # Skip common UI elements
                    skip_patterns = [
                        r'^\s*$',  # Empty
                        r'^(登录|注册|Sign in|Log in)$',
                        r'^(菜单|搜索|Search)$',
                        r'^(首页|Home)$',
                        r'^×$',  # Close buttons
                        r'^\d+$',  # Just numbers
                        r'^Skip to',
                        r'^Accessibility',
                        r'^Cookie',
                        r'^Accept$',
                    ]
                    if not any(re.match(p, text, re.IGNORECASE) for p in skip_patterns):
                        text_parts.append(text)

        # Join and clean up
        clean_text = "\n".join(text_parts)

        # Remove excessive whitespace and empty lines
        clean_text = re.sub(r'\n{3,}', '\n\n', clean_text)
        clean_text = re.sub(r' +', ' ', clean_text)  # Multiple spaces to single

        return clean_text.strip()

    async def _execute_command(self, command: str, timeout: int | None = None) -> ToolResult:
        """Execute a shell command on the system.

        Args:
            command: The shell command to execute.
            timeout: Optional timeout in seconds.

        Returns:
            Tool execution result.
        """
        from backend.services.config_service import config_service

        # Check blacklist
        is_blacklisted, reason = self._is_command_blacklisted(command)
        if is_blacklisted:
            logger.warning(f"Blocked blacklisted command: {command}")
            return ToolResult(
                success=False,
                content="",
                error=f"命令被拒绝: {reason}",
            )

        # Get timeout from config if not specified
        # Note: get_int returns None when config value is -1 (unlimited)
        if timeout is None:
            timeout = await config_service.get_int("command_timeout", 60)

        # Cap timeout at 300 seconds (unless unlimited)
        if timeout is not None:
            timeout = min(timeout, 300)

        logger.info(f"Executing command: {command} (timeout={timeout}s)")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult(
                    success=False,
                    content="",
                    error=f"命令执行超时 ({timeout}秒)",
                )

            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            # Build result content
            content_parts = [f"命令: {command}"]
            content_parts.append(f"退出码: {proc.returncode}")

            if stdout_str:
                # Truncate if too long
                if len(stdout_str) > 8000:
                    stdout_str = stdout_str[:8000] + "\n... (输出已截断)"
                content_parts.append(f"\n标准输出:\n{stdout_str}")

            if stderr_str:
                if len(stderr_str) > 2000:
                    stderr_str = stderr_str[:2000] + "\n... (错误输出已截断)"
                content_parts.append(f"\n标准错误:\n{stderr_str}")

            return ToolResult(
                success=proc.returncode == 0,
                content="\n".join(content_parts),
                error=stderr_str if proc.returncode != 0 else None,
                metadata={
                    "command": command,
                    "return_code": proc.returncode,
                    "timeout": timeout,
                },
            )

        except Exception as e:
            logger.exception(f"Error executing command: {e}")
            return ToolResult(
                success=False,
                content="",
                error=f"命令执行失败: {str(e)}",
            )

    async def _search_memory(self, query: str, category: str | None = None) -> ToolResult:
        """Search the knowledge base for relevant memories.

        Args:
            query: Search query.
            category: Optional category filter.

        Returns:
            Tool execution result.
        """
        from backend.services.retrieval_service import retrieval_service

        try:
            results = await retrieval_service.search(
                query=query,
                category=category,
                use_semantic=True,
            )

            if not results:
                return ToolResult(
                    success=True,
                    content="未找到相关记忆。",
                    metadata={"query": query, "result_count": 0},
                )

            # Format results
            content_parts = [f"搜索 '{query}' 找到 {len(results)} 条相关记忆:\n"]
            for i, item in enumerate(results, 1):
                content_parts.append(f"{i}. [{item.get('category', '通用')}] {item.get('key', '')}")
                content_parts.append(f"   {item.get('value', '')[:200]}...")
                content_parts.append("")

            return ToolResult(
                success=True,
                content="\n".join(content_parts),
                metadata={"query": query, "results": results, "result_count": len(results)},
            )

        except Exception as e:
            logger.exception(f"Error searching memory: {e}")
            return ToolResult(
                success=False,
                content="",
                error=f"搜索记忆失败: {str(e)}",
            )

    async def _store_memory(self, key: str, value: str, category: str | None = None) -> ToolResult:
        """Store a memory in the knowledge base.

        Args:
            key: Short description/key.
            value: Full content.
            category: Optional category.

        Returns:
            Tool execution result.
        """
        from backend.services.retrieval_service import retrieval_service

        try:
            knowledge = await retrieval_service.store(
                key=key[:500],  # Limit key length
                value=value,
                category=category,
                generate_embedding=True,
            )

            return ToolResult(
                success=True,
                content=f"已存储记忆: {key[:50]}{'...' if len(key) > 50 else ''}",
                metadata={
                    "knowledge_id": knowledge.id,
                    "key": key,
                    "category": category,
                },
            )

        except Exception as e:
            logger.exception(f"Error storing memory: {e}")
            return ToolResult(
                success=False,
                content="",
                error=f"存储记忆失败: {str(e)}",
            )


# Global tool service instance
tool_service = ToolService()
