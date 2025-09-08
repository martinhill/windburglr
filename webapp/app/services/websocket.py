import logging

from fastapi import WebSocket

logger = logging.getLogger("windburglr.websocket")


class WebSocketManager:
    """Manages WebSocket connections for real-time wind data updates."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, station: str):
        """Accept a new WebSocket connection for a station."""
        await websocket.accept()
        if station not in self.active_connections:
            self.active_connections[station] = []
        self.active_connections[station].append(websocket)
        logger.info(
            "WebSocket connected for station %s. Total connections: %s",
            station,
            len(self.active_connections[station]),
        )

    def disconnect(self, websocket: WebSocket, station: str):
        """Disconnect a WebSocket connection."""
        if station in self.active_connections:
            try:
                self.active_connections[station].remove(websocket)
                if not self.active_connections[station]:
                    del self.active_connections[station]
                    logger.info("All connections for station %s disconnected", station)
                else:
                    logger.info(
                        "WebSocket disconnected for station %s. Remaining connections: %s",
                        station,
                        len(self.active_connections[station]),
                    )
            except ValueError:
                logger.warning(
                    "Failed to remove WebSocket connection for station %s", station
                )

    async def broadcast_to_station(self, message: str, station: str):
        """Broadcast a message to all connections for a specific station."""
        if station in self.active_connections:
            logger.debug(
                "Broadcasting to %s connections for station %s",
                len(self.active_connections[station]),
                station,
            )
            disconnected: list[WebSocket] = []
            for connection in self.active_connections[station]:
                try:
                    await connection.send_text(message)
                    logger.debug(
                        "Successfully sent message %s to connection for station %s",
                        message,
                        station,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to send message to connection for station %s: %s",
                        station,
                        e,
                    )
                    disconnected.append(connection)

            for conn in disconnected:
                self.disconnect(conn, station)
        else:
            logger.debug("No active connections for station %s", station)
