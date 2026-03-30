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

        # Load command blacklist
        await self._load_blacklist()

    async def close(self) -> None:
        """Close the tool service."""
        logger.info("Tool service closed")

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
    ) -> tuple[bool, str]:
        """Run agent-browser CLI to open a page and get snapshot.

        Uses asyncio.create_subprocess_exec with bash -c for command chaining.

        Args:
            session_name: Browser session name for isolation.
            url: URL to open.
            timeout: Timeout in seconds, None means unlimited.

        Returns:
            Tuple of (success, output or error message).
        """
        if not self._agent_browser_path:
            return False, "agent-browser CLI not found"

        try:
            # Build command chain
            cmd = (
                f"{self._agent_browser_path} --session-name {session_name} open '{url}' && "
                f"{self._agent_browser_path} --session-name {session_name} wait --load networkidle && "
                f"{self._agent_browser_path} --session-name {session_name} snapshot"
            )

            # Use create_subprocess_exec with bash -c for command chaining
            proc = await asyncio.create_subprocess_exec(
                "bash", "-c", cmd,
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
                timeout_str = "unlimited" if timeout is None else f"{timeout}s"
                return False, f"Timeout after {timeout_str}"

            if proc.returncode != 0:
                error_msg = stderr.decode() if stderr else "Unknown error"
                return False, f"agent-browser failed: {error_msg}"

            output = stdout.decode() if stdout else ""
            return True, output

        except Exception as e:
            return False, str(e)

    def _parse_snapshot_for_search(self, snapshot: str, engine: str) -> list[dict]:
        """Parse agent-browser snapshot output to extract search results.

        The snapshot format is an accessibility tree:
        - heading "Title" [level=X, ref=eXX]
          - link "Title" [ref=eXX]
        - link "domain.com" [ref=eXX]
          - StaticText "https://..."
        - paragraph
          - StaticText "Snippet..."

        Args:
            snapshot: Raw snapshot text output.
            engine: Search engine name for parsing hints.

        Returns:
            List of search results with title, url, snippet.
        """
        results = []
        lines = snapshot.strip().split("\n")

        # Patterns for parsing accessibility tree
        heading_pattern = re.compile(r'heading\s+"([^"]+)"\s*\[level=(\d+),\s*ref=e(\d+)\]')
        link_pattern = re.compile(r'link\s+"([^"]+)"\s*\[ref=e(\d+)\]')
        static_text_pattern = re.compile(r'StaticText\s+"([^"]+)"')
        url_pattern = re.compile(r'https?://[^\s<>"\'\]\)]+', re.IGNORECASE)

        # Track found URLs to avoid duplicates
        seen_urls = set()

        # State machine to track current result being built
        current_result = None
        last_heading_ref = None
        last_link_ref = None
        pending_snippets = []

        for i, line in enumerate(lines):
            # Check for heading (potential result title)
            heading_match = heading_pattern.search(line)
            if heading_match:
                title = heading_match.group(1)
                heading_ref = heading_match.group(3)

                # Save previous result if exists
                if current_result and current_result.get("url"):
                    if current_result["url"] not in seen_urls:
                        seen_urls.add(current_result["url"])
                        results.append(current_result)

                # Start new result
                current_result = {
                    "title": title,
                    "url": "",
                    "snippet": "",
                }
                last_heading_ref = heading_ref
                pending_snippets = []
                continue

            # Check for link (potential URL or domain)
            link_match = link_pattern.search(line)
            if link_match:
                link_text = link_match.group(1)
                link_ref = link_match.group(2)
                last_link_ref = link_ref

                # Check if link text is a URL
                if url_pattern.search(link_text):
                    url = url_pattern.search(link_text).group(0)
                    if current_result and not current_result.get("url"):
                        current_result["url"] = url
                elif link_text.startswith("http") or "." in link_text:
                    # Domain or URL-like link text
                    if not link_text.startswith("http"):
                        link_text = "https://" + link_text
                    if current_result and not current_result.get("url"):
                        current_result["url"] = link_text

            # Check for StaticText (potential URL or snippet)
            static_matches = static_text_pattern.findall(line)
            for text in static_matches:
                # Check if this is a URL
                url_match = url_pattern.search(text)
                if url_match:
                    url = url_match.group(0)
                    # Skip navigation/pagination URLs
                    skip_patterns = [
                        'google.com/search', 'bing.com/search', 'baidu.com/s?',
                        'duckduckgo.com', 'javascript:', 'about:',
                        'googleads', 'gstatic.com', 'bing.com/th?',
                        'baidu.com/home', 'baidu.com/cache',
                    ]
                    if any(skip in url.lower() for skip in skip_patterns):
                        continue

                    if current_result and not current_result.get("url"):
                        current_result["url"] = url

                # Accumulate snippets (non-URL text, reasonable length)
                elif text and len(text) > 15 and not url_pattern.search(text):
                    # Skip common UI elements
                    skip_ui = ['登录', '注册', 'Sign in', 'Search', '首页', '菜单',
                               '搜索', '翻译此页', 'Skip to', 'Accessibility']
                    if not any(skip in text for skip in skip_ui):
                        pending_snippets.append(text[:300])

        # Don't forget the last result
        if current_result and current_result.get("url"):
            if current_result["url"] not in seen_urls:
                results.append(current_result)

        # Assign snippets to results
        for r in results:
            if pending_snippets:
                # Take first available snippet
                r["snippet"] = pending_snippets.pop(0) if pending_snippets else ""

        # Filter out low-quality results
        filtered_results = []
        for r in results:
            url = r["url"]
            title = r["title"]
            # Must have valid URL and reasonable title
            if url and len(title) > 3 and url.startswith("http"):
                # Skip ad labels
                if "广告" not in title and "Ads" not in title:
                    filtered_results.append(r)

        return filtered_results[:10]  # Limit to 10 results

    async def _web_search(self, query: str) -> ToolResult:
        """Search the web using agent-browser with multiple search engines.

        Args:
            query: Search query.

        Returns:
            Search results.
        """
        if not self._agent_browser_path:
            return ToolResult(
                success=False,
                content="",
                error="agent-browser CLI not found, cannot perform web search",
            )

        from backend.services.config_service import config_service

        # Get configurable timeout (default 15s for each search engine)
        search_timeout = await config_service.get_float("tool_search_timeout", 15.0)

        # Define search engines with fallback order
        # 百度 → Bing → DuckDuckGo Lite → Google
        search_engines = [
            {
                "name": "百度",
                "url": f"https://www.baidu.com/s?wd={quote_plus(query)}",
                "session": "search_baidu",
            },
            {
                "name": "Bing",
                "url": f"https://www.bing.com/search?q={quote_plus(query)}&setlang=en",
                "session": "search_bing",
            },
            {
                "name": "DuckDuckGo Lite",
                "url": f"https://lite.duckduckgo.com/lite/?q={quote_plus(query)}",
                "session": "search_ddg",
            },
            {
                "name": "Google",
                "url": f"https://www.google.com/search?q={quote_plus(query)}",
                "session": "search_google",
            },
        ]

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

                # Parse results from snapshot
                results = self._parse_snapshot_for_search(output, engine["name"])

                if results:
                    logger.info(f"Search succeeded with {engine['name']}, found {len(results)} results")
                    return self._format_search_results(query, results, engine["name"])
                else:
                    logger.warning(f"{engine['name']} returned no results, trying next engine")
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
        if not self._agent_browser_path:
            return ToolResult(
                success=False,
                content="",
                error="agent-browser CLI not found, cannot fetch web page",
            )

        from backend.services.config_service import config_service

        # Get configurable timeout
        fetch_timeout = await config_service.get_float("tool_fetch_timeout", 30.0)

        try:
            # Use a unique session name based on URL hash for isolation
            import hashlib
            session_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            session_name = f"fetch_{session_hash}"

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
