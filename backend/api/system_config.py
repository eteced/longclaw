"""
System Configuration API for LongClaw.
Supports export/import and configuration profiles.
"""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import db_manager
from backend.services.config_service import config_service

router = APIRouter()


# ==================== Schemas ====================


class SystemConfigItem(BaseModel):
    """Schema for a system configuration item."""

    key: str
    value: str
    description: str | None = None
    updated_at: str
    metadata: dict[str, Any] | None = None


class SystemConfigUpdate(BaseModel):
    """Schema for updating a system configuration."""

    value: str


class SystemConfigBatchUpdate(BaseModel):
    """Schema for batch updating configurations."""

    configs: dict[str, str]


class ConfigImportData(BaseModel):
    """Schema for importing configurations.

    Supports both legacy format (v1.0 with 'configs' key) and new format (v2.0
    with 'system_configs', 'agent_settings', 'model_settings', 'profiles').
    """

    version: str = "2.0"
    # Legacy format (v1.0): configs = {key: value}
    configs: dict[str, Any] | None = None
    # New format (v2.0): system_configs = {key: {value, description}}
    system_configs: dict[str, Any] | None = None
    agent_settings: dict[str, Any] | None = None
    # Note: using 'model_settings' instead of 'model_config' to avoid Pydantic conflict
    model_settings: dict[str, Any] | None = Field(None, alias="model_config")
    profiles: list[dict[str, Any]] | None = None


class ConfigProfileCreate(BaseModel):
    """Schema for creating a configuration profile."""

    name: str
    description: str | None = None
    config_data: dict[str, str] | None = None


class ConfigProfileUpdate(BaseModel):
    """Schema for updating a configuration profile."""

    name: str | None = None
    description: str | None = None
    config_data: dict[str, str] | None = None


# ==================== Dependency ====================


async def get_session() -> AsyncSession:
    """Get database session dependency.

    Yields:
        AsyncSession instance.
    """
    async with db_manager.session() as session:
        yield session


# ==================== Configuration Endpoints ====================


@router.get("", response_model=list[SystemConfigItem])
async def get_all_configs() -> list[SystemConfigItem]:
    """Get all system configurations.

    Returns:
        List of system configurations.
    """
    configs = await config_service.get_all()
    return [SystemConfigItem(**config) for config in configs]


@router.get("/categories")
async def get_config_categories() -> dict[str, Any]:
    """Get configuration categories and metadata.

    Returns:
        Dictionary with categories and metadata.
    """
    return {
        "categories": config_service.get_categories(),
        "metadata": config_service.get_metadata(),
        "unlimited_value": config_service.UNLIMITED_VALUE,
    }


@router.put("")
async def batch_update_configs(data: SystemConfigBatchUpdate) -> dict[str, Any]:
    """Batch update multiple configurations.

    Args:
        data: Batch update data.

    Returns:
        Update result.
    """
    await config_service.set_multiple(data.configs)
    return {
        "updated": len(data.configs),
        "keys": list(data.configs.keys()),
    }


@router.post("/reset", response_model=list[SystemConfigItem])
async def reset_configs() -> list[SystemConfigItem]:
    """Reset all configurations to default values.

    Returns:
        List of all configurations after reset.
    """
    await config_service.reset_to_defaults()
    configs = await config_service.get_all()
    return [SystemConfigItem(**config) for config in configs]


# ==================== Export/Import Endpoints ====================


@router.get("/export/json")
async def export_config_json() -> dict[str, Any]:
    """Export all configurations as JSON (legacy format, system configs only).

    Returns:
        JSON export of system configurations.
    """
    return await config_service.export_config()


@router.get("/export/full")
async def export_config_full() -> dict[str, Any]:
    """Export all configurations including agent settings and model config.

    Returns:
        JSON export of all configurations.
    """
    return await config_service.export_full_config()


@router.post("/import")
async def import_config(
    data: ConfigImportData,
    merge: bool = True,
) -> dict[str, Any]:
    """Import configurations from JSON data.

    Supports both legacy format (v1.0 with 'configs' key) and new format (v2.0
    with 'system_configs', 'agent_settings', 'model_settings', 'profiles').

    Args:
        data: Configuration import data.
        merge: If True, merge with existing; if False, replace all.

    Returns:
        Import result summary.
    """
    try:
        result = await config_service.import_config(data.model_dump(by_alias=True), merge=merge)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ==================== Profile Endpoints ====================
# IMPORTANT: These must be defined BEFORE the /{key} routes to avoid path conflicts


@router.get("/profiles", response_model=list[dict[str, Any]])
async def get_profiles() -> list[dict[str, Any]]:
    """Get all configuration profiles.

    Returns:
        List of profiles.
    """
    return await config_service.get_profiles()


@router.get("/profiles/{profile_id}", response_model=dict[str, Any] | None)
async def get_profile(profile_id: str) -> dict[str, Any] | None:
    """Get a specific configuration profile.

    Args:
        profile_id: Profile ID or name.

    Returns:
        Profile data.
    """
    profile = await config_service.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return profile


@router.post("/profiles", response_model=dict[str, Any])
async def create_profile(data: ConfigProfileCreate) -> dict[str, Any]:
    """Create a new configuration profile.

    Args:
        data: Profile creation data.

    Returns:
        Created profile.
    """
    try:
        profile = await config_service.create_profile(
            name=data.name,
            description=data.description,
            config_data=data.config_data,
        )
        return profile
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/profiles/{profile_id}", response_model=dict[str, Any])
async def update_profile(
    profile_id: str,
    data: ConfigProfileUpdate,
) -> dict[str, Any]:
    """Update a configuration profile.

    Args:
        profile_id: Profile ID.
        data: Profile update data.

    Returns:
        Updated profile.
    """
    profile = await config_service.update_profile(
        profile_id,
        name=data.name,
        description=data.description,
        config_data=data.config_data,
    )
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return profile


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str) -> dict[str, Any]:
    """Delete a configuration profile.

    Args:
        profile_id: Profile ID.

    Returns:
        Deletion result.
    """
    deleted = await config_service.delete_profile(profile_id)
    if not deleted:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete profile '{profile_id}' (not found or is default)"
        )
    return {"deleted": True, "profile_id": profile_id}


@router.post("/profiles/{profile_id}/load")
async def load_profile(profile_id: str) -> dict[str, Any]:
    """Load and apply a configuration profile.

    Args:
        profile_id: Profile ID or name.

    Returns:
        Load result.
    """
    try:
        result = await config_service.load_profile(profile_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/profiles/{profile_id}/save")
async def save_to_profile(profile_id: str) -> dict[str, Any]:
    """Save current configuration to an existing profile.

    Args:
        profile_id: Profile ID.

    Returns:
        Updated profile.
    """
    profile = await config_service.save_current_to_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_id}' not found")
    return profile


# ==================== Single Config Endpoints ====================
# IMPORTANT: These must be defined AFTER all static path routes


@router.get("/{key}", response_model=SystemConfigItem)
async def get_config(key: str) -> SystemConfigItem:
    """Get a specific configuration.

    Args:
        key: Configuration key.

    Returns:
        Configuration item.

    Raises:
        HTTPException: If config not found.
    """
    configs = await config_service.get_all()
    for config in configs:
        if config["key"] == key:
            return SystemConfigItem(**config)

    raise HTTPException(status_code=404, detail=f"Config '{key}' not found")


@router.put("/{key}", response_model=SystemConfigItem)
async def update_config(
    key: str,
    data: SystemConfigUpdate,
    session: AsyncSession = Depends(get_session),
) -> SystemConfigItem:
    """Update a configuration value.

    Args:
        key: Configuration key.
        data: Update data.
        session: Database session.

    Returns:
        Updated configuration item.

    Raises:
        HTTPException: If config not found.
    """
    configs = await config_service.get_all()
    existing = None
    for config in configs:
        if config["key"] == key:
            existing = config
            break

    if not existing:
        raise HTTPException(status_code=404, detail=f"Config '{key}' not found")

    await config_service.set(key, data.value, session)

    updated_configs = await config_service.get_all()
    for config in updated_configs:
        if config["key"] == key:
            return SystemConfigItem(**config)

    raise HTTPException(status_code=500, detail="Failed to update config")
