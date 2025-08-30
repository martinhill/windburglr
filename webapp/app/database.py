import logging

import asyncpg

from .config import get_database_url

logger = logging.getLogger("windburglr.database")


async def create_db_pool() -> asyncpg.Pool:
    """Create database connection pool during startup."""
    database_url = get_database_url(True)
    if database_url:
        logger.info("Creating PostgreSQL connection pool: %s...", database_url[:50])
        pool = await asyncpg.create_pool(
            database_url, min_size=2, max_size=10, command_timeout=60
        )
        logger.info("PostgreSQL connection pool created successfully")
        return pool
    else:
        logger.warning("No database URL provided")
