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
from backend.models.agent import AgentType
from backend.models.channel import ChannelType
from backend.services.agent_registry import agent_registry
from backend.services.agent_service import agent_service
from backend.services.channel_service import channel_service
from backend.services.config_service import config_service
from backend.services.llm_service import llm_service
from backend.services.message_service import message_service
from backend.services.scheduler_service import scheduler_service
from backend.services.tool_service import tool_service

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if get_settings().debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances
resident_agent: ResidentAgent | None = None
web_channel: WebChannel | None = None


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

    # Initialize message service (Redis)
    await message_service.init()
    logger.info("Message service initialized")

    # Start scheduler
    await scheduler_service.start()
    logger.info("Scheduler started")

    # Initialize resident agent and web channel
    await _init_resident_agent_and_web_channel()

    logger.info("LongClaw server started")

    yield

    # Cleanup
    logger.info("Shutting down LongClaw server...")

    # Stop resident agent
    if resident_agent:
        await resident_agent.terminate()
        agent_registry.unregister_agent(resident_agent.id)
        logger.info("Resident agent terminated")

    # Stop web channel
    if web_channel:
        await web_channel.stop()
        logger.info("Web channel stopped")

    await scheduler_service.stop()
    logger.info("Scheduler stopped")

    await message_service.close()
    logger.info("Message service closed")

    await tool_service.close()
    logger.info("Tool service closed")

    await llm_service.close()
    logger.info("LLM service closed")

    await db_manager.close()
    logger.info("Database closed")

    logger.info("LongClaw server stopped")


async def _init_resident_agent_and_web_channel() -> None:
    """Initialize resident agent and web channel."""
    global resident_agent, web_channel

    async with db_manager.session() as session:
        # Check for existing resident agent
        agents = await agent_service.get_agents(
            session,
            agent_type=AgentType.RESIDENT,
            limit=1,
        )

        if agents:
            # Load existing agent
            agent_model = agents[0]
            resident_agent = ResidentAgent(agent_id=agent_model.id)
            await resident_agent.load(agent_model.id)
            logger.info(f"Loaded existing resident agent: {resident_agent.id}")
        else:
            # Create new resident agent
            resident_agent = ResidentAgent(name="老六")
            await resident_agent.persist()
            logger.info(f"Created new resident agent: {resident_agent.id}")

        # Check for existing web channel
        channels = await channel_service.get_channels(
            session,
            channel_type=ChannelType.WEB,
            limit=1,
        )

        if channels:
            channel_model = channels[0]
            web_channel = WebChannel(
                channel_id=channel_model.id,
                resident_agent_id=channel_model.resident_agent_id,
                config=channel_model.config,
            )
            logger.info(f"Loaded existing web channel: {web_channel.id}")

            # Bind resident agent if not already bound
            if not channel_model.resident_agent_id:
                await channel_service.bind_resident_agent(
                    session,
                    channel_model.id,
                    resident_agent.id,
                )
                web_channel._resident_agent_id = resident_agent.id
                logger.info(f"Bound resident agent {resident_agent.id} to web channel")
        else:
            # Create new web channel
            channel_model = await channel_service.create_channel(
                session,
                channel_type=ChannelType.WEB,
                resident_agent_id=resident_agent.id,
            )
            web_channel = WebChannel(
                channel_id=channel_model.id,
                resident_agent_id=resident_agent.id,
            )
            logger.info(f"Created new web channel: {web_channel.id}")

    # Register agent and start
    agent_registry.register_agent(resident_agent)
    await resident_agent.start()
    logger.info("Resident agent started and registered")

    # Start web channel
    await web_channel.start()
    logger.info("Web channel started")


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
