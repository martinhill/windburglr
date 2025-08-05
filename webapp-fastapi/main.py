import os
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import zoneinfo

from sqlmodel import SQLModel, Field, create_engine, Session, select
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    task = asyncio.create_task(periodic_data_broadcast())
    yield
    # Shutdown
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

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
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

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

        results = []
        for row in session.exec(statement):
            results.append((epoch_time(row.update_time), safe_int(row.direction), safe_int(row.speed_kts), safe_int(row.gust_kts)))

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
    engine = get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")

    raise HTTPException(status_code=500, detail="Not implemented")

    try:
        with Session(engine) as session:
            # Get station by name
            station = session.exec(select(Station).where(Station.name == observation.station)).first()
            if not station:
                raise HTTPException(status_code=404, detail=f"Station {observation.station} not found")

            # Create wind observation
            wind_obs = WindObs(
                station_id=station.id,
                direction=observation.direction,
                speed_kts=observation.speed_kts,
                gust_kts=observation.gust_kts,
                update_time=observation.update_time
            )

            session.add(wind_obs)
            session.commit()

            # Broadcast new data to all connected WebSocket clients
            wind_data = {
                "station": observation.station,
                "timestamp": epoch_time(observation.update_time),
                "direction": observation.direction,
                "speed_kts": observation.speed_kts,
                "gust_kts": observation.gust_kts
            }
            await manager.broadcast(json.dumps(wind_data))

            return observation
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.websocket("/ws/{station}")
async def websocket_endpoint(websocket: WebSocket, station: str):
    await manager.connect(websocket)
    try:
        # Send initial data
        initial_data = await get_latest_wind_data(station)
        if initial_data:
            await websocket.send_text(json.dumps(initial_data))

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message from client (ping/pong)
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send periodic updates
                latest_data = await get_latest_wind_data(station)
                if latest_data:
                    await websocket.send_text(json.dumps(latest_data))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)

async def periodic_data_broadcast():
    while True:
        try:
            latest_data = await get_latest_wind_data()
            if latest_data and manager.active_connections:
                await manager.broadcast(json.dumps(latest_data))
        except Exception as e:
            print(f"Error in periodic broadcast: {e}")
        await asyncio.sleep(30)  # Broadcast every 30 seconds

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
