"""
API package for LongClaw.
"""
from fastapi import APIRouter

from backend.api.agent_settings import router as agent_settings_router
from backend.api.agents import router as agents_router
from backend.api.channels import router as channels_router
from backend.api.chat import router as chat_router
from backend.api.console import router as console_router
from backend.api.messages import router as messages_router
from backend.api.model_config import router as model_config_router
from backend.api.prompts import router as prompts_router
from backend.api.system_config import router as system_config_router
from backend.api.tasks import router as tasks_router
from backend.api.websocket import router as websocket_router

api_router = APIRouter(prefix="/api")

api_router.include_router(tasks_router, prefix="/tasks", tags=["tasks"])
api_router.include_router(agents_router, prefix="/agents", tags=["agents"])
api_router.include_router(messages_router, prefix="/messages", tags=["messages"])
api_router.include_router(channels_router, prefix="/channels", tags=["channels"])
api_router.include_router(chat_router, prefix="/chat", tags=["chat"])
api_router.include_router(model_config_router, prefix="/model-config", tags=["model-config"])
api_router.include_router(agent_settings_router, prefix="/agent-settings", tags=["agent-settings"])
api_router.include_router(prompts_router, prefix="/prompts", tags=["prompts"])
api_router.include_router(system_config_router, prefix="/system-config", tags=["system-config"])
api_router.include_router(console_router, prefix="/console", tags=["console"])

# WebSocket router is registered directly on the app in main.py (at /ws)

__all__ = ["api_router"]
