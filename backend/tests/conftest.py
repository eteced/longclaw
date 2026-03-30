"""Pytest configuration for LongClaw tests."""
import asyncio
import os
import sys

import pytest
import pytest_asyncio

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for each test case."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create database session for testing, with cleanup before and after.

    Uses the real database (MariaDB/MySQL) configured in .env.
    Clears all tables before and after each test.
    """
    from sqlalchemy import text
    from backend.database import db_manager

    # Initialize database connection
    await db_manager.init()

    # Tables to clear (in order of foreign key dependencies)
    tables_to_clear = [
        "messages",
        "subtasks",
        "tasks",
        "conversations",
        "knowledge",
        "agent_prompts",
        "agent_settings",
        "agents",
        "channels",
        "config_profiles",
        "system_config",
        "schema_migrations",
    ]

    # Clear tables before test
    async with db_manager._engine.connect() as conn:
        for table in tables_to_clear:
            try:
                await conn.execute(text(f"TRUNCATE TABLE {table}"))
            except Exception:
                pass  # Table might not exist
        await conn.commit()

    # Create tables if they don't exist
    await db_manager.create_tables()

    # Run migrations
    migrations_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")
    if os.path.exists(migrations_dir):
        migration_files = sorted([f for f in os.listdir(migrations_dir) if f.endswith('.sql')])

        async with db_manager._engine.connect() as conn:
            # Ensure migrations table exists
            await conn.execute(text("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL UNIQUE,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            await conn.commit()

            for migration_file in migration_files:
                migration_path = os.path.join(migrations_dir, migration_file)
                with open(migration_path, 'r') as f:
                    migration_sql = f.read()

                # Check if already applied
                result = await conn.execute(
                    text(f"SELECT name FROM schema_migrations WHERE name = '{migration_file}'")
                )
                if result.fetchone():
                    continue

                # Execute migration
                for statement in migration_sql.split(';'):
                    statement = statement.strip()
                    if statement and not statement.startswith('--'):
                        lines = [l for l in statement.split('\n') if not l.strip().startswith('--')]
                        clean_statement = '\n'.join(lines).strip()
                        if clean_statement:
                            clean_statement = clean_statement.replace('ADD COLUMN IF NOT EXISTS', 'ADD COLUMN')
                            try:
                                await conn.execute(text(clean_statement))
                            except Exception as e:
                                if "1060" not in str(e) and "Duplicate column" not in str(e):
                                    raise

                await conn.execute(
                    text(f"INSERT INTO schema_migrations (name) VALUES ('{migration_file}')")
                )
                await conn.commit()

    # Yield session for test
    async with db_manager.session() as session:
        yield session

    # Clear tables after test
    async with db_manager._engine.connect() as conn:
        for table in tables_to_clear:
            try:
                await conn.execute(text(f"TRUNCATE TABLE {table}"))
            except Exception:
                pass
        await conn.commit()

    # Close connection
    await db_manager.close()
