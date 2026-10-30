# WindBurglr FastAPI

A modern FastAPI-based wind observation web application with real-time WebSocket streaming and Chart.js visualizations.

## Features

- **Real-time Updates**: WebSocket connection streams live wind data
- **Interactive Charts**: Chart.js powered visualizations for wind speed and direction
- **Responsive Design**: Mobile-friendly interface
- **Historical Data**: View wind data for different time ranges
- **RESTful API**: Full API for wind observations

## Installation

### Using Nix (Recommended)

For the best development experience, use Nix to set up a complete development environment:

1. Install Nix: https://nixos.org/download.html

2. Enable flakes (if not already enabled):
```bash
echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf
```

3. Enter the development environment:
```bash
nix develop ..#webapp
```
or with direnv:
```bash
direnv allow
```

The environment provides Python 3.13, uv, Node.js 22, pyright and PostgreSQL 18. It does not start
anything; see [Development environment](../README.md#development-environment) for the shared
database (`make db-up`). Install dependencies with `uv sync` and `npm install`.
- Install all Python and Node.js dependencies

### Traditional Installation

1. Install dependencies:
```bash
uv sync --dev
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

### WebSocket /ws/{station}
Real-time wind data stream for specified station

## Development

### Available Commands

Once in the Nix development environment:

```bash
# Start the full application (backend + frontend)
./start.sh

# Backend development
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Frontend development
npm run dev         # Start Vite dev server
npm run build       # Build for production
npm run preview     # Preview production build

# Testing
pytest                     # Run Python tests
npm test                   # Run frontend tests
npm run test:coverage      # Run tests with coverage

# Code Quality
ruff check .               # Lint Python code
ruff format .              # Format Python code
pyright                    # Type check Python code

# Database Management
make db-up                 # Start the shared PostgreSQL cluster
make db-down               # Stop it
make db-connect            # Connect to the development database
make db-status             # Show cluster state and databases
make db-reset-dev          # Recreate the development database
```

### Development Workflow

1. Enter the Nix environment (`nix develop ..#webapp`, or direnv) and start the database: `make db-up`
2. Start the backend: `./start.sh`
3. In another terminal, start the frontend: `npm run dev`
4. Open http://localhost:5173 for the frontend dev server
5. The backend API will be available at http://localhost:8000
6. The development database is `postgresql://webapp@/windburglr_dev` (host from `PGHOST`)

### Testing

Run the full test suite:
```bash
pytest -v
npm run test:run
```

Run with coverage:
```bash
pytest --cov-report=html
npm run test:coverage
```

## Frontend Features

- **Live Dashboard**: Real-time wind conditions display
- **Interactive Charts**:
  - Wind speed over time with gust overlay
  - Wind direction scatter plot, labelled on right axis
- **Time Range Selection**: View data for 1, 3, 6, 12, or 24 hours
- **Connection Status**: Visual WebSocket connection indicator
- **Historical Data**: Retrieve past observations by date
- **Zoom**: Click or touch and drag to zoom in, double click/tap to zoom out
- **Scraper Status**: Visual scraper status indicator in header and banner showing details

## Technology Stack

- **Backend**: FastAPI, WebSockets, PostgreSQL
- **Frontend**: Vanilla JavaScript, Chart.js
- **Styling**: Modern CSS with responsive design, light/dark theme
- **Real-time**: WebSocket for live data streaming
