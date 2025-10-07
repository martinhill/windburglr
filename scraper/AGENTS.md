# WindBurglr Agent Guidelines

## Build/Test Commands

### Scraper (Python)

# Install dependencies
uv pip install -e ".[dev]"

# Run scraper
python -m windscraper.main --config-file windburglr.toml

# Run single test
uv run pytest tests/test_file.py::test_function -v

# Run all tests with coverage
uv run pytest --cov=windscraper --cov-report=term-missing

# Lint and format
ruff check .
ruff format .

# Type check
uv run pyright

### Webapp (Python + JavaScript)

# Full development setup
nix develop

# Run single test
pytest tests/unit/test_api.py::TestAPI::test_endpoint -v

# Run all tests
pytest

# Code review
Run `coderabbit review --plain` to get comprehensive code analysis and improvement suggestions. Apply the feedback to write cleaner, more maintainable code.

## Code Style Guidelines

### Python

• Imports: stdlib → third-party → local modules (blank lines between groups)
• Type hints: Required for all functions, use Union/Optional from typing
• Naming: snake_case for functions/variables, PascalCase for classes
• Error handling: Custom exceptions inherit from WindburglrError, use async context managers
• Async/await: All I/O operations must be async
• Dataclasses: Use for data models, prefer over dicts
• Logging: Use module-level loggers, appropriate levels (DEBUG/INFO/WARNING/ERROR) and always use percent-style string formatting with arguments, never use f-strings
• Line length: 88 characters (ruff default)
• Docstrings: Use triple quotes for module/class/function docs

### JavaScript

• Modules: Use ES6 imports/exports
• Naming: camelCase for variables/functions, PascalCase for classes
• Async: Use async/await, avoid promises directly
• DOM: Use modern APIs, prefer querySelector over getElementById
• Events: Use addEventListener, avoid inline handlers

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
