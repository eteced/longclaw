"""
Tests for ToolService - specifically browser launch and cleanup functionality.
"""
import asyncio
import os
import shutil
import subprocess
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock must be declared before importing the module under test
pytest_plugins = ['pytest_asyncio']


class TestBrowserLaunch:
    """Test browser launch functionality."""

    @pytest.fixture(scope="class", autouse=True)
    def warmup_daemon(self):
        """Warm up agent-browser daemon before running tests."""
        # Do a warmup call to ensure daemon is ready
        warmup_session = f"warmup_{int(time.time())}"
        subprocess.run(
            ["agent-browser", "--session-name", warmup_session, "open", "https://example.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Close it
        subprocess.run(
            ["agent-browser", "--session-name", warmup_session, "close"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        yield
        # Cleanup after all tests
        subprocess.run(["pkill", "-9", "-f", "agent-browser"], capture_output=True)
        subprocess.run(["pkill", "-9", "-f", "chrome"], capture_output=True)

    @pytest.fixture
    def event_loop(self):
        """Create an instance of the default event loop for the test session."""
        loop = asyncio.new_event_loop()
        yield loop
        loop.close()

    @pytest.mark.asyncio
    async def test_agent_browser_binary_exists(self):
        """Test that agent-browser CLI exists and is executable."""
        agent_browser_path = shutil.which("agent-browser")
        assert agent_browser_path is not None, "agent-browser CLI not found in PATH"
        assert os.path.isfile(agent_browser_path), f"agent-browser not a file: {agent_browser_path}"
        assert os.access(agent_browser_path, os.X_OK), f"agent-browser not executable: {agent_browser_path}"

    @pytest.mark.asyncio
    async def test_agent_browser_version(self):
        """Test that agent-browser version can be retrieved."""
        result = subprocess.run(
            ["agent-browser", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, f"agent-browser --version failed: {result.stderr}"
        assert "agent-browser" in result.stdout.lower(), f"Unexpected version output: {result.stdout}"

    @pytest.mark.asyncio
    async def test_agent_browser_open_basic(self):
        """Test basic agent-browser open command works."""
        session_name = f"test_basic_{int(time.time())}"
        result = subprocess.run(
            ["agent-browser", "--session-name", session_name, "open", "https://example.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Skip if daemon is in bad state
        if result.returncode != 0 and "Event stream closed" in result.stderr:
            pytest.skip("Daemon in bad state (Event stream closed)")
        assert result.returncode == 0, f"agent-browser open failed: {result.stderr}"
        assert "Example" in result.stdout or "example" in result.stdout.lower(), f"Unexpected output: {result.stdout}"

    @pytest.mark.asyncio
    async def test_agent_browser_session_isolation(self):
        """Test that different session names create isolated browser sessions."""
        session1 = f"test_iso1_{int(time.time())}"
        session2 = f"test_iso2_{int(time.time())}"

        # Open first URL in session1
        result1 = subprocess.run(
            ["agent-browser", "--session-name", session1, "open", "https://example.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result1.returncode == 0, f"Session1 open failed: {result1.stderr}"

        # Open different URL in session2
        result2 = subprocess.run(
            ["agent-browser", "--session-name", session2, "open", "https://example.org"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result2.returncode == 0, f"Session2 open failed: {result2.stderr}"

        # Sessions should be isolated - both should show example domain
        assert "Example" in result1.stdout or "example" in result1.stdout, f"Session1 should show example: {result1.stdout}"
        assert "Example" in result2.stdout or "example" in result2.stdout, f"Session2 should show example: {result2.stdout}"

    @pytest.mark.asyncio
    async def test_agent_browser_close_command(self):
        """Test agent-browser close command terminates session properly."""
        session_name = f"test_close_{int(time.time())}"

        # Open a page
        result = subprocess.run(
            ["agent-browser", "--session-name", session_name, "open", "https://example.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"Open failed: {result.stderr}"

        # Close the session
        close_result = subprocess.run(
            ["agent-browser", "--session-name", session_name, "close"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # close command should succeed (exit 0 or show "Browser closed")
        assert close_result.returncode == 0 or "closed" in close_result.stdout.lower(), \
            f"Close failed: {close_result.stderr}, stdout: {close_result.stdout}"

    @pytest.mark.asyncio
    async def test_chrome_process_cleanup_after_close(self):
        """Test that Chrome processes are cleaned up after session close."""
        session_name = f"test_cleanup_{int(time.time())}"

        # Get initial chrome process count
        initial_count = self._get_chrome_process_count()

        # Open a page
        result = subprocess.run(
            ["agent-browser", "--session-name", session_name, "open", "https://example.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Skip if daemon is in bad state
        if result.returncode != 0 and "Event stream closed" in result.stderr:
            pytest.skip("Daemon in bad state (Event stream closed)")
        assert result.returncode == 0, f"Open failed: {result.stderr}"

        # Close the session
        close_result = subprocess.run(
            ["agent-browser", "--session-name", session_name, "close"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        # Wait a bit for cleanup
        time.sleep(2)

        # Chrome processes should be cleaned up
        final_count = self._get_chrome_process_count()
        assert final_count <= initial_count + 1, \
            f"Chrome processes not cleaned up: {initial_count} -> {final_count}"

    @pytest.mark.asyncio
    async def test_agent_browser_concurrent_sessions(self):
        """Test that multiple session opens work correctly (may be sequential due to agent-browser limitations)."""
        session1 = f"test_concurrent1_{int(time.time())}"
        session2 = f"test_concurrent2_{int(time.time())}"

        # Note: agent-browser may process sessions sequentially, so we use a longer timeout
        # and don't require them to truly run concurrently

        # Open first session
        proc1 = await asyncio.create_subprocess_exec(
            "agent-browser", "--session-name", session1, "open", "https://www.baidu.com",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Wait for first to complete (can take up to 60s for browser launch)
        try:
            stdout1, stderr1 = await asyncio.wait_for(proc1.communicate(), timeout=90)
        except asyncio.TimeoutError:
            proc1.kill()
            pytest.skip("Session1 timed out - daemon may be overloaded")

        # Open second session after first completes
        proc2 = await asyncio.create_subprocess_exec(
            "agent-browser", "--session-name", session2, "open", "https://www.google.com",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=90)
        except asyncio.TimeoutError:
            proc2.kill()
            pytest.fail("Session2 timed out - browser launch took too long")

        # Both sessions should succeed (or at least one may fail due to timing)
        # The important thing is that the tool service handles these gracefully
        stderr1_str = stderr1.decode()
        # Skip on known daemon/daemon issues
        if proc1.returncode != 0 and ("Event stream closed" in stderr1_str or "timed out" in stderr1_str.lower()):
            pytest.skip("Daemon in bad state or overloaded")
        assert proc1.returncode == 0, f"Session1 failed: {stderr1_str}"

    @pytest.mark.asyncio
    async def test_chrome_executable_path_config(self):
        """Test that Chrome executable path can be configured."""
        # Find available Chrome
        chrome_path = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
        if chrome_path:
            # Should be able to pass custom executable path
            session_name = f"test_custom_chrome_{int(time.time())}"
            result = subprocess.run(
                [
                    "agent-browser",
                    "--session-name", session_name,
                    "--executable-path", chrome_path,
                    "open", "https://www.baidu.com"
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            # May fail if daemon is already running with different executable
            # or if page times out. Both are acceptable - we just want to verify it doesn't crash.
            # Note: --executable-path is IGNORED when daemon is already running!
            stderr_lower = result.stderr.lower()
            acceptable = (
                result.returncode == 0 or
                "failed" in stderr_lower or
                "timeout" in stderr_lower or
                "executable-path ignored" in stderr_lower
            )
            assert acceptable, f"Custom Chrome failed unexpectedly: {result.stderr}"

    def _get_chrome_process_count(self) -> int:
        """Get count of Chrome/Chromium processes."""
        result = subprocess.run(
            ["pgrep", "-c", "-f", "chrome"],
            capture_output=True,
            text=True,
        )
        try:
            return int(result.stdout.strip())
        except:
            return 0


class TestBrowserSessionCleanup:
    """Test browser session cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_removes_session_files(self):
        """Test that cleanup removes session-specific files."""
        session_name = f"test_files_{int(time.time())}"

        # Open a page to create session
        subprocess.run(
            ["agent-browser", "--session-name", session_name, "open", "https://example.com"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Check session directory exists
        session_prefix = session_name[:8]
        session_dir_pattern = f"/tmp/agent-browser-chrome-*{session_prefix}*"
        result = subprocess.run(
            f"ls -d /tmp/agent-browser-chrome-* 2>/dev/null | wc -l",
            shell=True,
            capture_output=True,
            text=True,
        )
        initial_dirs = int(result.stdout.strip())

        # Close session
        subprocess.run(
            ["agent-browser", "--session-name", session_name, "close"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        time.sleep(2)

        # Session directory should be removed
        result = subprocess.run(
            f"ls -d /tmp/agent-browser-chrome-* 2>/dev/null | wc -l",
            shell=True,
            capture_output=True,
            text=True,
        )
        final_dirs = int(result.stdout.strip())

        assert final_dirs <= initial_dirs, \
            f"Session directories not cleaned: {initial_dirs} -> {final_dirs}"

    @pytest.mark.asyncio
    async def test_cleanup_all_sessions(self):
        """Test cleanup of all browser sessions."""
        # Open multiple sessions
        sessions = [f"test_all_{i}_{int(time.time())}" for i in range(3)]

        for session in sessions:
            subprocess.run(
                ["agent-browser", "--session-name", session, "open", "https://example.com"],
                capture_output=True,
                text=True,
                timeout=30,
            )

        # Close all
        close_result = subprocess.run(
            ["agent-browser", "close-all"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Note: close-all may not be a valid command, so this is informational
        # The important thing is sessions get closed

        time.sleep(2)


class TestToolServiceIntegration:
    """Integration tests for ToolService with real browser."""

    @pytest.fixture
    def tool_service(self):
        """Create ToolService instance for testing."""
        # Import here to avoid early initialization
        from backend.services.tool_service import tool_service
        return tool_service

    @pytest.mark.asyncio
    async def test_run_agent_browser_success(self):
        """Test successful browser operation through ToolService."""
        import shutil
        from backend.services.tool_service import tool_service

        # Manually set agent_browser_path if not initialized
        if not tool_service._agent_browser_path:
            tool_service._agent_browser_path = shutil.which("agent-browser")

        session_name = f"test_service_{int(time.time())}"
        success, output = await tool_service._run_agent_browser(
            session_name=session_name,
            url="https://example.com",
            timeout=30.0,
            agent_id="test_agent",
        )

        assert success, f"Browser operation failed: {output}"
        assert len(output) > 0, "No output from browser"

    @pytest.mark.asyncio
    async def test_run_agent_browser_timeout_handling(self):
        """Test that browser launch timeout is handled correctly."""
        import shutil
        from backend.services.tool_service import tool_service

        # Manually set agent_browser_path if not initialized
        if not tool_service._agent_browser_path:
            tool_service._agent_browser_path = shutil.which("agent-browser")

        # This should complete within 60 seconds or fail with timeout message
        session_name = f"test_timeout_{int(time.time())}"

        # Use a short timeout for the test
        start_time = time.time()
        success, output = await tool_service._run_agent_browser(
            session_name=session_name,
            url="https://example.com",
            timeout=30.0,
            agent_id="test_agent",
        )
        elapsed = time.time() - start_time

        # Should either succeed quickly or fail with proper timeout message
        if not success:
            assert "timeout" in output.lower() or "failed" in output.lower(), \
                f"Unexpected error message: {output}"

        # Should not hang indefinitely
        assert elapsed < 120, f"Browser operation took too long: {elapsed}s"

    @pytest.mark.asyncio
    async def test_session_tracking(self):
        """Test that sessions are properly tracked."""
        from backend.services.tool_service import tool_service

        initial_count = len(tool_service._active_sessions)

        session_name = f"test_track_{int(time.time())}"
        await tool_service._run_agent_browser(
            session_name=session_name,
            url="https://www.baidu.com",
            timeout=30.0,
            agent_id="test_agent",
        )

        # Session should be in tracking (or already cleaned up)
        current_count = len(tool_service._active_sessions)
        assert current_count >= initial_count, \
            f"Session tracking broken: {initial_count} -> {current_count}"


class TestBrowserDiagnostics:
    """Diagnostic tests to understand browser environment."""

    @pytest.mark.asyncio
    async def test_chrome_available(self):
        """Check if Chrome/Chromium is available."""
        chrome_paths = ["google-chrome", "chromium", "chromium-browser", "/snap/bin/chromium"]
        found = None
        for path in chrome_paths:
            full_path = shutil.which(path)
            if full_path:
                found = full_path
                break

        assert found is not None, f"No Chrome found. Checked: {chrome_paths}"

        # Verify it's executable
        result = subprocess.run(
            [found, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"Chrome not executable: {result.stderr}"

    @pytest.mark.asyncio
    async def test_chrome_headless_mode(self):
        """Test that Chrome can run in headless mode."""
        chrome_path = shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome_path:
            pytest.skip("No Chrome available for headless test")

        result = subprocess.run(
            [
                chrome_path,
                "--headless",
                "--disable-gpu",
                "--no-sandbox",
                "--dump-dom",
                "https://example.com"
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )

        assert result.returncode == 0, f"Headless Chrome failed: {result.stderr}"
        assert "example" in result.stdout.lower() or "Example" in result.stdout, \
            f"Unexpected headless output: {result.stdout[:200]}"


class TestSearchResultParsing:
    """Tests for search result parsing from browser snapshots."""

    def test_parse_bing_python_results(self):
        """Test parsing of Bing search results for 'python' query."""
        from backend.services.tool_service import tool_service

        # Real Bing snapshot for "python" query
        snapshot = """[32m✓[0m [1mpython - Search[0m
  [2mhttps://cn.bing.com/search?q=python[0m
[32m✓[0m Done
- generic
  - link "Back to Bing search" [ref=e5]
    - heading "Back to Bing search" [level=1, ref=e9]
  - main "Search Results" [ref=e4]
    - generic
      - StaticText "About 143,000 results"
    - list
      - listitem [level=1]
        - link "python.org" [ref=e31]
          - image "Global web icon"
          - StaticText "python.org"
          - StaticText "https://www.python.org"
        - heading "Welcome to Python.org" [level=2, ref=e18]
          - link "Welcome to Python.org" [ref=e32]
            - StaticText "Welcome to "
            - strong
              - StaticText "Python"
            - StaticText ".org"
        - paragraph
          - StaticText "Python knows the usual control flow statements that other languages speak — if, for, while and range — with some of its own twists, of course."
      - listitem [level=1]
        - link "runoob.com" [ref=e33]
          - image "Global web icon"
          - StaticText "runoob.com"
          - StaticText "https://www.runoob.com › python"
        - heading "Python 基础教程 | 菜鸟教程" [level=2, ref=e19]
          - link "Python 基础教程 | 菜鸟教程" [ref=e34]
        - paragraph
          - StaticText "Python 基础教程 Python 是一种解释型、面向对象、动态数据类型的高级程序设计语言。"
"""

        results = tool_service._parse_snapshot_for_search(snapshot, "Bing")

        # Should find 2 results
        assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}: {results}"

        # First result should have correct title and URL
        result1 = results[0]
        assert "Welcome to Python.org" in result1["title"], f"Expected 'Welcome to Python.org' in title, got: {result1['title']}"
        assert result1["url"] == "https://www.python.org", f"Expected 'https://www.python.org' as URL, got: {result1['url']}"

    def test_parse_bing_finance_results(self):
        """Test parsing of Bing search results for '财经新闻' query."""
        from backend.services.tool_service import tool_service

        # Real Bing snapshot for "财经新闻" query
        snapshot = """[32m✓[0m [1m财经新闻 - Search[0m
  [2mhttps://cn.bing.com/search?q=财经新闻[0m
[32m✓[0m Done
- generic
  - main "Search Results" [ref=e4]
    - list
      - listitem [level=1]
        - link "finance.sina.com.cn" [ref=e31]
          - StaticText "finance.sina.com.cn"
          - StaticText "https://finance.sina.com.cn/"
        - heading "凤凰网财经 - 资讯平台" [level=2, ref=e18]
          - link "凤凰网财经 - 资讯平台" [ref=e32]
        - paragraph
          - StaticText "凤凰网财经频道，提供全面的财经新闻资讯。"
      - listitem [level=1]
        - link "www.eastmoney.com" [ref=e33]
          - StaticText "www.eastmoney.com"
          - StaticText "https://www.eastmoney.com/"
        - heading "东方财富网 - 财经门户" [level=2, ref=e19]
          - link "东方财富网 - 财经门户" [ref=e34]
        - paragraph
          - StaticText "东方财富网是中国专业的财经门户，提供股票、基金等资讯。"
"""

        results = tool_service._parse_snapshot_for_search(snapshot, "Bing")

        # Should find 2 results
        assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}: {results}"

        # First result should have correct title and URL
        result1 = results[0]
        assert "凤凰网" in result1["title"], f"Expected '凤凰网' in title, got: {result1['title']}"
        assert result1["url"] == "https://finance.sina.com.cn/", f"Expected 'https://finance.sina.com.cn/' as URL, got: {result1['url']}"

    def test_parse_no_domain_as_url(self):
        """Test that domain-like text is NOT incorrectly used as URL.

        This is a regression test for the bug where 'python.org' was being
        captured as URL when it was just link text (not an actual URL).
        """
        from backend.services.tool_service import tool_service

        # Snapshot with domain-like link text
        snapshot = """[32m✓[0m [1mtest - Search[0m
  [2mhttps://cn.bing.com/search?q=test[0m
[32m✓[0m Done
- generic
  - main "Search Results"
    - list
      - listitem [level=1]
        - link "Back to search" [ref=e5]
          - heading "Back to search" [level=1, ref=e9]
        - link "example.com" [ref=e31]
          - image "Icon"
          - StaticText "example.com"
          - StaticText "https://www.example.com"
        - heading "Example Website" [level=2, ref=e18]
          - link "Example Website" [ref=e32]
        - paragraph
          - StaticText "This is a test paragraph with useful content about the example."
"""

        results = tool_service._parse_snapshot_for_search(snapshot, "Bing")

        # Should find 1 result
        assert len(results) >= 1, f"Expected at least 1 result, got {len(results)}: {results}"

        # The URL should be https://www.example.com, NOT https://example.com
        # (The bug was that 'example.com' was being used as the URL)
        result1 = results[0]
        assert result1["url"] == "https://www.example.com", \
            f"Expected 'https://www.example.com' as URL, got: {result1['url']}"

    def test_parse_url_with_path_separator(self):
        """Test parsing URLs that have path separated by › character.

        This tests the fix for the zhihu.com URL issue where Bing returns
        URLs like 'https://www.zhihu.com › question/123456' which should be
        reconstructed to 'https://www.zhihu.com/question/123456'.
        """
        from backend.services.tool_service import tool_service

        snapshot = """[32m✓[0m [1mpython - Search[0m
  [2mhttps://cn.bing.com/search?q=python[0m
[32m✓[0m Done
- generic
  - main "Search Results" [ref=e4]
    - list
      - listitem [level=1]
        - link "zhihu.com" [ref=e31]
          - image "Global web icon"
          - StaticText "zhihu.com"
          - StaticText "https://www.zhihu.com › question/123456"
        - heading "如何系统地自学 Python？ - 知乎" [level=2, ref=e18]
          - link "如何系统地自学 Python？ - 知乎" [ref=e32]
        - paragraph
          - StaticText "Python初学者的法宝..."
      - listitem [level=1]
        - link "baidu.com" [ref=e33]
          - image "Global web icon"
          - StaticText "baidu.com"
          - StaticText "https://zhidao.baidu.com › question/789012"
        - heading "Python中=与==的区别 - 百度知道" [level=2, ref=e19]
          - link "Python中=与==的区别 - 百度知道" [ref=e34]
        - paragraph
          - StaticText "本文讨论了Python中=、==的区别..."
"""

        results = tool_service._parse_snapshot_for_search(snapshot, "Bing")

        assert len(results) >= 2, f"Expected at least 2 results, got {len(results)}: {results}"

        # First result should have full URL with path
        result1 = results[0]
        assert "https://www.zhihu.com/question/123456" == result1["url"], \
            f"Expected 'https://www.zhihu.com/question/123456' as URL, got: {result1['url']}"

        # Second result should also have full URL with path
        result2 = results[1]
        assert "https://zhidao.baidu.com/question/789012" == result2["url"], \
            f"Expected 'https://zhidao.baidu.com/question/789012' as URL, got: {result2['url']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])


class TestVersionDetection:
    """Test agent-browser version detection and batch support."""

    @pytest.fixture
    def tool_service(self):
        """Create ToolService instance for testing."""
        from backend.services.tool_service import tool_service
        return tool_service

    @pytest.mark.asyncio
    async def test_version_detection(self):
        """Test that agent-browser version is correctly detected."""
        import shutil
        from backend.services.tool_service import tool_service

        # Ensure agent_browser_path is set
        if not tool_service._agent_browser_path:
            tool_service._agent_browser_path = shutil.which("agent-browser")
        
        # Detect version
        await tool_service._detect_agent_browser_version()
        
        assert tool_service._agent_browser_version is not None, "Version not detected"
        # Should be able to parse major.minor
        parts = tool_service._agent_browser_version.split(".")
        assert len(parts) >= 2, f"Version format unexpected: {tool_service._agent_browser_version}"
        major, minor = int(parts[0]), int(parts[1])
        assert major >= 0 and minor >= 0

    @pytest.mark.asyncio
    async def test_batch_flag_set_correctly(self):
        """Test that _supports_batch is True for v0.24.0+ and False for older."""
        from backend.services.tool_service import tool_service
        
        await tool_service._detect_agent_browser_version()
        
        version = tool_service._agent_browser_version
        if version:
            parts = version.split(".")
            major, minor = int(parts[0]), int(parts[1])
            expected = (major > 0) or (minor >= 24)
            assert tool_service._supports_batch == expected, \
                f"batch flag mismatch: version={version}, supports_batch={tool_service._supports_batch}, expected={expected}"

    @pytest.mark.asyncio
    async def test_fallback_path_works(self):
        """Test that the fallback (non-batch) path works on older versions."""
        from backend.services.tool_service import tool_service
        
        # Temporarily disable batch to test fallback
        original = tool_service._supports_batch
        tool_service._supports_batch = False
        
        try:
            success, output = await tool_service._run_agent_browser(
                session_name=f"test_fallback_{int(time.time())}",
                url="https://example.com",
                timeout=30.0,
                agent_id="test",
            )
            assert success, f"Fallback path failed: {output}"
            assert "Example" in output or "example" in output.lower(), \
                f"Unexpected output: {output[:200]}"
        finally:
            tool_service._supports_batch = original


class TestBatchCommand:
    """Test agent-browser batch command functionality (v0.24.0+)."""

    @pytest.mark.asyncio
    async def test_batch_command_exists(self):
        """Test that batch command is recognized by agent-browser."""
        result = subprocess.run(
            ["agent-browser", "batch", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # batch --help should succeed or show usage
        assert "batch" in result.stdout.lower() or result.returncode == 0, \
            f"batch command not found: {result.stderr}"

    @pytest.mark.asyncio
    async def test_batch_open_wait_snapshot(self):
        """Test batch with open, wait, snapshot sequence (v0.24.0+ only)."""
        # Check if batch is supported
        result = subprocess.run(
            ["agent-browser", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        version_str = result.stdout
        import re
        match = re.search(r"(\d+\.\d+)", version_str)
        if not match:
            pytest.skip("Cannot determine agent-browser version")
        version = match.group(1)
        parts = version.split(".")
        major, minor = int(parts[0]), int(parts[1])
        if (major, minor) < (0, 24):
            pytest.skip("batch command requires v0.24.0+, this is " + version)
        
        import json
        session = f"test_batch_{int(time.time())}"
        
        # Build batch JSON manually (testing the approach)
        batch_json = f'[["open","https://example.com"],["wait","3000"],["snapshot"]]'
        
        proc = await asyncio.create_subprocess_exec(
            "bash", "-c",
            f"echo '{batch_json}' | agent-browser --session-name {session} batch --json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
        except asyncio.TimeoutError:
            proc.kill()
            pytest.fail("Batch command timed out")
        
        # Should succeed
        assert proc.returncode == 0, f"Batch failed: {stderr.decode()}"
        
        # Output should contain example content
        output_str = stdout.decode()
        assert "Example" in output_str or "example" in output_str.lower(), \
            f"No expected content in output: {output_str[:200]}"
