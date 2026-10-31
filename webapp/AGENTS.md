# WindBurglr webapp: agent guidelines

See [README.md](README.md) for the layout, commands and configuration.

## Development Environment

- Tools and variables come from the root flake (`nix develop ..#webapp`, or direnv via `.envrc`).
  Loading it has no side effects; it does not start the database.
- Start the shared PostgreSQL cluster with `../scripts/db.sh up` (or `make db-up`) before running
  integration tests or the app. It is socket-only; `PGHOST`, `PGUSER` and `PGDATABASE` point at it.
- Tests create their own database cloned from `windburglr_template` and drop it afterwards;
  never point tests at `windburglr_dev`.
- The development database is `windburglr_dev`; connect as the `webapp` role
  (`postgresql://webapp@/windburglr_dev`) for production-like permissions.

## Build/Test Commands

```bash
uv sync && npm install                       # dependencies
uv run ruff check . && uv run ruff format .  # lint, format
uv run pyright                               # type check
npm run build                                # the Python tests need dist/
uv run pytest tests/unit tests/integration   # Python tests, as in CI
uv run pytest tests/unit/test_api.py::TestClass::test_name  # a single test
npm run test:run                             # frontend tests (Vitest)
```

## Code Style Guidelines

### Python (main.py, app/)
- Use async/await for all database operations
- Import order: stdlib, third-party, local (enforced by ruff)
- Type hints required, in modern syntax: `int | None`, `list[WebSocket]`
- Error handling: Use HTTPException for API errors, log with logger.error()
- Naming: snake_case for functions/variables, PascalCase for classes
- Use `datetime.UTC` for all UTC operations, never naive datetimes

### JavaScript (src/)
- ES modules; state goes through the store in `src/store/store.js`
- Use `toISOString()` for API timestamps
- Use `toLocaleTimeString()` with `timeZone` for display
- Camel case for variables, kebab-case for CSS classes
- Put unit tests next to the module as `*.test.js`

## Application wiring

- `app/lifespan.py` creates every service once at startup (pool, cache, services, WebSocket
  manager, Postgres listener, cache hydration) and stores it on `app.state`; it shuts them down
  in reverse. Routes get them through `app/dependencies.py`, which reads `app.state`; don't add
  module-level singletons.
- Tests build apps with `main.create_app(StartupOptions(...))` rather than overriding
  dependencies. `make_test_client` starts the app after the test has seeded mock data.

## Critical Rules
- **ALL database timestamps are UTC** - never convert in backend
- Use Pydantic for data models, FastAPI for endpoints
- Log timezone operations at DEBUG level
- Pushes to `master` deploy to production (see the root README)
