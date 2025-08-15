import asyncio
import json
import logging
import os
import zoneinfo
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import asyncpg
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Configure logging
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
log_level_value = getattr(logging, log_level, logging.INFO)

# Configure root logger
logging.basicConfig(
    level=log_level_value,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
    force=True,  # Force reconfiguration even if already configured
)

# Create and configure our application logger
logger = logging.getLogger("windburglr")
logger.setLevel(log_level_value)

# Test that debug logging is working
logger.debug(f"Logger configured with level: {log_level} ({log_level_value})")
logger.info(f"WindBurglr logger initialized at level: {log_level}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.debug("DEBUG: Starting WindBurglr application lifespan")
    logger.info("Starting WindBurglr application")
    await manager.start_pg_listener()
    logger.debug("DEBUG: Application startup complete")
    logger.info("Application startup complete")
    yield
    # Shutdown
    logger.debug("DEBUG: Shutting down WindBurglr application")
    logger.info("Shutting down WindBurglr application")
    await manager.stop_pg_listener()
    logger.info("Application shutdown complete")


app = FastAPI(title="WindBurglr", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DEFAULT_STATION = "CYTZ"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"
EPOCH = datetime.fromtimestamp(0, tz=UTC)

GTAG_ID = os.environ.get("GOOGLE_TAG_MANAGER_ID", "")


async def get_station_timezone(station_name: str) -> str:
    """Get the timezone for a given station"""
    pool = get_db_pool()
    if not pool:
        return "UTC"

    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT get_station_timezone_name($1)", station_name
        )
        return result or "UTC"


class WindObservation(BaseModel):
    station: str
    direction: float | None
    speed_kts: float | None
    gust_kts: float | None
    update_time: datetime


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.pg_listener: asyncpg.Connection | None = None
        self.notification_count = 0
        self.db_pool: asyncpg.Pool | None = None
        self.monitor_task: asyncio.Task | None = None
        self.is_pg_listener_healthy = False

    async def connect(self, websocket: WebSocket, station: str):
        await websocket.accept()
        if station not in self.active_connections:
            self.active_connections[station] = []
        self.active_connections[station].append(websocket)
        logger.info(
            f"WebSocket connected for station {station}. Total connections: {len(self.active_connections[station])}"
        )

    def disconnect(self, websocket: WebSocket, station: str):
        if station in self.active_connections:
            try:
                self.active_connections[station].remove(websocket)
                if not self.active_connections[station]:
                    del self.active_connections[station]
                    logger.info(f"All connections for station {station} disconnected")
                else:
                    logger.info(
                        f"WebSocket disconnected for station {station}. Remaining connections: {len(self.active_connections[station])}"
                    )
            except ValueError:
                logger.warning(
                    f"Failed to remove WebSocket connection for station {station}"
                )

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast_to_station(self, message: str, station: str):
        if station in self.active_connections:
            logger.debug(
                f"Broadcasting to {len(self.active_connections[station])} connections for station {station}"
            )
            disconnected = []
            for connection in self.active_connections[station]:
                try:
                    await connection.send_text(message)
                    logger.debug(
                        f"Successfully sent message {message} to connection for station {station}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to send message to connection for station {station}: {e}"
                    )
                    disconnected.append(connection)

            for conn in disconnected:
                self.disconnect(conn, station)
        else:
            logger.debug(f"No active connections for station {station}")

    async def broadcast(self, message: str):
        for station in list(self.active_connections.keys()):
            await self.broadcast_to_station(message, station)

    async def start_pg_listener(self):
        database_url = get_database_url()
        if not database_url:
            logger.warning("No database URL configured, skipping PostgreSQL listener")
            return

        try:
            # Create connection pool
            logger.info(f"Creating PostgreSQL connection pool: {database_url[:50]}...")
            self.db_pool = await asyncpg.create_pool(
                database_url, min_size=2, max_size=10, command_timeout=60
            )

            # Create separate connection for notifications
            logger.info(
                f"Connecting to PostgreSQL for notifications: {database_url[:50]}..."
            )
            self.pg_listener = await asyncpg.connect(database_url)

            # Test the connection
            result = await self.pg_listener.fetchval("SELECT 1")
            logger.debug(f"PostgreSQL connection test result: {result}")

            await self.pg_listener.add_listener(
                "wind_obs_insert", self._handle_notification
            )
            logger.info("PostgreSQL listener started successfully")
            logger.info("Listening for channels: wind_obs_insert")

            # Mark connection as healthy
            self.is_pg_listener_healthy = True

            # Start background monitoring task
            self.monitor_task = asyncio.create_task(self._monitor_pg_connection())
            logger.info("PostgreSQL connection monitoring started")

        except Exception as e:
            logger.error(f"Failed to start PostgreSQL listener: {e}", exc_info=True)
            self.is_pg_listener_healthy = False

    async def stop_pg_listener(self):
        # Cancel monitoring task
        if (
            hasattr(self, "monitor_task")
            and self.monitor_task
            and not self.monitor_task.done()
        ):
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                logger.info("PostgreSQL connection monitor task cancelled")
            except Exception as e:
                logger.error(f"Error cancelling monitor task: {e}")

        if self.pg_listener:
            try:
                await self.pg_listener.close()
                logger.info("PostgreSQL listener stopped")
            except Exception as e:
                logger.error(f"Error stopping PostgreSQL listener: {e}", exc_info=True)

        if self.db_pool:
            try:
                await self.db_pool.close()
                logger.info("PostgreSQL connection pool closed")
            except Exception as e:
                logger.error(f"Error closing PostgreSQL pool: {e}", exc_info=True)

        self.is_pg_listener_healthy = False

    async def _check_pg_connection_health(self) -> bool:
        """Check if PostgreSQL listener connection is healthy"""
        if not self.pg_listener or self.pg_listener.is_closed():
            self.is_pg_listener_healthy = False
            return False

        try:
            # Simple health check query
            await self.pg_listener.fetchval("SELECT 1")
            self.is_pg_listener_healthy = True
            return True
        except Exception as e:
            logger.error(f"PostgreSQL connection health check failed: {e}")
            self.is_pg_listener_healthy = False
            return False

    async def _reconnect_pg_listener(self) -> bool:
        """Attempt to reconnect PostgreSQL listener with exponential backoff"""
        max_retries = 5
        base_delay = 1  # Start with 1 second

        for attempt in range(max_retries):
            try:
                logger.info(
                    f"Attempting PostgreSQL listener reconnection (attempt {attempt + 1}/{max_retries})"
                )

                # Clean up existing connection
                if self.pg_listener and not self.pg_listener.is_closed():
                    await self.pg_listener.close()

                # Re-establish connection
                database_url = get_database_url()
                if not database_url:
                    logger.error("No database URL available for reconnection")
                    return False

                self.pg_listener = await asyncpg.connect(database_url)
                await self.pg_listener.add_listener(
                    "wind_obs_insert", self._handle_notification
                )

                logger.info("PostgreSQL listener reconnected successfully")
                self.is_pg_listener_healthy = True
                return True

            except Exception as e:
                delay = base_delay * (2**attempt)  # Exponential backoff
                logger.error(f"Reconnection attempt {attempt + 1} failed: {e}")

                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)

        logger.error("Failed to reconnect PostgreSQL listener after all attempts")
        self.is_pg_listener_healthy = False
        return False

    async def _monitor_pg_connection(self):
        """Background task to monitor PostgreSQL connection health"""
        while True:
            try:
                if not await self._check_pg_connection_health():
                    logger.warning(
                        "PostgreSQL listener connection lost, attempting reconnection..."
                    )
                    await self._reconnect_pg_listener()

                # Check every 30 seconds
                await asyncio.sleep(30)
                logger.debug("PostgreSQL connection monitor running")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in PostgreSQL connection monitor: {e}")
                await asyncio.sleep(5)  # Shorter wait on error

    async def _handle_notification(self, connection, pid, channel, payload):
        try:
            self.notification_count += 1
            logger.info(
                f"🔔 Received notification #{self.notification_count} on channel '{channel}' from PID {pid}"
            )
            logger.debug(f"Raw payload: {payload}")

            data = json.loads(payload)
            logger.debug(f"Parsed notification data: {data}")

            station_name = data.get("station_name")
            logger.debug(f"Station name from notification: {station_name}")

            if station_name:
                # Apply the same safe_int conversion as used elsewhere
                wind_data = {
                    "timestamp": data.get("update_time"),
                    "direction": safe_int(data.get("direction")),
                    "speed_kts": safe_int(data.get("speed_kts")),
                    "gust_kts": safe_int(data.get("gust_kts")),
                }
                logger.info(
                    f"📡 Broadcasting wind data to station {station_name}: {wind_data}"
                )
                logger.debug(
                    f"Active connections for {station_name}: {len(self.active_connections.get(station_name, []))}"
                )

                await self.broadcast_to_station(json.dumps(wind_data), station_name)
            else:
                logger.warning("No station name found in notification data")
        except Exception as e:
            logger.error(f"Error handling notification: {e}", exc_info=True)


manager = ConnectionManager()


def get_database_url():
    return os.environ.get("DATABASE_URL", "")


def get_db_pool():
    return manager.db_pool


def epoch_time(dt):
    # Ensure both datetimes are timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    # Convert to UTC if not already
    if dt.tzinfo != UTC:
        dt = dt.astimezone(UTC)
    delta = dt - EPOCH
    return delta.total_seconds()


def safe_int(d):
    try:
        return int(d) if d is not None else None
    except (TypeError, ValueError):
        return None


async def query_wind_data(station: str, start_time: datetime, end_time: datetime):
    pool = get_db_pool()
    if not pool:
        return []

    # Convert timezone-aware datetimes to timezone-naive UTC for asyncpg
    # (PostgreSQL timestamp columns are typically timezone-naive)
    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(UTC).replace(tzinfo=None)
    if end_time.tzinfo is not None:
        end_time = end_time.astimezone(UTC).replace(tzinfo=None)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM get_wind_data_by_station_range($1, $2, $3)",
            station,
            start_time,
            end_time,
        )

        results = [
            (
                epoch_time(row["update_time"]),
                safe_int(row["direction"]),
                safe_int(row["speed_kts"]),
                safe_int(row["gust_kts"]),
            )
            for row in rows
        ]

        return results


async def get_latest_wind_data(station: str = DEFAULT_STATION):
    pool = get_db_pool()
    if not pool:
        return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM get_latest_wind_observation($1)", station
        )
        if row:
            # Ensure update_time is timezone-aware before processing
            update_time = row["update_time"]
            if update_time.tzinfo is None:
                update_time = update_time.replace(tzinfo=UTC)

            return {
                "timestamp": epoch_time(update_time),
                "direction": safe_int(row["direction"]),
                "speed_kts": safe_int(row["speed_kts"]),
                "gust_kts": safe_int(row["gust_kts"]),
            }
        return None


@app.get("/", response_class=HTMLResponse)
async def live_wind_chart(
    request: Request, stn: str = DEFAULT_STATION, hours: int = 3, minutes: int = 0
):
    return templates.TemplateResponse(
        "index.html",
        {
            "gtag_id": GTAG_ID,
            "request": request,
            "station": stn,
            "hours": hours,
            "minutes": minutes,
            "is_live": True,
        },
    )


@app.get("/day")
async def redirect_to_today(stn: str = DEFAULT_STATION, hours: int = 24):
    """Redirect to current date when no date is specified"""
    today = datetime.now().strftime("%Y-%m-%d")
    return RedirectResponse(
        url=f"/day/{today}?stn={stn}&hours={hours}", status_code=302
    )


@app.get("/day/{date}", response_class=HTMLResponse)
async def historical_wind_day_chart(
    request: Request, date: str, stn: str = DEFAULT_STATION, hours: int = 24
):
    try:
        # Parse ISO date (YYYY-MM-DD) - simple validation
        selected_date = datetime.strptime(date, "%Y-%m-%d")

        # Calculate previous and next dates
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)

        # Get station timezone to convert local day boundaries to UTC
        station_tz_name = await get_station_timezone(stn)
        station_tz = zoneinfo.ZoneInfo(station_tz_name)

        # Create day boundaries in station timezone, then convert to UTC
        day_start_local = selected_date.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=station_tz
        )
        day_end_local = day_start_local + timedelta(days=1)

        day_start_utc = day_start_local.astimezone(UTC)
        day_end_utc = day_end_local.astimezone(UTC)

        return templates.TemplateResponse(
            "index.html",
            {
                "gtag_id": GTAG_ID,
                "request": request,
                "station": stn,
                "hours": hours,
                "minutes": 0,
                "is_live": False,
                "selected_date": selected_date.strftime("%Y-%m-%d"),
                "selected_date_obj": selected_date,
                "prev_date": prev_date.strftime("%Y-%m-%d"),
                "next_date": next_date.strftime("%Y-%m-%d"),
                "date_start": day_start_utc.strftime("%Y-%m-%dT%H:%M:%S"),
                "date_end": day_end_utc.strftime("%Y-%m-%dT%H:%M:%S"),
                "station_timezone": station_tz_name,
            },
        )
    except ValueError as err:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD"
        ) from err


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "database": "unknown",
        "websocket": "unknown",
        "postgresql_listener": "unknown",
    }

    # Check database connection
    pool = get_db_pool()
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
        "active" if manager.active_connections else "no_connections"
    )

    # Check PostgreSQL listener
    health_status["postgresql_listener"] = (
        "healthy" if manager.is_pg_listener_healthy else "unhealthy"
    )

    # Determine overall status
    if health_status["database"] == "connected" and manager.is_pg_listener_healthy:
        health_status["status"] = "healthy"
    else:
        health_status["status"] = "unhealthy"

    return health_status


@app.get("/api/wind")
async def get_wind_data(
    stn: str = DEFAULT_STATION,
    from_time: str | None = None,
    to_time: str | None = None,
    hours: int | None = None,
):
    # Get station timezone for metadata only
    station_tz_name = await get_station_timezone(stn)

    if from_time and to_time:
        # Parse datetime strings as UTC (no timezone conversion)
        start_time = datetime.strptime(from_time, ISO_FORMAT).replace(tzinfo=UTC)
        end_time = datetime.strptime(to_time, ISO_FORMAT).replace(tzinfo=UTC)

    elif hours:
        # For relative time queries, use current UTC time
        now_utc = datetime.now(UTC)
        start_time = now_utc - timedelta(hours=hours)
        end_time = now_utc
    else:
        # Default: last 24 hours in UTC
        now_utc = datetime.now(UTC)
        start_time = now_utc - timedelta(hours=24)
        end_time = now_utc

    winddata = await query_wind_data(stn, start_time, end_time)
    return {
        "station": stn,
        "winddata": winddata,
        "timezone": station_tz_name,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "database": "unknown",
        "websocket": "unknown",
        "postgresql_listener": "unknown",
    }

    # Check database connection
    pool = get_db_pool()
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
        "active" if manager.active_connections else "no_connections"
    )

    # Check PostgreSQL listener
    health_status["postgresql_listener"] = (
        "healthy" if manager.is_pg_listener_healthy else "unhealthy"
    )

    # Determine overall status
    if health_status["database"] == "connected" and manager.is_pg_listener_healthy:
        health_status["status"] = "healthy"
    else:
        health_status["status"] = "unhealthy"

    return health_status


@app.post("/api/wind")
async def create_wind_observation(observation: WindObservation):
    logger.info(f"Received wind observation: {observation}")
    pool = get_db_pool()
    if not pool:
        logger.error("Database connection failed")
        raise HTTPException(status_code=500, detail="Database connection failed")

    # No authorization yet, so do not allow for any request
    raise HTTPException(status_code=500, detail="Not implemented")

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                logger.debug(
                    f"Starting database transaction for observation: {observation}"
                )

                # Get station by name
                logger.debug(f"Looking for station: {observation.station}")
                station = await conn.fetchrow(
                    "SELECT * FROM get_station_id_by_name($1)", observation.station
                )

                if not station:
                    logger.warning(f"Station {observation.station} not found")
                    # List available stations for debugging
                    all_stations = await conn.fetch("SELECT * FROM get_all_stations()")
                    available_stations = [s["name"] for s in all_stations]
                    logger.warning(f"Available stations: {available_stations}")
                    raise HTTPException(
                        status_code=404,
                        detail=f"Station {observation.station} not found",
                    )

                logger.info(f"Found station: {station['name']} (ID: {station['id']})")

                # Create wind observation
                # Convert timezone-aware datetime to timezone-naive UTC for asyncpg
                update_time = observation.update_time
                if update_time.tzinfo is not None:
                    update_time = update_time.astimezone(UTC).replace(tzinfo=None)

                await conn.execute(
                    """
                    INSERT INTO wind_obs (station_id, direction, speed_kts, gust_kts, update_time)
                    VALUES ($1, $2, $3, $4, $5)
                """,
                    station["id"],
                    observation.direction,
                    observation.speed_kts,
                    observation.gust_kts,
                    update_time,
                )

                logger.info(
                    f"✅ Wind observation committed to database for station {observation.station} - trigger should have fired!"
                )

                # The database trigger will automatically send notifications
                # No need to manually broadcast here

                return observation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating wind observation: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring and load balancers"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(UTC).isoformat(),
        "database": "unknown",
        "websocket": "unknown",
        "postgresql_listener": "unknown",
    }

    # Check database connection
    pool = get_db_pool()
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
        "active" if manager.active_connections else "no_connections"
    )

    # Check PostgreSQL listener
    health_status["postgresql_listener"] = (
        "healthy" if manager.is_pg_listener_healthy else "unhealthy"
    )

    # Determine overall status
    if health_status["database"] == "connected" and manager.is_pg_listener_healthy:
        health_status["status"] = "healthy"
    else:
        health_status["status"] = "unhealthy"

    return health_status


@app.websocket("/ws/{station}")
async def websocket_endpoint(websocket: WebSocket, station: str):
    await manager.connect(websocket, station)
    try:
        # Send initial data
        initial_data = await get_latest_wind_data(station)
        if initial_data:
            await websocket.send_text(json.dumps(initial_data))

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message from client (ping/pong)
                await asyncio.wait_for(websocket.receive_text(), timeout=60.0)
            except TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_text(json.dumps({"type": "ping"}))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, station)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))

    # Configure uvicorn logging to respect our configuration
    uvicorn_log_level = log_level.lower()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=uvicorn_log_level,
        log_config=None,  # Don't use uvicorn's default log config
    )
