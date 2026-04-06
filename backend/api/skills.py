"""
Skills API for LongClaw.
"""
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.skill_service import skill_service

router = APIRouter()


# ==================== Schemas ====================

# Reserved skill names that conflict with API endpoints
RESERVED_SKILL_NAMES = frozenset({
    "search",
    "categories",
    "create",
    "update",
    "delete",
    "list",
})


class SkillResponse(BaseModel):
    """Schema for skill response."""

    name: str
    category: str
    description: str
    content: str | None = None
    is_builtin: bool = False


class SkillListItem(BaseModel):
    """Schema for skill list item (without content)."""

    name: str
    category: str
    description: str
    is_builtin: bool = False


class SkillListResponse(BaseModel):
    """Schema for skill list response."""

    items: list[SkillListItem]
    total: int


class CategoryListResponse(BaseModel):
    """Schema for category list response."""

    categories: list[str]


class SkillCreate(BaseModel):
    """Schema for creating a skill."""

    name: str = Field(..., min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1)
    content: str = Field(default="")


class SkillUpdate(BaseModel):
    """Schema for updating a skill."""

    description: str | None = None
    content: str | None = None


class SkillSearchResponse(BaseModel):
    """Schema for skill search response."""

    items: list[SkillResponse]
    total: int


# ==================== Endpoints ====================


@router.get("", response_model=SkillListResponse)
async def list_skills(
    category: str | None = None,
) -> SkillListResponse:
    """List all skills.

    Args:
        category: Optional category filter.

    Returns:
        List of skills.
    """
    skills = await skill_service.list_skills(category=category)
    return SkillListResponse(
        items=[SkillListItem(**s) for s in skills],
        total=len(skills),
    )


@router.get("/categories", response_model=CategoryListResponse)
async def list_categories() -> CategoryListResponse:
    """List all skill categories.

    Returns:
        List of categories.
    """
    categories = await skill_service.list_categories()
    return CategoryListResponse(categories=categories)


@router.get("/search", response_model=SkillSearchResponse)
async def search_skills(
    q: str = Query(..., min_length=1, description="Search query"),
) -> SkillSearchResponse:
    """Search skills.

    Args:
        q: Search query.

    Returns:
        List of matching skills.
    """
    results = await skill_service.search_skills(q)
    return SkillSearchResponse(
        items=[SkillResponse(**r) for r in results],
        total=len(results),
    )


@router.get("/{skill_name}", response_model=SkillResponse)
async def get_skill(
    skill_name: str,
) -> SkillResponse:
    """Get a skill by name.

    Args:
        skill_name: Skill name.

    Returns:
        Skill details with content.

    Raises:
        HTTPException: If skill not found.
    """
    skill = await skill_service.get_skill(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    return SkillResponse(**skill)


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(
    skill_data: SkillCreate,
) -> SkillResponse:
    """Create a new skill.

    Args:
        skill_data: Skill data.

    Returns:
        Created skill.

    Raises:
        HTTPException: If skill already exists or creation fails.
    """
    # Validate skill name
    if skill_data.name.lower() in RESERVED_SKILL_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Skill name '{skill_data.name}' is reserved. Please use a different name."
        )

    try:
        skill = await skill_service.create_skill(
            name=skill_data.name,
            category=skill_data.category,
            description=skill_data.description,
            content=skill_data.content,
        )
        return SkillResponse(**skill)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create skill: {str(e)}")


@router.put("/{skill_name}", response_model=SkillResponse)
async def update_skill(
    skill_name: str,
    skill_data: SkillUpdate,
) -> SkillResponse:
    """Update a skill.

    Args:
        skill_name: Skill name.
        skill_data: Update data.

    Returns:
        Updated skill.

    Raises:
        HTTPException: If skill not found or is builtin.
    """
    try:
        skill = await skill_service.update_skill(
            name=skill_name,
            description=skill_data.description,
            content=skill_data.content,
        )
        return SkillResponse(**skill)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")


@router.delete("/{skill_name}", status_code=204)
async def delete_skill(
    skill_name: str,
) -> None:
    """Delete a skill.

    Args:
        skill_name: Skill name.

    Raises:
        HTTPException: If skill not found or is builtin.
    """
    try:
        await skill_service.delete_skill(skill_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete skill: {str(e)}")
