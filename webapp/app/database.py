import logging

import asyncpg

from .config import describe_database_url, get_database_url

logger = logging.getLogger("windburglr.database")

# Seconds to wait for a new connection before giving up
CONNECT_TIMEOUT = 10


async def create_db_pool() -> asyncpg.Pool:
    """Create the query connection pool; raise if no database is configured."""
    database_url = get_database_url(True)
    if not database_url:
        raise RuntimeError(
            "No database configured: set DATABASE_URL (and optionally DATABASE_POOL_URL)"
        )
    logger.info(
        "Creating PostgreSQL connection pool: %s",
        describe_database_url(database_url),
    )
    pool = await asyncpg.create_pool(
        database_url,
        min_size=2,
        max_size=10,
        command_timeout=60,
        timeout=CONNECT_TIMEOUT,
    )
    logger.info("PostgreSQL connection pool created successfully")
    return pool


async def connect_listener() -> asyncpg.Connection:
    """Open a dedicated connection for LISTEN/NOTIFY.

    It bypasses DATABASE_POOL_URL, since a transaction-mode pooler can't hold LISTEN.
    """
    database_url = get_database_url(False)
    if not database_url:
        raise RuntimeError("No database configured: set DATABASE_URL")
    logger.info(
        "Connecting to Postgres for notifications: %s",
        describe_database_url(database_url),
    )
    return await asyncpg.connect(database_url, timeout=CONNECT_TIMEOUT)
