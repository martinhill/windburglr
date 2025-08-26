import asyncio
import json
import logging
import os
import time
import zoneinfo
from bisect import bisect_left
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional, List, Tuple

import asyncpg
from async_lru import alru_cache
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    APIRouter,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, field_validator

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

app_globals = {}


def make_app(pg_connection: Optional[asyncpg.Connection] = None):
    global router

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Create fresh ConnectionManager instance for this app
        manager = app_globals["manager"] = ConnectionManager()

        # Startup
        logger.info("Starting WindBurglr application")

        # Create database connection pool during startup
        await manager.create_db_pool()

        # Optional: inject a custom connection before starting the listener
        if pg_connection:
            manager.set_pg_listener(pg_connection)

        await manager.start_pg_listener()
        logger.info("Application startup complete")
        yield
        # Shutdown
        logger.info("Shutting down WindBurglr application")
        await manager.stop_pg_listener()
        logger.info("Application shutdown complete")

    app = FastAPI(title="WindBurglr", lifespan=lifespan)
    app.include_router(router)
    app.mount("/static", StaticFiles(directory="static"), name="static")
    return app


templates = Jinja2Templates(directory="templates")

DEFAULT_STATION = "CYTZ"
ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"

GTAG_ID = os.environ.get("GOOGLE_TAG_MANAGER_ID", "")

# Cache configuration
DATA_CACHE_HOURS = int(os.environ.get("DATA_CACHE_HOURS", "48"))
CACHE_DURATION = timedelta(hours=DATA_CACHE_HOURS)


class WindDataPoint(BaseModel):
    timestamp: float
    direction: Optional[int]
    speed_kts: Optional[int]
    gust_kts: Optional[int]

    @field_validator("timestamp", mode="before")
    @classmethod
    def convert_timestamp(cls, ts_value):
        if isinstance(ts_value, datetime):
            # Ensure both datetimes are timezone-aware
            if ts_value.tzinfo is None:
                ts_value = ts_value.replace(tzinfo=timezone.utc)
            # Convert to UTC if not already
            if ts_value.tzinfo != timezone.utc:
                ts_value = ts_value.astimezone(timezone.utc)
            return ts_value.timestamp()
        return ts_value


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.pg_listener: asyncpg.Connection | None = None
        self.notification_count = 0
        self.db_pool: asyncpg.Pool | None = None
        self.monitor_task: asyncio.Task | None = None
        self._is_pg_listener_healthy = False

        # Initialize cache storage for wind data
        self._init_cache()

    def _init_cache(self):
        """Initialize cache attributes"""
        self.wind_data_cache: dict[
            str, list[tuple]
        ] = {}  # station -> list of (timestamp, direction, speed_kts, gust_kts)
        self.cache_oldest_time: dict[
            str, datetime
        ] = {}  # station -> oldest cached timestamp
        self.cache_lock: asyncio.Lock = (
            asyncio.Lock()
        )  # For thread-safe cache operations
        self.cache_hit_count = 0
        self.cache_miss_count = 0

    async def _add_to_cache(self, station: str, data: tuple):
        """Add new observation to cache"""
        async with self.cache_lock:
            if station not in self.wind_data_cache:
                self.wind_data_cache[station] = []
                self.cache_oldest_time[station] = data[0]  # timestamp is first element

            # Add new data point (data is already a tuple: (timestamp, direction, speed_kts, gust_kts))
            self.wind_data_cache[station].append(data)

            # Update oldest time if this is the oldest
            if data[0] < self.cache_oldest_time[station]:
                self.cache_oldest_time[station] = data[0]

            # Prune old data beyond cache duration
            await self._prune_cache(station)

            logger.debug(
                f"Added data to cache for station {station}, cache size: {len(self.wind_data_cache[station])}"
            )

    async def _prune_cache(self, station: str):
        """Remove data older than cache duration"""
        if station not in self.wind_data_cache:
            return

        cutoff_time = datetime.now(timezone.utc) - CACHE_DURATION
        cutoff_timestamp = cutoff_time.timestamp()

        # Find insertion point for cutoff time (data is sorted by timestamp)
        cache_data = self.wind_data_cache[station]
        if not cache_data:
            return

        # Use bisect to find where to trim
        from bisect import bisect_left

        insert_point = bisect_left([item[0] for item in cache_data], cutoff_timestamp)

        if insert_point > 0:
            # Remove old data
            self.wind_data_cache[station] = cache_data[insert_point:]
            if self.wind_data_cache[station]:
                self.cache_oldest_time[station] = self.wind_data_cache[station][0][0]
            else:
                # No data left, remove station from cache
                del self.wind_data_cache[station]
                del self.cache_oldest_time[station]

            logger.debug(
                f"Pruned cache for station {station}, removed {insert_point} old entries"
            )

    async def _is_cache_hit(self, station: str, start_time: datetime) -> bool:
        """Check if cache covers the requested time range"""
        if station not in self.cache_oldest_time or station not in self.wind_data_cache:
            return False

        # Convert times to UTC if needed
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(timezone.utc)
        # if end_time.tzinfo is not None:
        #     end_time = end_time.astimezone(timezone.utc)

        start_ts = start_time.timestamp()
        # end_ts = end_time.timestamp()
        oldest_ts = float(self.cache_oldest_time[station])

        # Quick check: requested range must be within cached range
        if start_ts < oldest_ts:
            logger.debug(
                f"Cache miss: start_time {start_time} is before oldest cached time"
            )
            return False

        cache_data = self.wind_data_cache[station]
        if not cache_data:
            return False

        # Check if there's any overlap between requested range and cached range
        newest_ts = cache_data[-1][0]  # Last item has the newest timestamp

        # Check for overlap: requested range [start_ts, end_ts] overlaps with cached range [oldest_ts, newest_ts]
        # Check request vs cached range
        # Ignore the end_time, since the cache contains the most recent data
        within_bounds = (
            oldest_ts <= start_ts <= newest_ts
        )  # and oldest_ts <= end_ts <= newest_ts

        if not within_bounds:
            logger.debug(
                f"Cache miss: requested range {start_ts}, cached range {oldest_ts} to {newest_ts}"
            )
            return False

        logger.debug(
            f"Cache hit: requested range {start_ts}, cached range {oldest_ts} to {newest_ts}"
        )
        return True

    async def _get_cached_data(
        self, station: str, start_time: datetime, end_time: datetime
    ) -> list[tuple]:
        """Get cached data for the specified time range"""
        if station not in self.wind_data_cache:
            return []

        cache_data = self.wind_data_cache[station]
        if not cache_data:
            return []

        # Convert times to UTC timestamps
        if start_time.tzinfo is not None:
            start_time = start_time.astimezone(timezone.utc)
        if end_time.tzinfo is not None:
            end_time = end_time.astimezone(timezone.utc)

        start_ts = start_time.timestamp()
        end_ts = end_time.timestamp()

        # Find data in range using binary search
        from bisect import bisect_left, bisect_right

        timestamps = [item[0] for item in cache_data]
        start_idx = bisect_left(timestamps, start_ts)
        end_idx = bisect_right(timestamps, end_ts)

        return cache_data[start_idx:end_idx]

    async def _update_cache_with_data(
        self,
        station: str,
        start_time: datetime,
        end_time: datetime,
        wind_data: List[Tuple],
    ):
        """Populate cache with data from database"""
        try:
            # Abort if end_time is before oldest data in cache
            # Adding this data would leave a gap in the cache
            oldest_update_time = self.cache_oldest_time.get(station, 0)
            if end_time.timestamp() < oldest_update_time:
                logger.debug(f"End time {end_time} is before oldest data in cache")
                return

            # Sort new data by timestamp to maintain chronological order
            sorted_new_data = sorted(wind_data, key=lambda x: x[0])  # Sort by timestamp

            async with self.cache_lock:
                if station not in self.wind_data_cache:
                    self.wind_data_cache[station] = []
                    self.cache_oldest_time[station] = (
                        sorted_new_data[0][0] if sorted_new_data else 0
                    )

                # Get existing cache data
                existing_data = self.wind_data_cache[station]

                # Combine existing and new data, then sort and deduplicate
                combined_data = existing_data + sorted_new_data
                if combined_data:
                    # Sort by timestamp
                    combined_data.sort(key=lambda x: x[0])

                    # Remove duplicates based on timestamp (keep the last occurrence for each timestamp)
                    deduplicated_data = []
                    seen_timestamps = set()

                    # Iterate in reverse to keep the most recent data for duplicate timestamps
                    for item in reversed(combined_data):
                        timestamp = item[0]
                        if timestamp not in seen_timestamps:
                            seen_timestamps.add(timestamp)
                            deduplicated_data.append(item)

                    # Reverse back to chronological order
                    deduplicated_data.reverse()

                    # Update cache with deduplicated data
                    self.wind_data_cache[station] = deduplicated_data

                    # Update oldest time based on the earliest timestamp in the cache
                    if deduplicated_data:
                        start_ts = start_time.timestamp()
                        self.cache_oldest_time[station] = min(deduplicated_data[0][0], start_ts)
                    else:
                        # No data left, remove station from cache
                        del self.wind_data_cache[station]
                        del self.cache_oldest_time[station]
                else:
                    # No data at all, ensure station is removed from cache
                    if station in self.wind_data_cache:
                        del self.wind_data_cache[station]
                    if station in self.cache_oldest_time:
                        del self.cache_oldest_time[station]

                # Prune old data after adding new data
                await self._prune_cache(station)

            logger.debug(
                f"Updated cache for station {station} with {len(sorted_new_data)} new entries, cache size: {len(self.wind_data_cache.get(station, []))}"
            )
        except Exception as e:
            logger.error(
                f"Error updating cache from database for station {station}: {e}"
            )

    def set_pg_listener(self, connection: asyncpg.Connection):
        """Inject an asyncpg connection to be used as the pg_listener"""
        self.pg_listener = connection

    async def create_db_pool(self):  # pragma: no cover
        """Create database connection pool during startup"""
        if self.db_pool is None:
            database_url = get_database_url(True)
            if database_url:
                logger.info(
                    f"Creating PostgreSQL connection pool: {database_url[:50]}..."
                )
                self.db_pool = await asyncpg.create_pool(
                    database_url, min_size=2, max_size=10, command_timeout=60
                )
                logger.info("PostgreSQL connection pool created successfully")
            else:
                logger.warning("No database URL provided")
        else:
            logger.warning("Database pool already exists")

    async def get_db_pool(self):  # pragma: no cover
        """Get existing database pool, but create it if it doesn't exist"""
        if self.db_pool is None:
            await self.create_db_pool()
            if self.db_pool is None:
                raise RuntimeError(
                    "Database pool not initialized - ensure lifespan startup completed"
                )
        return self.db_pool

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

    async def start_pg_listener(self):
        # If a connection was already injected, use it directly
        if self.pg_listener:
            logger.info("Using injected PostgreSQL connection for listener")
        else:  # pragma: no cover
            # Create a new connection if none was injected
            database_url = get_database_url(False)
            if not database_url:
                logger.warning(
                    "No database URL configured, skipping PostgreSQL listener"
                )
                return

            try:
                # Create separate connection for notifications
                logger.info(
                    f"Connecting to PostgreSQL for notifications: {database_url[:50]}..."
                )
                self.pg_listener = await asyncpg.connect(database_url)
            except Exception as e:
                logger.error(
                    f"Failed to create PostgreSQL connection: {e}", exc_info=True
                )
                self._is_pg_listener_healthy = False
                return

        try:
            # Test the connection
            if self.pg_listener:
                result = await self.pg_listener.fetchval("SELECT 1")
                logger.debug(f"PostgreSQL connection test result: {result}")

                await self.pg_listener.add_listener(
                    "wind_obs_insert", self._handle_notification
                )
            logger.info("PostgreSQL listener started successfully")
            logger.info("Listening for channels: wind_obs_insert")

            # Mark connection as healthy
            self._is_pg_listener_healthy = True

            # Start background monitoring task
            self.monitor_task = asyncio.create_task(self._monitor_pg_connection())
            logger.info("PostgreSQL connection monitoring started")

        except Exception as e:
            logger.error(f"Failed to start PostgreSQL listener: {e}", exc_info=True)
            self._is_pg_listener_healthy = False

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

        self._is_pg_listener_healthy = False

    async def _check_pg_connection_health(self) -> bool:
        """Check if PostgreSQL listener connection is healthy"""
        if not self.pg_listener or self.pg_listener.is_closed():
            self._is_pg_listener_healthy = False
            return False

        try:
            # Simple health check query
            await self.pg_listener.fetchval("SELECT 1")
            self._is_pg_listener_healthy = True
            return True
        except Exception as e:
            logger.error(f"PostgreSQL connection health check failed: {e}")
            self._is_pg_listener_healthy = False
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
                database_url = get_database_url(False)
                if not database_url:
                    logger.error("No database URL available for reconnection")
                    return False

                self.pg_listener = await asyncpg.connect(database_url)
                if self.pg_listener:
                    await self.pg_listener.add_listener(
                        "wind_obs_insert", self._handle_notification
                    )

                logger.info("PostgreSQL listener reconnected successfully")
                self._is_pg_listener_healthy = True
                return True

            except Exception as e:
                delay = base_delay * (2**attempt)  # Exponential backoff
                logger.error(f"Reconnection attempt {attempt + 1} failed: {e}")

                if attempt < max_retries - 1:
                    await asyncio.sleep(delay)

        logger.error("Failed to reconnect PostgreSQL listener after all attempts")
        self._is_pg_listener_healthy = False
        return False

    @property
    async def is_pg_listener_healthy(self):
        return self._is_pg_listener_healthy and await self._check_pg_connection_health()

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
                # Use Pydantic model for data validation and conversion
                wind_data = WindDataPoint(
                    timestamp=data.get("update_time"),
                    direction=data.get("direction"),
                    speed_kts=data.get("speed_kts"),
                    gust_kts=data.get("gust_kts"),
                ).model_dump()
                logger.info(
                    f"📡 Broadcasting wind data to station {station_name}: {wind_data}"
                )
                logger.debug(
                    f"Active connections for {station_name}: {len(self.active_connections.get(station_name, []))}"
                )

                await self.broadcast_to_station(json.dumps(wind_data), station_name)

                # Add new observation to cache
                data_tuple = (
                    wind_data["timestamp"],
                    wind_data["direction"],
                    wind_data["speed_kts"],
                    wind_data["gust_kts"],
                )
                await self._add_to_cache(station_name, data_tuple)
            else:
                logger.warning("No station name found in notification data")
        except Exception as e:
            logger.error(f"Error handling notification: {e}", exc_info=True)


# manager = ConnectionManager()


def get_database_url(pooled: bool = False) -> str:  # pragma: no cover
    if pooled:
        return os.environ.get("DATABASE_POOL_URL", os.environ.get("DATABASE_URL", ""))
    return os.environ.get("DATABASE_URL", "")


async def get_manager() -> ConnectionManager:
    """Dependency to get the ConnectionManager instance from app.state"""
    return app_globals.get("manager")


async def get_db_pool(
    manager: Annotated[ConnectionManager, Depends(get_manager)],
) -> asyncpg.Pool:  # pragma: no cover
    """Get database pool with proper error handling"""
    try:
        return await manager.get_db_pool()
    except Exception as e:
        logger.error(f"Error getting database pool: {e}", exc_info=True)
        raise HTTPException(status_code=503, detail="Database not available")


@alru_cache(maxsize=10)
async def get_station_timezone(station_name: str, pool: asyncpg.Pool) -> str:
    """Get the timezone for a given station"""
    # logger.debug(f"get_station_timezone called for {station_name}")
    async with pool.acquire() as conn:
        result = await conn.fetchval(
            "SELECT get_station_timezone_name($1)", station_name
        )
        logger.debug(f"get_station_timezone result for {station_name}: {result}")
        return result or "UTC"


async def query_wind_data(
    station: str,
    start_time: datetime,
    end_time: datetime,
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
):
    # Convert timezone-aware datetimes to timezone-naive UTC for asyncpg
    # (PostgreSQL timestamp columns are typically timezone-naive)
    if start_time.tzinfo is not None:
        start_time = start_time.astimezone(timezone.utc).replace(tzinfo=None)
    if end_time.tzinfo is not None:
        end_time = end_time.astimezone(timezone.utc).replace(tzinfo=None)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM get_wind_data_by_station_range($1, $2, $3)",
            station,
            start_time,
            end_time,
        )

        return (
            WindDataPoint(
                timestamp=row["update_time"],
                direction=row["direction"],
                speed_kts=row["speed_kts"],
                gust_kts=row["gust_kts"],
            )
            for row in rows
        )


async def get_latest_wind_data(station: str, pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM get_latest_wind_observation($1)", station
        )
        if row:
            # Ensure update_time is timezone-aware before processing
            update_time = row["update_time"]
            if update_time.tzinfo is None:
                update_time = update_time.replace(tzinfo=timezone.utc)

            return WindDataPoint(
                timestamp=update_time,
                direction=row["direction"],
                speed_kts=row["speed_kts"],
                gust_kts=row["gust_kts"],
            ).model_dump()
        return None


router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def live_wind_chart(
    request: Request, stn: str = DEFAULT_STATION, hours: int = 3, minutes: int = 0
):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "gtag_id": GTAG_ID,
            "station": stn,
            "hours": hours,
            "minutes": minutes,
            "is_live": True,
        },
    )


@router.get("/day")
async def redirect_to_today(stn: str = DEFAULT_STATION, hours: int = 24):
    """Redirect to current date when no date is specified"""
    today = datetime.now().strftime("%Y-%m-%d")
    return RedirectResponse(
        url=f"/day/{today}?stn={stn}&hours={hours}", status_code=302
    )


@router.get("/day/{date}", response_class=HTMLResponse)
async def historical_wind_day_chart(
    request: Request,
    date: str,
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    stn: str = DEFAULT_STATION,
    hours: int = 24,
):
    try:
        # Parse ISO date (YYYY-MM-DD) - simple validation
        selected_date = datetime.strptime(date, "%Y-%m-%d")

        # Calculate previous and next dates
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)

        # Get station timezone to convert local day boundaries to UTC
        station_tz_name = await get_station_timezone(stn, pool)
        station_tz = zoneinfo.ZoneInfo(station_tz_name)

        # Create day boundaries in station timezone, then convert to UTC
        day_start_local = selected_date.replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=station_tz
        )
        day_end_local = day_start_local + timedelta(days=1)

        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = day_end_local.astimezone(timezone.utc)

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "gtag_id": GTAG_ID,
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


@router.get("/health")
async def health_check(
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    manager: Annotated[ConnectionManager, Depends(get_manager)],
):
    """Health check endpoint for monitoring and load balancers"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
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
        "active" if manager.active_connections else "no_connections"
    )

    # Check PostgreSQL listener
    health_status["postgresql_listener"] = (
        "healthy" if await manager.is_pg_listener_healthy else "unhealthy"
    )

    # Check connection monitor
    health_status["connection_monitor"] = (
        {
            "done": manager.monitor_task.done(),
            "cancelled": manager.monitor_task.cancelled(),
        }
        if manager.monitor_task
        else "no_task"
    )

    # Add cache statistics
    health_status["cache"] = {
        "cache_hit_count": manager.cache_hit_count,
        "cache_miss_count": manager.cache_miss_count,
        "cache_hit_ratio": (
            manager.cache_hit_count
            / (manager.cache_hit_count + manager.cache_miss_count)
            if (manager.cache_hit_count + manager.cache_miss_count) > 0
            else 0
        ),
        "stations_cached": len(manager.wind_data_cache),
        "total_cached_entries": sum(
            len(entries) for entries in manager.wind_data_cache.values()
        ),
        "oldest_cache_entry": datetime.fromtimestamp(
            min(manager.cache_oldest_time.values()), tz=timezone.utc
        )
        if manager.cache_oldest_time
        else None,
        "cache_duration_hours": DATA_CACHE_HOURS,
    }

    # Determine overall status
    if (
        health_status["database"] == "connected"
        and await manager.is_pg_listener_healthy
    ):
        health_status["status"] = "healthy"
    else:
        health_status["status"] = "unhealthy"

    return health_status


@router.get("/health/stack", response_class=PlainTextResponse)  # pragma: no cover
async def get_health_stack(manager: Annotated[ConnectionManager, Depends(get_manager)]):
    """Returns the stack of the monitoring task"""
    if manager.monitor_task:
        return "\n".join(str(s) for s in manager.monitor_task.get_stack())
    return "no_task"


@router.get("/api/wind")
async def get_wind_data(
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    manager: Annotated[ConnectionManager, Depends(get_manager)],
    stn: str = DEFAULT_STATION,
    from_time: str | None = None,
    to_time: str | None = None,
    hours: int | None = None,
) -> dict:
    # Get station timezone for metadata only
    station_tz_name = await get_station_timezone(stn, pool)

    if from_time and to_time:
        # Parse datetime strings as UTC (no timezone conversion)
        start_time = datetime.strptime(from_time, ISO_FORMAT).replace(
            tzinfo=timezone.utc
        )
        end_time = datetime.strptime(to_time, ISO_FORMAT).replace(tzinfo=timezone.utc)

    elif hours:
        # For relative time queries, use current UTC time
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=hours)
        end_time = now_utc
    else:
        # Default: last 24 hours in UTC
        now_utc = datetime.now(timezone.utc)
        start_time = now_utc - timedelta(hours=24)
        end_time = now_utc

    # Try cache-first approach
    is_cache_hit = await manager._is_cache_hit(stn, start_time)
    logger.debug(
        f"Cache check for station {stn}: hit={is_cache_hit}, start_time={start_time}, cache_oldest={manager.cache_oldest_time.get(stn, 'None')}, cache_size={len(manager.wind_data_cache.get(stn, []))}"
    )

    if is_cache_hit:
        # Cache hit - get data from cache
        cached_data = await manager._get_cached_data(stn, start_time, end_time)
        manager.cache_hit_count += 1
        logger.debug(
            f"Cache hit for station {stn}, returned {len(cached_data)} data points"
        )
        winddata = cached_data
    else:
        # Cache miss - query database and update cache
        manager.cache_miss_count += 1
        logger.debug(f"Cache miss for station {stn}, querying database")

        # Query database
        winddata = [
            (point.timestamp, point.direction, point.speed_kts, point.gust_kts)
            for point in await query_wind_data(stn, start_time, end_time, pool)
        ]

        # Update cache with fresh data
        logger.debug(
            f"Updating cache for station {stn} with data from {start_time} to {end_time}"
        )
        await manager._update_cache_with_data(stn, start_time, end_time, winddata)
        logger.debug(
            f"Cache updated for station {stn}, cache size now: {len(manager.wind_data_cache.get(stn, []))}"
        )

    return {
        "station": stn,
        "winddata": winddata,
        "timezone": station_tz_name,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
        "cache_hit": is_cache_hit,
    }


@router.websocket("/ws/{station}")
async def websocket_endpoint(
    websocket: WebSocket,
    station: str,
    pool: Annotated[asyncpg.Pool, Depends(get_db_pool)],
    manager: Annotated[ConnectionManager, Depends(get_manager)],
):
    await manager.connect(websocket, station)
    try:
        # Send initial data
        initial_data = await get_latest_wind_data(station, pool)
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
        manager.disconnect(websocket, station)


app = make_app()

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
