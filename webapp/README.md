# WindBurglr webapp

The web interface for WindBurglr: a FastAPI backend serving pages, a JSON API and WebSocket
updates, with a Vite-built vanilla JavaScript frontend that charts wind speed, gusts and
direction with Chart.js.

## Features

- **Live view** (`/`): current conditions and a chart that updates over a WebSocket as the
  scraper stores new observations. Choose a 1 to 24 hour window.
- **Historical view** (`/day/YYYY-MM-DD`): a day of observations in the station's local time,
  with previous/next day navigation.
- **Zoom**: click or touch and drag to zoom in; double click/tap to zoom out.
- **Scraper status**: a header indicator and banner when the scraper reports errors or stale
  data.
- Mobile-friendly layout with light and dark themes.

## Layout

```
main.py            FastAPI app: lifespan (DB pool, suspension detector), routers, static mounts
app/
  config.py        settings from environment variables
  dependencies.py  DB pool, cache, services and built-asset lookup for templates
  routers/         web pages, /api, /ws, /health
  services/        wind data, stations, Postgres LISTEN/NOTIFY, WebSocket fan-out, scraper watchdog
  cache/           in-memory wind data cache
templates/         Jinja2 pages (base, index, day)
static/            icons, manifest and images, served as-is
db/                dbmate migrations/ and seed.sql
src/               frontend source, bundled by Vite into dist/
  main.js          entry point
  store/           central state store; components subscribe to changes
  chart/           Chart.js setup and zoom
  websocket/       live connection and reconnection gap filling
  ui/              conditions display, scraper status, mobile handling
  utils/           data fetching and time formatting
  styles/          CSS, imported from main.js
tests/             pytest: unit/, integration/ (real database), e2e/ (Playwright)
```

Frontend unit tests (`*.test.js`) sit next to the modules they test; `src/test/setup.js` holds
the Vitest mocks.

## Development

The root Nix flake provides Python 3.13, uv, Node.js 24, pyright and PostgreSQL. Enter it with
`nix develop ..#webapp` or direnv (`direnv allow`); see
[Development environment](../README.md#development-environment) for the shared database.

```bash
make db-up        # start the shared PostgreSQL cluster
make install      # uv sync && npm install
make dev          # backend on :8000 with Vite hot reloading; Ctrl-C stops both
```

Open http://localhost:8000. `make dev` sets `DEV_MODE=true`, so pages load scripts and styles
from the Vite dev server on port 5173 instead of `dist/`.

To run the backend against a production build instead: `make build`, then `make backend`. The
app mounts `dist/` at startup, so it needs a build (or `make dev`'s `DEV_MODE`) to render pages
with assets, and the Python tests need `dist/` to exist.

Both `make dev` and `make backend` export `.env` if it exists (copy `.env.example`). Locally,
connect as the `webapp` role for production-like permissions:
`DATABASE_URL=postgresql://webapp@/windburglr_dev`.

`make help` lists the other targets (`test`, `lint`, `format`, `type-check`, `clean`, `db-*`).

### Configuration

Environment variables, read in `app/config.py` and `main.py`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | | PostgreSQL connection; also used for LISTEN/NOTIFY |
| `DATABASE_POOL_URL` | `DATABASE_URL` | Connection for the query pool, e.g. a pooler |
| `DEV_MODE` | `false` | Load frontend assets from the Vite dev server |
| `LOG_LEVEL` | `INFO` | |
| `DATA_CACHE_HOURS` | `48` | Hours of observations kept in the in-memory cache |
| `SCRAPER_STATUS_TIMEOUT_MINUTES` | `5` | When the watchdog considers scraper status stale |
| `WEBSOCKET_PING_TIMEOUT` | `60` | Seconds |
| `POSTGRES_MONITOR_INTERVAL` | `30` | Seconds between LISTEN connection health checks |
| `GOOGLE_TAG_MANAGER_ID` | | Adds Google Tag Manager to pages when set |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_RELEASE` | | Error reporting; also read from `.env.sentry` |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Fraction of transactions traced (0.0-1.0), server and browser |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.0` | Fraction of traced transactions profiled (0.0-1.0) |

## Endpoints

- `GET /?stn=CYTZ&hours=3`: live page
- `GET /day?stn=CYTZ`: redirects to today in the station's timezone
- `GET /day/{YYYY-MM-DD}?stn=CYTZ`: historical page
- `GET /api/wind?stn=CYTZ`: observations as JSON. Either `from_time` and `to_time`
  (`YYYY-MM-DDTHH:MM:SS`, UTC) or `hours`; defaults to the last 24 hours
- `WS /ws/{station}`: live observations and scraper status
- `GET /health/live`: liveness (the Fly.io check); `GET /health`: database, WebSocket and
  LISTEN connection status; `GET /health/scraper`, `GET /health/scraper-details`: scraper status

## Testing

```bash
make db-up                                  # integration and e2e tests need the database
npm run build                               # the app mounts dist/ at import time
uv run pytest tests/unit tests/integration  # what CI runs
npm run test:run                            # Vitest; `npm test` watches
```

Each pytest session clones its own database from the template and drops it afterwards (see
`tests/conftest.py`). Set `TEST_DATABASE_URL` to use a specific database. Without the dev
environment, database tests are skipped locally; in CI they fail instead.

Plain `uv run pytest` also runs `tests/e2e`, which starts the app with uvicorn and drives it
with Playwright. Install a browser first with `uv run playwright install chromium`.

pytest settings live in `pyproject.toml`. pytest-asyncio runs in strict mode, so async tests
need `@pytest.mark.asyncio` (or `anyio`). Coverage reports are written to `htmlcov/` and
`coverage.xml`; pass `--no-cov` to skip them.

## Deployment

The app deploys to Fly.io as `windburglr` from CI; see [Deployment](../README.md#deployment).
The `Dockerfile` builds the frontend (uploading source maps to Sentry when `SENTRY_AUTH_TOKEN`
is available, then deleting them), installs the locked Python dependencies and runs
`fastapi run`. It requires `--build-arg SENTRY_RELEASE=...`. It also ships dbmate and the
migrations, which Fly's `release_command` applies as `MIGRATION_DATABASE_URL` before each deploy.

## Known issues and ideas

Issues:

- The frontend sometimes fails to request wind data on startup
- The historical day view starts at 7am?
- The click target for enabling/disabling a chart series is displaced above its label

Ideas:

- Testing: populate the test database for e2e tests and make assertions; visual checks of the
  frontend with a multimodal LLM; parameterized tests
- UI: optional wind direction arrows instead of the right-axis point plot; better chart
  animation; accessibility testing; toggle the time display between clock and minutes-ago;
  tooltips with details for current conditions (full update time, direction in degrees)
- Backend: shared cache (Redis, LiteFS); `/api/wind` pagination by date;
  `/api/wind/<station>/bydate/?date=YYYY-MM-DD`
