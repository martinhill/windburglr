import os
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

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
ISO_FORMAT = '%Y-%m-%dT%H:%M:%S.%fZ'
EPOCH = datetime.fromtimestamp(0, tz=timezone.utc)

class Station(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)

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
        "minutes": minutes
    })

@app.get("/api/wind")
async def get_wind_data(
    stn: str = DEFAULT_STATION,
    from_time: Optional[str] = None,
    to_time: Optional[str] = None,
    hours: Optional[int] = None
):
    if from_time:
        start_time = datetime.strptime(from_time, ISO_FORMAT)
    elif hours:
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
    else:
        start_time = datetime.now(timezone.utc) - timedelta(hours=24)

    if to_time:
        end_time = datetime.strptime(to_time, ISO_FORMAT)
    else:
        end_time = datetime.now(timezone.utc)

    winddata = await query_wind_data(stn, start_time, end_time)
    return {"station": stn, "winddata": winddata}

@app.post("/api/wind")
async def create_wind_observation(observation: WindObservation):
    engine = get_engine()
    if not engine:
        raise HTTPException(status_code=500, detail="Database connection failed")

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
