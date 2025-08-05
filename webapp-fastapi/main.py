import os
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict
import zoneinfo

from sqlmodel import SQLModel, Field, create_engine, Session, select
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn
import asyncpg

# Configure logging
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
log_level_value = getattr(logging, log_level, logging.INFO)

# Configure root logger
logging.basicConfig(
    level=log_level_value,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
    force=True  # Force reconfiguration even if already configured
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

DEFAULT_STATION = 'CYTZ'
ISO_FORMAT = '%Y-%m-%dT%H:%M:%S'
EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)

async def get_station_timezone(station_name: str) -> str:
    """Get the timezone for a given station"""
    engine = get_engine()
    if not engine:
        return 'UTC'

    with Session(engine) as session:
        station = session.exec(select(Station).where(Station.name == station_name)).first()
        return station.timezone if station else 'UTC'

class Station(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    timezone: str = Field(index=True)

class WindObs(SQLModel, table=True):
    __tablename__ = "wind_obs"

    id: Optional[int] = Field(default=None, primary_key=True)
    station_id: int = Field(foreign_key="station.id")
    direction: Optional[float]
    speed_kts: Optional[float]
    gust_kts: Optional[float]
    update_time: datetime

class WindObservation(BaseModel):
    station: str
    direction: Optional[float]
    speed_kts: Optional[float]
    gust_kts: Optional[float]
    update_time: datetime

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.pg_listener: Optional[asyncpg.Connection] = None
        self.notification_count = 0

    async def connect(self, websocket: WebSocket, station: str):
        await websocket.accept()
        if station not in self.active_connections:
            self.active_connections[station] = []
        self.active_connections[station].append(websocket)
        logger.info(f"WebSocket connected for station {station}. Total connections: {len(self.active_connections[station])}")

    def disconnect(self, websocket: WebSocket, station: str):
        if station in self.active_connections:
            try:
                self.active_connections[station].remove(websocket)
                if not self.active_connections[station]:
                    del self.active_connections[station]
                    logger.info(f"All connections for station {station} disconnected")
                else:
                    logger.info(f"WebSocket disconnected for station {station}. Remaining connections: {len(self.active_connections[station])}")
            except ValueError:
                logger.warning(f"Failed to remove WebSocket connection for station {station}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast_to_station(self, message: str, station: str):
        if station in self.active_connections:
            logger.debug(f"Broadcasting to {len(self.active_connections[station])} connections for station {station}")
            disconnected = []
            for connection in self.active_connections[station]:
                try:
                    await connection.send_text(message)
                    logger.debug(f"Successfully sent message {message} to connection for station {station}")
                except Exception as e:
                    logger.warning(f"Failed to send message to connection for station {station}: {e}")
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
            logger.info(f"Connecting to PostgreSQL for notifications: {database_url[:50]}...")
            self.pg_listener = await asyncpg.connect(database_url)

            # Test the connection
            result = await self.pg_listener.fetchval("SELECT 1")
            logger.debug(f"PostgreSQL connection test result: {result}")

            await self.pg_listener.add_listener('wind_obs_insert', self._handle_notification)
            logger.info("PostgreSQL listener started successfully")
            logger.info("Listening for channels: wind_obs_insert")

            # Test if we can send/receive a test notification
            await self.pg_listener.execute("SELECT pg_notify('test_channel', 'test_message')")
            logger.debug("Test notification sent")

        except Exception as e:
            logger.error(f"Failed to start PostgreSQL listener: {e}", exc_info=True)

    async def stop_pg_listener(self):
        if self.pg_listener:
            try:
                await self.pg_listener.close()
                logger.info("PostgreSQL listener stopped")
            except Exception as e:
                logger.error(f"Error stopping PostgreSQL listener: {e}", exc_info=True)

    async def _handle_notification(self, connection, pid, channel, payload):
        try:
            self.notification_count += 1
            logger.info(f"🔔 Received notification #{self.notification_count} on channel '{channel}' from PID {pid}")
            logger.debug(f"Raw payload: {payload}")

            data = json.loads(payload)
            logger.debug(f"Parsed notification data: {data}")

            station_name = data.get('station_name')
            logger.debug(f"Station name from notification: {station_name}")

            if station_name:
                # Apply the same safe_int conversion as used elsewhere
                wind_data = {
                    "timestamp": data.get('update_time'),
                    "direction": safe_int(data.get('direction')),
                    "speed_kts": safe_int(data.get('speed_kts')),
                    "gust_kts": safe_int(data.get('gust_kts'))
                }
                logger.info(f"📡 Broadcasting wind data to station {station_name}: {wind_data}")
                logger.debug(f"Active connections for {station_name}: {len(self.active_connections.get(station_name, []))}")

                await self.broadcast_to_station(json.dumps(wind_data), station_name)
            else:
                logger.warning("No station name found in notification data")
        except Exception as e:
            logger.error(f"Error handling notification: {e}", exc_info=True)
manager = ConnectionManager()

def get_database_url():
    return os.environ.get('DATABASE_URL', '')

def get_engine():
    database_url = get_database_url()
    if database_url:
        return create_engine(database_url)
    return None

def epoch_time(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = dt - EPOCH
    return delta.total_seconds()

def safe_int(d):
    try:
        return int(d) if d is not None else None
    except (TypeError, ValueError):
        return None

async def query_wind_data(station: str, start_time: datetime, end_time: datetime):
    engine = get_engine()
    if not engine:
        return []

    with Session(engine) as session:
        statement = (
            select(WindObs.update_time, WindObs.direction, WindObs.speed_kts, WindObs.gust_kts)
            .join(Station, WindObs.station_id == Station.id)
            .where(Station.name == station)
            .where(WindObs.update_time >= start_time)
            .where(WindObs.update_time <= end_time)
            .order_by(WindObs.update_time)
        )

        results = [
            (epoch_time(row.update_time), safe_int(row.direction), safe_int(row.speed_kts), safe_int(row.gust_kts))
            for row in session.exec(statement)
        ]

        return results

async def get_latest_wind_data(station: str = DEFAULT_STATION):
    engine = get_engine()
    if not engine:
        return None

    with Session(engine) as session:
        statement = (
            select(WindObs.update_time, WindObs.direction, WindObs.speed_kts, WindObs.gust_kts)
            .join(Station, WindObs.station_id == Station.id)
            .where(Station.name == station)
            .order_by(WindObs.update_time.desc())
            .limit(1)
        )

        row = session.exec(statement).first()
        if row:
            return {
                "timestamp": epoch_time(row.update_time),
                "direction": safe_int(row.direction),
                "speed_kts": safe_int(row.speed_kts),
                "gust_kts": safe_int(row.gust_kts)
            }
        return None

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request, stn: str = DEFAULT_STATION, hours: int = 3, minutes: int = 0):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "station": stn,
        "hours": hours,
        "minutes": minutes,
        "is_live": True
    })

@app.get("/date/{date}", response_class=HTMLResponse)
async def read_date(request: Request, date: str, stn: str = DEFAULT_STATION, hours: int = 24):
    try:
        # Parse ISO date (YYYY-MM-DD) - simple validation
        selected_date = datetime.strptime(date, "%Y-%m-%d")

        # Calculate previous and next dates
        prev_date = selected_date - timedelta(days=1)
        next_date = selected_date + timedelta(days=1)

        # Create naive datetime strings for API (station timezone assumed)
        day_start = selected_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        return templates.TemplateResponse("index.html", {
            "request": request,
            "station": stn,
            "hours": hours,
            "minutes": 0,
            "is_live": False,
            "selected_date": date,
            "prev_date": prev_date.strftime("%Y-%m-%d"),
            "next_date": next_date.strftime("%Y-%m-%d"),
            "date_start": day_start.strftime("%Y-%m-%dT%H:%M:%S"),
            "date_end": day_end.strftime("%Y-%m-%dT%H:%M:%S")
        })
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

@app.get("/api/wind")
async def get_wind_data(
    stn: str = DEFAULT_STATION,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    hours: Optional[int] = None
):
    # Get station timezone for proper date handling
    station_tz_name = await get_station_timezone(stn)
    station_tz = zoneinfo.ZoneInfo(station_tz_name)

    if from_time and to_time:
        # Parse naive datetime strings and assume they're in station timezone
        start_naive = datetime.strptime(from_time, ISO_FORMAT)
        end_naive = datetime.strptime(to_time, ISO_FORMAT)

        # Apply station timezone and convert to UTC for database query
        start_time = start_naive.replace(tzinfo=station_tz).astimezone(timezone.utc)
        end_time = end_naive.replace(tzinfo=station_tz).astimezone(timezone.utc)

    elif hours:
        # For relative time queries, use current time in station timezone
        now_station = datetime.now(station_tz)
        start_station = now_station - timedelta(hours=hours)

        # Convert to UTC for database query
        start_time = start_station.astimezone(timezone.utc)
        end_time = now_station.astimezone(timezone.utc)
    else:
        # Default: last 24 hours in station timezone
        now_station = datetime.now(station_tz)
        start_station = now_station - timedelta(hours=24)

        # Convert to UTC for database query
        start_time = start_station.astimezone(timezone.utc)
        end_time = now_station.astimezone(timezone.utc)

    winddata = await query_wind_data(stn, start_time, end_time)
    return {
        "station": stn,
        "winddata": winddata,
        "timezone": station_tz_name,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat()
    }

@app.post("/api/wind")
async def create_wind_observation(observation: WindObservation):
    logger.info(f"Received wind observation: {observation}")
    engine = get_engine()
    if not engine:
        logger.error("Database connection failed")
        raise HTTPException(status_code=500, detail="Database connection failed")

    # No authorization yet, so do not allow for any request
    raise HTTPException(status_code=500, detail="Not implemented")

    try:
        with Session(engine) as session:
            logger.debug(f"Starting database transaction for observation: {observation}")

            # Get station by name
            logger.debug(f"Looking for station: {observation.station}")
            station = session.exec(select(Station).where(Station.name == observation.station)).first()
            if not station:
                logger.warning(f"Station {observation.station} not found")
                # List available stations for debugging
                all_stations = session.exec(select(Station)).all()
                available_stations = [s.name for s in all_stations]
                logger.warning(f"Available stations: {available_stations}")
                raise HTTPException(status_code=404, detail=f"Station {observation.station} not found")

            logger.info(f"Found station: {station.name} (ID: {station.id})")

            # Create wind observation
            wind_obs = WindObs(
                station_id=station.id,
                direction=observation.direction,
                speed_kts=observation.speed_kts,
                gust_kts=observation.gust_kts,
                update_time=observation.update_time
            )

            logger.info(f"Creating wind observation: station_id={wind_obs.station_id}, direction={wind_obs.direction}, speed={wind_obs.speed_kts}, gust={wind_obs.gust_kts}, time={wind_obs.update_time}")
            session.add(wind_obs)

            session.commit()
            logger.info(f"✅ Wind observation committed to database for station {observation.station} - trigger should have fired!")

            # The database trigger will automatically send notifications
            # No need to manually broadcast here

            return observation
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating wind observation: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))

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
            except asyncio.TimeoutError:
                # Send ping to keep connection alive
                await websocket.send_text(json.dumps({"type": "ping"}))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, station)



if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))

    # Configure uvicorn logging to respect our configuration
    uvicorn_log_level = log_level.lower()

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level=uvicorn_log_level,
        log_config=None  # Don't use uvicorn's default log config
    )
