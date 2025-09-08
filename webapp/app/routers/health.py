from datetime import UTC, datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from ..cache.abc import CacheBackend
from ..dependencies import (
    get_cache_backend,
    get_db_pool,
    get_pg_manager,
    get_websocket_manager,
)
from ..services.notifications import PostgresNotificationManager
from ..services.websocket import WebSocketManager

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

    # Check database connection
    if pool:
        try:
            async with pool.acquire() as conn:
                result = await conn.fetchval("SELECT 1")
                health_status["database"] = "connected" if result == 1 else "failed"
        except Exception as e:
            health_status["database"] = f"error: {str(e)}"
    else:
        health_status["database"] = "not_configured"

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

    # Determine overall status
    if health_status["database"] == "connected" and pg_manager.is_pg_listener_healthy:
        health_status["status"] = "healthy"
    else:
        health_status["status"] = "unhealthy"

    return health_status


@router.get("/stack", response_class=PlainTextResponse)
async def get_health_stack(
    pg_manager: Annotated[PostgresNotificationManager, Depends(get_pg_manager)],
):
    """Returns the stack of the monitoring task."""
    if pg_manager.monitor_task:
        return "\n".join(str(s) for s in pg_manager.monitor_task.get_stack())
    return "no_task"
