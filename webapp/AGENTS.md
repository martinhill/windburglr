# WindBurglr Agent Guidelines

## Development Environment

- Tools and variables come from the root flake (`nix develop ..#webapp`, or direnv via `.envrc`).
  Loading it has no side effects; it does not start the database.
- Start the shared PostgreSQL cluster with `../scripts/db.sh up` before running integration tests
  or the app. It is socket-only; `PGHOST`, `PGUSER` and `PGDATABASE` point at it.
- Tests create their own database cloned from `windburglr_template` and drop it afterwards;
  never point tests at `windburglr_dev`.
- The development database is `windburglr_dev`; connect as the `webapp` role
  (`postgresql://webapp@/windburglr_dev`) for production-like permissions.

## Build/Test Commands

# Install dependencies
uv sync

```bash
# Run application
./start.sh

# Type checking
uv run pyright

# Linting (if available)
ruff check .
ruff format .

# Run tests
uv run pytest -v
```

## Code Style Guidelines

### Python (main.py)
- Use async/await for all database operations
- Import order: stdlib, third-party, local (SQLModel, FastAPI, asyncpg, etc.)
- Type hints required: `Optional[int]`, `List[WebSocket]`, `Dict[str, List[WebSocket]]`
- Error handling: Use HTTPException for API errors, log with logger.error()
- Naming: snake_case for functions/variables, PascalCase for classes
- Use `timezone.utc` for all UTC operations, never naive datetimes

### JavaScript (templates/index.html)
- Use `toISOString()` for API timestamps
- Use `toLocaleTimeString()` with `timeZone` for display
- Camel case for variables, kebab-case for CSS classes

## Critical Rules
- **ALL database timestamps are UTC** - never convert in backend
- Use Pydantic for database models, FastAPI for endpoints
- Log timezone operations at DEBUG level
- Do not commit changes without review
