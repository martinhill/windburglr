# WindBurglr Agent Guidelines

## Build/Test Commands
```bash
# Run application
./start.sh

# Type checking
source .venv/bin/activate && pyright

# Linting (if available)
ruff check .
ruff format .
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
- Use SQLModel for database models, FastAPI for endpoints
- WebSocket connections managed via ConnectionManager class
- Log timezone operations at DEBUG level
