import logging
from datetime import UTC, datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends

from ..cache.abc import CacheBackend
from ..dependencies import (
    get_cache_backend,
    get_db_pool,
    get_pg_manager,
    get_watchdog_service,
    get_websocket_manager,
)
from ..models import ScraperHealth, ScraperStatus
from ..services.notifications import PostgresNotificationManager
from ..services.watchdog import WatchdogService
from ..services.websocket import WebSocketManager

logger = logging.getLogger("windburglr.health")

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check(
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    ws_manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
    pg_manager: Annotated[PostgresNotificationManager, Depends(get_pg_manager)],
    cache_backend: Annotated[CacheBackend, Depends(get_cache_backend)],
):
    """Health check endpoint for monitoring and load balancers."""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "database": "unknown",
        "websocket": "unknown",
        "postgresql_listener": "unknown",
        "connection_monitor": {},
    }

    async with pool.acquire() as conn:
        # Check database connection - connection is already tested by dependency
        try:
            result = await conn.fetchval("SELECT 1")
            health_status["database"] = "connected" if result == 1 else "failed"
        except Exception as e:
            health_status["database"] = f"error: {str(e)}"
            logger.error("Database health check failed: %s", e)

        # Check WebSocket manager
        health_status["websocket"] = (
            "active" if ws_manager.active_connections else "no_connections"
        )

        # Check PostgreSQL listener
        health_status["postgresql_listener"] = (
            "healthy" if pg_manager.is_pg_listener_healthy else "unhealthy"
        )

        # Check connection monitor
        if pg_manager.monitor_task:
            health_status["connection_monitor"] = {
                "done": pg_manager.monitor_task.done(),
                "cancelled": pg_manager.monitor_task.cancelled(),
            }
        else:
            health_status["connection_monitor"] = "no_task"

        # Add cache statistics
        cache_stats = await cache_backend.get_cache_stats()
        health_status["cache"] = cache_stats

        # Add scraper health status
        try:
            scraper_health = await conn.fetchrow(
                """
                SELECT
                    total_stations,
                    healthy_stations,
                    error_stations,
                    stale_stations,
                    overall_status
                FROM get_scraper_health()
                """
            )
            health_status["scraper"] = scraper_health or {}
        except Exception as e:
            health_status["scraper"] = {
                "error": f"Failed to get scraper health: {str(e)}",
                "overall_status": "unknown",
            }

    # Determine overall status
    scraper_status = health_status.get("scraper", {}).get("overall_status", "unknown")
    if (
        health_status["database"] == "connected"
        and pg_manager.is_pg_listener_healthy
        and scraper_status in ["healthy", "warning"]
    ):
        health_status["status"] = "healthy"
    else:
        health_status["status"] = "unhealthy"

    return health_status


@router.get("/scraper-details")
async def get_scraper_status(
    watchdog_service: Annotated[WatchdogService, Depends(get_watchdog_service)],
) -> list[ScraperStatus]:
    """Get detailed scraper status for all stations from watchdog service."""
    return watchdog_service.get_scraper_status()


@router.get("/scraper")
async def get_scraper_health(
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
) -> ScraperHealth:
    """Get overall scraper health status."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                total_stations,
                healthy_stations,
                error_stations,
                stale_stations,
                overall_status
            FROM get_scraper_health()
            """
        )

    return ScraperHealth(**row)
