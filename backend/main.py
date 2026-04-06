"""
LongClaw - Multi-Agent Task Server
Main entry point.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from backend.agents.resident_agent import ResidentAgent
from backend.api import api_router
from backend.api.websocket import router as websocket_router
from backend.channels.web_channel import WebChannel
from backend.config import get_settings
from backend.database import db_manager
from backend.middleware.auth import AuthMiddleware
from backend.models.agent import AgentStatus, AgentType
from backend.models.channel import ChannelType
from backend.services.agent_registry import agent_registry
from backend.services.agent_service import agent_service
from backend.services.channel_service import channel_service
from backend.services.config_service import config_service
from backend.services.llm_service import llm_service
from backend.services.message_service import message_service
from backend.services.scheduler_service import scheduler_service
from backend.services.provider_scheduler_service import provider_scheduler_service
from backend.services.skill_service import skill_service
from backend.services.tool_service import tool_service

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if get_settings().debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances - support multiple agents and channels
_resident_agents: dict[str, ResidentAgent] = {}
_web_channels: dict[str, WebChannel] = {}


async def register_and_start_resident_agent(agent_id: str) -> ResidentAgent | None:
    """Register and start a resident agent dynamically.

    Args:
        agent_id: The agent ID to register and start.

    Returns:
        The started ResidentAgent instance, or None if not found.
    """
    global _resident_agents

    # Check if already registered
    if agent_id in _resident_agents:
        logger.warning(f"Agent {agent_id} is already registered")
        return _resident_agents[agent_id]

    # Check if already running in this process
    if agent_registry.has_agent(agent_id):
        agent = agent_registry.get_agent(agent_id)
        if agent:
            _resident_agents[agent_id] = agent
            return agent

    # Create new agent instance
    agent = ResidentAgent(agent_id=agent_id)
    await agent.load(agent_id)

    # Register and start
    agent_registry.register_agent(agent)
    await agent.start()

    _resident_agents[agent_id] = agent
    logger.info(f"Dynamically registered and started resident agent: {agent_id}")

    return agent


async def register_and_start_web_channel(channel_id: str) -> WebChannel | None:
    """Register and start a web channel dynamically.

    Args:
        channel_id: The channel ID to register and start.

    Returns:
        The started WebChannel instance, or None if not found.
    """
    global _web_channels

    # Check if already registered
    if channel_id in _web_channels:
        logger.warning(f"Channel {channel_id} is already registered")
        return _web_channels[channel_id]

    # Get channel from DB
    async with db_manager.session() as session:
        from backend.services.channel_service import channel_service
        channel = await channel_service.get_channel(session, channel_id)
        if not channel:
            logger.error(f"Channel {channel_id} not found in DB")
            return None

        # Get the agent
        if not channel.resident_agent_id:
            logger.error(f"Channel {channel_id} has no resident agent bound")
            return None

        agent_id = channel.resident_agent_id

    # Ensure agent is registered and started
    if agent_id not in _resident_agents:
        await register_and_start_resident_agent(agent_id)

    # Create and start web channel
    web_channel = WebChannel(
        channel_id=channel_id,
        resident_agent_id=agent_id,
        config=channel.config,
    )
    await web_channel.start()

    _web_channels[channel_id] = web_channel
    logger.info(f"Dynamically registered and started web channel: {channel_id}")

    return web_channel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    Args:
        app: FastAPI application.
    """
    global resident_agent, web_channel

    logger.info("Starting LongClaw server...")

    # Initialize database
    await db_manager.init()
    logger.info("Database initialized")

    # Create tables if they don't exist
    await db_manager.create_tables()
    logger.info("Database tables created")

    # Initialize config service (loads defaults into DB and cache)
    await config_service.initialize()
    logger.info("Config service initialized")

    # Initialize LLM service
    await llm_service.init()
    logger.info("LLM service initialized")

    # Initialize tool service
    await tool_service.init()
    logger.info("Tool service initialized")

    # Initialize skill service
    await skill_service.init()
    logger.info("Skill service initialized")

    # Initialize message service (Redis)
    await message_service.init()
    logger.info("Message service initialized")

    # Start scheduler
    await scheduler_service.start()
    logger.info("Scheduler started")

    # Start provider scheduler
    await provider_scheduler_service.start()
    logger.info("Provider scheduler started")

    # Initialize resident agent and web channel
    await _init_resident_agents_and_web_channels()

    logger.info("LongClaw server started")

    yield

    # Cleanup
    logger.info("Shutting down LongClaw server...")

    # Stop all web channels
    for channel_id, channel in _web_channels.items():
        await channel.stop()
        logger.info(f"Web channel {channel_id} stopped")

    # Stop all resident agents
    for agent_id, agent in _resident_agents.items():
        await agent.terminate()
        agent_registry.unregister_agent(agent_id)
        logger.info(f"Resident agent {agent_id} terminated")

    await scheduler_service.stop()
    logger.info("Scheduler stopped")

    await provider_scheduler_service.stop()
    logger.info("Provider scheduler stopped")

    await message_service.close()
    logger.info("Message service closed")

    await tool_service.close()
    logger.info("Tool service closed")

    await llm_service.close()
    logger.info("LLM service closed")

    await db_manager.close()
    logger.info("Database closed")

    logger.info("LongClaw server stopped")


async def _init_resident_agents_and_web_channels() -> None:
    """Initialize all resident agents and web channels."""
    global _resident_agents, _web_channels

    # Clear any stale resident agents from registry
    # (agents that were registered but their process is gone)
    for agent in agent_registry.get_all_agents():
        if hasattr(agent, 'agent_type') and agent.agent_type == AgentType.RESIDENT:
            agent_registry.unregister_agent(agent.id)
            logger.warning(f"Unregistered stale resident agent: {agent.id}")

    async with db_manager.session() as session:
        # Get all resident agents (no limit)
        agents = await agent_service.get_agents(
            session,
            agent_type=AgentType.RESIDENT,
            limit=None,  # Get all agents
        )

        if not agents:
            # Create a default resident agent if none exist
            default_agent = ResidentAgent(name="老六")
            await default_agent.persist()
            agents = [default_agent]
            logger.info(f"Created default resident agent: {default_agent.id}")

        # Create agent instances and register them (skip terminated ones)
        for agent_model in agents:
            # Skip terminated agents - they should not be started on restart
            if agent_model.status == AgentStatus.TERMINATED:
                logger.info(f"Skipping terminated agent: {agent_model.id} ({agent_model.name})")
                continue

            agent = ResidentAgent(agent_id=agent_model.id)
            await agent.load(agent_model.id)
            _resident_agents[agent.id] = agent
            agent_registry.register_agent(agent)
            logger.info(f"Registered resident agent: {agent.id} ({agent.name})")

        # Get all active web channels
        channels = await channel_service.get_channels(
            session,
            channel_type=ChannelType.WEB,
            is_active=True,
            limit=None,  # Get all channels
        )

        # Create and start web channels
        for channel_model in channels:
            agent_id = channel_model.resident_agent_id

            # Skip if no agent is bound to this channel
            if not agent_id:
                logger.warning(f"Channel {channel_model.id} has no resident agent, skipping")
                continue

            # Skip if agent is not loaded
            if agent_id not in _resident_agents:
                logger.warning(f"Channel {channel_model.id} references unknown agent {agent_id}, skipping")
                continue

            # Create web channel instance
            web_channel = WebChannel(
                channel_id=channel_model.id,
                resident_agent_id=agent_id,
                config=channel_model.config,
            )
            _web_channels[channel_model.id] = web_channel
            logger.info(f"Created web channel: {channel_model.id}")

        # If no channels were created, create one for the first agent
        if not _web_channels and _resident_agents:
            first_agent_id = list(_resident_agents.keys())[0]
            channel_model = await channel_service.create_channel(
                session,
                channel_type=ChannelType.WEB,
                resident_agent_id=first_agent_id,
            )
            web_channel = WebChannel(
                channel_id=channel_model.id,
                resident_agent_id=first_agent_id,
            )
            _web_channels[channel_model.id] = web_channel
            logger.info(f"Created default web channel: {channel_model.id}")

    # Start all agents
    for agent_id, agent in _resident_agents.items():
        await agent.start()
        logger.info(f"Started resident agent: {agent_id}")

    # Start all web channels
    for channel_id, channel in _web_channels.items():
        await channel.start()
        logger.info(f"Started web channel: {channel_id}")

    logger.info(f"Initialized {len(_resident_agents)} resident agents and {len(_web_channels)} web channels")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application.
    """
    settings = get_settings()

    # API Key security scheme for Swagger UI
    api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

    app = FastAPI(
        title="LongClaw",
        description="Multi-Agent Task Server",
        version="0.1.0",
        lifespan=lifespan,
        swagger_ui_parameters={
            "persistAuthorization": True,
        },
    )

    # Auth middleware
    app.add_middleware(AuthMiddleware)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, specify allowed origins
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routes
    app.include_router(api_router)

    # WebSocket router directly at /ws (not under /api prefix)
    app.include_router(websocket_router, tags=["websocket"])

    # Health check endpoint
    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint.

        Returns:
            Health status.
        """
        return {"status": "healthy"}

    # Verify API key endpoint (requires authentication)
    @app.get("/api/verify")
    async def verify_api_key() -> dict[str, str]:
        """Verify API key endpoint.

        Returns:
            Success message if authenticated.
        """
        return {"status": "authenticated"}

    # Root endpoint
    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint.

        Returns:
            Welcome message.
        """
        return {
            "name": "LongClaw",
            "version": "0.1.0",
            "description": "Multi-Agent Task Server",
        }

    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
