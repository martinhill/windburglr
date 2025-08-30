# WindBurglr FastAPI

A modern FastAPI-based wind observation web application with real-time WebSocket streaming and Chart.js visualizations.

## Features

- **Real-time Updates**: WebSocket connection streams live wind data
- **Interactive Charts**: Chart.js powered visualizations for wind speed and direction
- **Responsive Design**: Mobile-friendly interface
- **Historical Data**: View wind data for different time ranges
- **RESTful API**: Full API for wind observations

## Installation

1. Install dependencies:
```bash
poetry install
```
or
```bash
pip install -r requirements.txt
```

2. Set up environment variables:
```bash
export DATABASE_URL="your_postgresql_connection_string"
```

3. Run the application:
```bash
./start.sh
```

Or manually:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## API Endpoints

### GET /
Main web interface

### GET /api/wind
Get historical wind data
- `stn`: Station name (default: CYTZ)
- `from_time`: Start time (ISO format)
- `to_time`: End time (ISO format)

### POST /api/wind
Create new wind observation
```json
{
    "station": "CYTZ",
    "direction": 270,
    "speed_kts": 15,
    "gust_kts": 20,
    "update_time": "2024-01-01T12:00:00Z"
}
```

### WebSocket /ws/{station}
Real-time wind data stream for specified station

## Database Schema

The application expects a PostgreSQL database with the following tables:

```sql
CREATE TABLE station (
    id serial PRIMARY KEY,
    name text NOT NULL
);

CREATE TABLE wind_obs (
    station_id integer references station (id),
    update_time timestamp,
    direction numeric,
    speed_kts numeric,
    gust_kts numeric,
    PRIMARY KEY (station_id, update_time)
);
```

## Frontend Features

- **Live Dashboard**: Real-time wind conditions display
- **Interactive Charts**:
  - Wind speed over time with gust overlay
  - Wind direction scatter plot
- **Time Range Selection**: View data for 1, 3, 6, 12, or 24 hours
- **Connection Status**: Visual WebSocket connection indicator
- **Historical Data**: Retrieve past observations by date
- **Zoom**: Click or touch and drag to zoom in, double click/tap to zoom out

## Technology Stack

- **Backend**: FastAPI, WebSockets, PostgreSQL
- **Frontend**: Vanilla JavaScript, Chart.js
- **Styling**: Modern CSS with responsive design
- **Real-time**: WebSocket for live data streaming
