import asyncio
import json
import logging
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from ..dependencies import (
    get_db_pool,
    get_watchdog_service,
    get_websocket_manager,
    get_wind_service,
)
from ..services.watchdog import WatchdogService
from ..services.websocket import WebSocketManager
from ..services.wind_data import WindDataService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{station}")
async def websocket_endpoint(
    websocket: WebSocket,
    station: str,
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    ws_manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
    wind_service: Annotated[WindDataService, Depends(get_wind_service)],
    watchdog_service: Annotated[WatchdogService, Depends(get_watchdog_service)],
):
    """WebSocket endpoint for real-time wind data updates."""
    await ws_manager.connect(websocket, station)
    try:
        # Send initial status update for this specific connection
        station_status = watchdog_service.get_station_status_by_name(station)
        if station_status:
            status_message = json.dumps(
                {
                    "type": "status_update",
                    "data": station_status.model_dump(mode="json"),
                }
            )
            await websocket.send_text(status_message)

        # Send initial wind data
        initial_data = await wind_service.get_latest_wind_data(station, pool)
        if initial_data:
            await websocket.send_text(
                json.dumps({"type": "wind", "data": initial_data})
            )

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message from client (ping/pong)
                await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
                await websocket.send_text(json.dumps({"type": "pong"}))
            except TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_text(json.dumps({"type": "ping"}))
            except WebSocketDisconnect:
                break
    except (WebSocketDisconnect, ConnectionClosedError) as e:
        logger.warning(
            "WebSocket connection unexpectedly closed for station %s: %s", station, e
        )
    finally:
        ws_manager.disconnect(websocket, station)
