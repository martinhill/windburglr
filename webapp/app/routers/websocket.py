import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from ..dependencies import get_db_pool, get_websocket_manager, get_wind_service

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{station}")
async def websocket_endpoint(
    websocket: WebSocket,
    station: str,
    pool=Depends(get_db_pool),
    ws_manager=Depends(get_websocket_manager),
    wind_service=Depends(get_wind_service),
):
    """WebSocket endpoint for real-time wind data updates."""
    await ws_manager.connect(websocket, station)
    try:
        # Send initial data
        initial_data = await wind_service.get_latest_wind_data(station, pool)
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
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket, station)
