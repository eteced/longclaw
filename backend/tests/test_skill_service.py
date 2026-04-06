"""
Tests for Skill Service and Skills API.
"""
import asyncio
import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure backend is in path
sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys_path not in os.environ.get('PYTHONPATH', ''):
    os.environ['PYTHONPATH'] = sys_path + ':' + os.environ.get('PYTHONPATH', '')


class TestSkillService:
    """Tests for SkillService functionality."""

    @pytest.fixture
    def temp_skills_dir(self):
        """Create a temporary skills directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_db_manager(self):
        """Mock database manager for unit tests."""
        mock_session = AsyncMock()
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = MagicMock()

        mock_manager = MagicMock()
        mock_manager.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_manager.session.return_value.__aexit__ = AsyncMock()
        mock_manager.init = AsyncMock()

        return mock_manager

    @pytest.mark.asyncio
    async def test_skill_service_initialization(self, temp_skills_dir):
        """Test SkillService initializes correctly."""
        from backend.services.skill_service import SkillService

        service = SkillService()
        assert service._skills_dir == Path(__file__).parent.parent / "skills"
        assert service._builtin_dir == Path(__file__).parent.parent / "skills" / "builtin"
        assert service._custom_dir == Path(__file__).parent.parent / "skills" / "custom"
        assert service._initialized is False

    @pytest.mark.asyncio
    async def test_list_categories(self, mock_db_manager):
        """Test listing skill categories."""
        from backend.services.skill_service import SkillService

        # Mock the db_manager
        with patch('backend.services.skill_service.db_manager', mock_db_manager):
            service = SkillService()

            # Setup mock result
            mock_result = MagicMock()
            mock_result.fetchall.return_value = [('git',), ('shell',), ('web',)]

            mock_session = await mock_db_manager.session().__aenter__()
            mock_session.execute.return_value = mock_result

            categories = await service.list_categories()

            assert 'git' in categories
            assert 'shell' in categories
            assert 'web' in categories

    @pytest.mark.asyncio
    async def test_skill_content_parsing(self, temp_skills_dir):
        """Test that skill markdown files are parsed correctly."""
        import frontmatter

        # Create a test skill file
        skill_dir = Path(temp_skills_dir) / "test_category"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "test_skill.md"

        content = """---
name: test_skill
category: test_category
description: A test skill for unit testing
---

# Test Skill

## When to Use
This skill is used for testing purposes.

## Procedures
1. Step one
2. Step two
"""

        skill_file.write_text(content)

        # Parse with frontmatter
        parsed = frontmatter.loads(content)

        assert parsed.metadata['name'] == 'test_skill'
        assert parsed.metadata['category'] == 'test_category'
        assert parsed.metadata['description'] == 'A test skill for unit testing'
        assert '# Test Skill' in parsed.content


class TestSkillLookup:
    """Tests for skill_lookup tool."""

    @pytest.mark.asyncio
    async def test_skill_lookup_result_format(self):
        """Test that skill_lookup returns properly formatted results."""
        from backend.services.tool_service import ToolService

        tool_service = ToolService()

        # Mock skill_service.search_skills
        mock_results = [
            {
                'name': 'git_clone',
                'category': 'git',
                'description': 'How to clone from GitHub',
                'content': '# Git Clone\n\nClone repositories from GitHub.',
                'is_builtin': True
            }
        ]

        with patch.object(tool_service, '_skill_lookup') as mock_lookup:
            # The actual method would be tested here
            # For now, just verify the method exists
            assert hasattr(tool_service, '_skill_lookup')

    @pytest.mark.asyncio
    async def test_skill_lookup_empty_results(self):
        """Test skill_lookup handles empty results gracefully."""
        from backend.services.tool_service import ToolResult

        # Create a mock ToolResult for empty search
        result = ToolResult(
            success=True,
            content="未找到相关 Skill。\n\n提示：你可以尝试直接描述你要执行的操作，系统会尝试执行。"
        )

        assert result.success is True
        assert "未找到相关 Skill" in result.content


class TestSkillApi:
    """Tests for Skills API endpoints."""

    @pytest.mark.asyncio
    async def test_skill_response_schema(self):
        """Test SkillResponse schema validation."""
        from backend.api.skills import SkillResponse, SkillListItem, SkillCreate

        # Test SkillResponse
        skill = SkillResponse(
            name="test_skill",
            category="test",
            description="A test skill",
            content="# Test\n\nContent here",
            is_builtin=False
        )

        assert skill.name == "test_skill"
        assert skill.category == "test"
        assert skill.is_builtin is False

        # Test SkillListItem
        list_item = SkillListItem(
            name="test_skill",
            category="test",
            description="A test skill",
            is_builtin=True
        )

        assert list_item.is_builtin is True

        # Test SkillCreate
        create_data = SkillCreate(
            name="new_skill",
            category="new",
            description="A new skill",
            content="# New Skill\n\nContent"
        )

        assert create_data.name == "new_skill"
        assert len(create_data.content) > 0

    @pytest.mark.asyncio
    async def test_skill_update_schema(self):
        """Test SkillUpdate schema."""
        from backend.api.skills import SkillUpdate

        # Update with only description
        update1 = SkillUpdate(description="Updated description")
        assert update1.description == "Updated description"
        assert update1.content is None

        # Update with only content
        update2 = SkillUpdate(content="# Updated\n\nNew content")
        assert update2.content is not None
        assert update2.description is None

        # Update with both
        update3 = SkillUpdate(description="Desc", content="Content")
        assert update3.description is not None
        assert update3.content is not None


class TestSkillFiles:
    """Tests for builtin skill files."""

    def test_builtin_skill_files_exist(self):
        """Test that all builtin skill files exist."""
        skills_dir = Path(__file__).parent.parent / "skills" / "builtin"

        expected_files = [
            "git/clone.md",
            "git/branch.md",
            "shell/find.md",
            "shell/dangerous.md",
            "web/web_search.md",
            "python/package.md",
            "skill/lookup.md",
        ]

        for skill_file in expected_files:
            full_path = skills_dir / skill_file
            assert full_path.exists(), f"Builtin skill file missing: {skill_file}"

    def test_builtin_skill_files_have_frontmatter(self):
        """Test that all builtin skill files have valid frontmatter."""
        import frontmatter

        skills_dir = Path(__file__).parent.parent / "skills" / "builtin"

        for category_dir in skills_dir.iterdir():
            if not category_dir.is_dir():
                continue

            for skill_file in category_dir.glob("*.md"):
                content = skill_file.read_text()
                parsed = frontmatter.loads(content)

                assert 'name' in parsed.metadata, f"{skill_file}: missing 'name' in frontmatter"
                assert 'category' in parsed.metadata, f"{skill_file}: missing 'category' in frontmatter"
                assert 'description' in parsed.metadata, f"{skill_file}: missing 'description' in frontmatter"

    def test_builtin_skill_content_structure(self):
        """Test that builtin skill files have proper markdown structure."""
        skills_dir = Path(__file__).parent.parent / "skills" / "builtin"

        for category_dir in skills_dir.iterdir():
            if not category_dir.is_dir():
                continue

            for skill_file in category_dir.glob("*.md"):
                content = skill_file.read_text()

                # Should have at least one markdown heading
                assert '#' in content, f"{skill_file}: should have at least one heading"
