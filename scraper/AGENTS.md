# WindBurglr scraper: agent guidelines

See [README.md](README.md) for configuration, error handling and commands.

## Development Environment

- Tools and variables come from the root flake (`nix develop ..#scraper`, or direnv via `.envrc`).
  Loading it has no side effects; it does not start the database.
- Start the shared PostgreSQL cluster with `../scripts/db.sh up` before running integration tests
  or the app. It is socket-only; `PGHOST`, `PGUSER` and `PGDATABASE` point at it.
- Tests create their own database cloned from `windburglr_template` and drop it afterwards;
  never point tests at `windburglr_dev`.
- The development database is `windburglr_dev`; connect as the `scraper` role
  (`postgresql://scraper@/windburglr_dev`) for production-like permissions.

## Build/Test Commands

```bash
uv sync                                                  # install dependencies
uv run scraper --config-file windburglr.toml             # run the scraper
uv run pytest                                            # all tests, with coverage
uv run pytest tests/unit/test_scraper.py::TestClass::test_name  # a single test
uv run ruff check . && uv run ruff format .              # lint, format
uv run pyright                                           # type check
```

## Code review

Run `coderabbit review --plain` to get comprehensive code analysis and improvement suggestions. Apply the feedback to write cleaner, more maintainable code.

## Code Style Guidelines

### Python

• Imports: stdlib → third-party → local modules (blank lines between groups)
• Type hints: Required for all functions, in modern syntax (`str | None`, `list[str]`)
• Naming: snake_case for functions/variables, PascalCase for classes
• Error handling: Custom exceptions inherit from WindburglrError, use async context managers
• Async/await: All I/O operations must be async
• Data models: dataclasses for configuration, Pydantic for observations; prefer either over dicts
• Logging: Use module-level loggers, appropriate levels (DEBUG/INFO/WARNING/ERROR) and always use percent-style string formatting with arguments, never use f-strings
• Line length: 88 characters (ruff default)
• Docstrings: Use triple quotes for module/class/function docs

### Database

• Connections: Use async context managers for database connections
• Migrations: Use raw SQL for schema changes, validate with tests
• Error handling: Catch specific exceptions (UniqueViolationError, etc.)

## Critical Rules

• NEVER use naive datetimes - always use timezone-aware UTC
• Database operations must be async - no blocking I/O
• Handle all exceptions gracefully - don't let errors crash the scraper
• Log at appropriate levels - DEBUG for development, INFO for operations
• Test database operations - use test database URLs in CI/tests
• Validate all inputs - use Pydantic models for data validation
