"""
Skill Service for LongClaw.
Provides skill lookup and management for agents.
"""
import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import frontmatter

from backend.database import db_manager

logger = logging.getLogger(__name__)

# Skill storage directory
SKILLS_DIR = Path(__file__).parent.parent / "skills"
BUILTIN_SKILLS_DIR = SKILLS_DIR / "builtin"
CUSTOM_SKILLS_DIR = SKILLS_DIR / "custom"


class SkillService:
    """Service for managing and searching skills."""

    def __init__(self) -> None:
        """Initialize the skill service."""
        self._skills_dir = SKILLS_DIR
        self._builtin_dir = BUILTIN_SKILLS_DIR
        self._custom_dir = CUSTOM_SKILLS_DIR
        self._initialized = False

    async def init(self) -> None:
        """Initialize the skill service.

        Creates skill directories and registers builtin skills in the database.
        """
        if self._initialized:
            return

        # Create directories
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        self._builtin_dir.mkdir(parents=True, exist_ok=True)
        self._custom_dir.mkdir(parents=True, exist_ok=True)

        # Register builtin skills
        await self._register_builtin_skills()

        self._initialized = True
        logger.info(f"Skill service initialized at {self._skills_dir}")

    async def close(self) -> None:
        """Close the skill service."""
        self._initialized = False
        logger.info("Skill service closed")

    async def _register_builtin_skills(self) -> None:
        """Scan builtin skills directory and register them in the database."""
        if not self._builtin_dir.exists():
            return

        await db_manager.init()
        async with db_manager.session() as session:
            for category_dir in self._builtin_dir.iterdir():
                if not category_dir.is_dir():
                    continue
                category = category_dir.name

                for skill_file in category_dir.glob("*.md"):
                    name = skill_file.stem
                    skill_path = f"builtin/{category}/{name}.md"

                    # Parse frontmatter for description
                    try:
                        with open(skill_file, "r", encoding="utf-8") as f:
                            content = f.read()
                        parsed = frontmatter.loads(content)
                        description = parsed.metadata.get("description", f"{name} skill")
                    except Exception:
                        description = f"{name} skill"

                    # Check if already registered
                    from sqlalchemy import select
                    from backend.models import Skill

                    result = await session.execute(
                        select(Skill).where(Skill.name == name)
                    )
                    existing = result.scalar_one_or_none()

                    if not existing:
                        skill = Skill(
                            id=str(uuid.uuid4()),
                            name=name,
                            category=category,
                            description=description,
                            file_path=skill_path,
                            is_builtin=True,
                        )
                        session.add(skill)
                        logger.info(f"Registered builtin skill: {name} ({category})")

            await session.commit()

    async def get_skill(self, name: str) -> dict[str, Any] | None:
        """Get a skill by name.

        Args:
            name: Skill name.

        Returns:
            Skill data dict with name, category, description, content, or None if not found.
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select
            from backend.models import Skill

            result = await session.execute(
                select(Skill).where(Skill.name == name)
            )
            skill = result.scalar_one_or_none()

            if not skill:
                return None

            # Read content from file
            file_path = self._skills_dir / skill.file_path
            if not file_path.exists():
                logger.warning(f"Skill file not found: {file_path}")
                return None

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                parsed = frontmatter.loads(content)
                return {
                    "name": skill.name,
                    "category": skill.category,
                    "description": skill.description,
                    "content": str(parsed.content),
                    "is_builtin": skill.is_builtin,
                    "created_at": skill.created_at.isoformat() if skill.created_at else None,
                    "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
                }
            except Exception as e:
                logger.error(f"Error reading skill file {file_path}: {e}")
                return None

    async def search_skills(self, query: str) -> list[dict[str, Any]]:
        """Search skills by query.

        Searches both skill names and content.

        Args:
            query: Search query.

        Returns:
            List of matching skill data dicts.
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select, or_
            from backend.models import Skill

            # First get matching skills from DB by name/description
            search_pattern = f"%{query}%"
            result = await session.execute(
                select(Skill).where(
                    or_(
                        Skill.name.ilike(search_pattern),
                        Skill.description.ilike(search_pattern),
                    )
                )
            )
            skills = result.scalars().all()

            results = []
            for skill in skills:
                # Read content and check if query matches content
                file_path = self._skills_dir / skill.file_path
                if not file_path.exists():
                    continue

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Parse frontmatter
                    parsed = frontmatter.loads(content)
                    plain_content = parsed.content.lower()

                    # Check if query is in name, description, or content
                    if (query.lower() in skill.name.lower() or
                        query.lower() in skill.description.lower() or
                        query.lower() in plain_content):

                        results.append({
                            "name": skill.name,
                            "category": skill.category,
                            "description": skill.description,
                            "content": str(parsed.content),
                            "is_builtin": skill.is_builtin,
                        })
                except Exception as e:
                    logger.error(f"Error reading skill file {file_path}: {e}")
                    continue

            return results

    async def list_skills(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all skills.

        Args:
            category: Optional category filter.

        Returns:
            List of skill data dicts (without content).
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select
            from backend.models import Skill

            if category:
                result = await session.execute(
                    select(Skill).where(Skill.category == category).order_by(Skill.name)
                )
            else:
                result = await session.execute(
                    select(Skill).order_by(Skill.category, Skill.name)
                )

            skills = result.scalars().all()
            return [
                {
                    "name": s.name,
                    "category": s.category,
                    "description": s.description,
                    "is_builtin": s.is_builtin,
                }
                for s in skills
            ]

    async def list_categories(self) -> list[str]:
        """List all skill categories.

        Returns:
            List of category names.
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select, func
            from backend.models import Skill

            result = await session.execute(
                select(Skill.category).distinct().order_by(Skill.category)
            )
            return [row[0] for row in result.fetchall()]

    async def create_skill(
        self,
        name: str,
        category: str,
        description: str,
        content: str,
    ) -> dict[str, Any]:
        """Create a new skill.

        Args:
            name: Skill name.
            category: Skill category.
            description: Skill description.
            content: Skill content in Markdown.

        Returns:
            Created skill data dict.

        Raises:
            ValueError: If skill with name already exists.
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select
            from backend.models import Skill

            # Check if already exists
            result = await session.execute(
                select(Skill).where(Skill.name == name)
            )
            existing = result.scalar_one_or_none()
            if existing:
                raise ValueError(f"Skill '{name}' already exists")

            # Create skill file
            category_dir = self._custom_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            file_path = category_dir / f"{name}.md"

            # Write content with frontmatter
            post = frontmatter.Post(content)
            post.metadata = {
                "name": name,
                "category": category,
                "description": description,
            }
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(frontmatter.dumps(post))

            # Create database entry
            skill = Skill(
                id=str(uuid.uuid4()),
                name=name,
                category=category,
                description=description,
                file_path=f"custom/{category}/{name}.md",
                is_builtin=False,
            )
            session.add(skill)
            await session.commit()

            return {
                "name": skill.name,
                "category": skill.category,
                "description": skill.description,
                "content": content,
                "is_builtin": False,
            }

    async def update_skill(
        self,
        name: str,
        description: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing skill.

        Args:
            name: Skill name.
            description: Optional new description.
            content: Optional new content.

        Returns:
            Updated skill data dict.

        Raises:
            ValueError: If skill is builtin (read-only) or not found.
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select
            from backend.models import Skill

            result = await session.execute(
                select(Skill).where(Skill.name == name)
            )
            skill = result.scalar_one_or_none()

            if not skill:
                raise ValueError(f"Skill '{name}' not found")

            if skill.is_builtin:
                raise ValueError(f"Builtin skill '{name}' cannot be modified")

            updated = False

            # Update file if content provided
            if content is not None:
                file_path = self._skills_dir / skill.file_path
                if not file_path.exists():
                    raise ValueError(f"Skill file not found: {file_path}")

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        existing = f.read()
                    parsed = frontmatter.loads(existing)
                    parsed.content = content
                    if description:
                        parsed.metadata["description"] = description
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(frontmatter.dumps(parsed))
                    updated = True
                except Exception as e:
                    raise ValueError(f"Failed to update skill file: {e}")

            # Update description in DB if provided
            if description is not None:
                skill.description = description
                updated = True

            if updated:
                await session.commit()

            return {
                "name": skill.name,
                "category": skill.category,
                "description": skill.description,
                "content": content if content is not None else "",
                "is_builtin": skill.is_builtin,
            }

    async def delete_skill(self, name: str) -> None:
        """Delete a skill.

        Args:
            name: Skill name.

        Raises:
            ValueError: If skill is builtin (read-only) or not found.
        """
        await db_manager.init()
        async with db_manager.session() as session:
            from sqlalchemy import select, delete
            from backend.models import Skill

            result = await session.execute(
                select(Skill).where(Skill.name == name)
            )
            skill = result.scalar_one_or_none()

            if not skill:
                raise ValueError(f"Skill '{name}' not found")

            if skill.is_builtin:
                raise ValueError(f"Builtin skill '{name}' cannot be deleted")

            # Delete file
            file_path = self._skills_dir / skill.file_path
            if file_path.exists():
                file_path.unlink()

            # Delete from database
            await session.execute(
                delete(Skill).where(Skill.name == name)
            )
            await session.commit()


# Global singleton instance
skill_service = SkillService()
