"""
Database migration script for LongClaw.
Adds error_message column to agents table.
"""
import asyncio
import logging

from sqlalchemy import text

from backend.config import get_settings
from backend.database import DatabaseManager

logger = logging.getLogger(__name__)


async def migrate():
    """Run database migrations."""
    settings = get_settings()
    db = DatabaseManager()

    await db.init()

    try:
        async with db.engine.begin() as conn:
            # Check if error_message column exists
            result = await conn.execute(
                text("SHOW COLUMNS FROM agents LIKE 'error_message'")
            )
            exists = result.fetchone()

            if not exists:
                logger.info("Adding error_message column to agents table...")
                await conn.execute(
                    text("ALTER TABLE agents ADD COLUMN error_message TEXT NULL")
                )
                logger.info("Successfully added error_message column")
            else:
                logger.info("error_message column already exists")

            # Create model_configs table if not exists
            result = await conn.execute(
                text("SHOW TABLES LIKE 'model_configs'")
            )
            table_exists = result.fetchone()

            if not table_exists:
                logger.info("Creating model_configs table...")
                await conn.execute(
                    text("""
                        CREATE TABLE model_configs (
                            id VARCHAR(36) PRIMARY KEY,
                            config_type VARCHAR(50) NOT NULL,
                            default_provider VARCHAR(100) NOT NULL DEFAULT 'openai',
                            providers JSON NOT NULL,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                            INDEX idx_config_type (config_type)
                        )
                    """)
                )
                logger.info("Successfully created model_configs table")
            else:
                logger.info("model_configs table already exists")

        logger.info("Migration completed successfully")

    finally:
        await db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(migrate())
