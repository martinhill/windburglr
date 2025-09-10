import asyncio
import json
import logging
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError

from ..dependencies import get_db_connection, get_websocket_manager, get_wind_service
from ..services.websocket import WebSocketManager
from ..services.wind_data import WindDataService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{station}")
async def websocket_endpoint(
    websocket: WebSocket,
    station: str,
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
    ws_manager: Annotated[WebSocketManager, Depends(get_websocket_manager)],
    wind_service: Annotated[WindDataService, Depends(get_wind_service)],
):
    """WebSocket endpoint for real-time wind data updates."""
    await ws_manager.connect(websocket, station)
    try:
        # Send initial data
        initial_data = await wind_service.get_latest_wind_data(station, conn)
        if initial_data:
            await websocket.send_text(json.dumps(initial_data))

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
        logger.warning("WebSocket connection unexpectedly closed for station %s: %s", station, e)
    finally:
        ws_manager.disconnect(websocket, station)
