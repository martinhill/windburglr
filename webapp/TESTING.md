This document provides comprehensive instructions for running tests on the WindBurglr application.

## Overview

The testing suite includes:
- **Unit Tests**: Individual component testing (sync-based)
- **Integration Tests**: Component interaction testing
- **End-to-End Tests**: Full application workflow testing with Playwright
- **Mock Database Tests**: Test without PostgreSQL dependencies

## Quick Start

```bash
# Run all tests
./run_tests.sh

# Run specific test types
./run_tests.sh unit          # Unit tests only
./run_tests.sh integration   # Integration tests only
./run_tests.sh e2e          # End-to-end tests only
./run_tests.sh quick        # Fast unit tests (excludes slow tests)
./run_tests.sh coverage     # All tests with coverage report
```

## Test Environment Setup

### Prerequisites

1. **Python Dependencies**: Install test dependencies
   ```bash
   pip install -e ".[dev]"
   playwright install chromium
   ```
   or using `uv`:
   ```bash
   uv sync --dev
   playwright install chromium
   ```

2. **Environment Variables**: Configure test environment
   ```bash
   cp tests/.env.test .env.test
   # Edit .env.test with your database credentials (optional for mock testing)
   ```

### Optional: Real Database Testing

For integration tests with a real PostgreSQL database:

1. **PostgreSQL server**: Ensure PostgreSQL is installed and running.
   ```bash
   podman run -d \
     --name windburglr-pg \
     -e POSTGRES_PASSWORD=windburglr \
     -p 5432:5432 \
     -v pgdata:/var/lib/postgresql/data \
     docker.io/timescale/timescaledb:latest-pg15
   ```

2. **PostgreSQL Test Database**: Create a test database
   ```bash
   createdb windburglr_test
   ```
   or
   ```bash
   psql -U postgres -c "CREATE DATABASE windburglr_test;"
   ```

## Test Structure

```
tests/
├── unit/                    # Unit tests (sync-based)
│   ├── test_api_endpoints.py
│   ├── test_websocket.py
│   ├── test_database_operations.py
│   └── test_api_sync.py
├── integration/             # Integration tests
│   └── test_integration_sync.py
├── e2e/                     # End-to-end tests (Playwright)
│   ├── test_frontend.py
│   └── conftest.py
├── fixtures/                # Test data and utilities
│   ├── database.py
│   ├── data.py
│   └── stations.py
├── conftest.py             # Pytest configuration
└── .env.test              # Test environment variables
```

## Running Tests

### Unit Tests

Unit tests focus on individual components and use sync-based testing:

```bash
# Run all unit tests
pytest tests/unit -v

# Run specific test file
pytest tests/unit/test_api_endpoints.py -v

# Run specific test
pytest tests/unit/test_api_endpoints.py::TestAPIEndpoints::test_root_endpoint -v
```

### Integration Tests

Integration tests verify component interactions with a real Postgres database:

```bash
# Run integration tests
pytest tests/integration -v

# Run with coverage
pytest tests/integration --cov=main --cov-report=html
```

### Mock Database Testing

Tests run with mock database by default (no PostgreSQL required):

```bash
# Run all tests with mock database
pytest tests/unit/ tests/e2e/ -v

# Run specific test categories
pytest tests/unit/ -v                    # Unit tests only
pytest tests/e2e/test_frontend.py -v     # E2E tests only
```

### End-to-End Tests

E2E tests use Playwright to test the full application:

```bash
# Install Playwright browsers (first time only)
playwright install chromium

# Run E2E tests
pytest tests/e2e -v

# Run E2E tests with visible browser (for debugging)
pytest tests/e2e -v --headed

# Run specific E2E test
pytest tests/e2e/test_frontend.py::TestFrontend::test_homepage_loads -v
```

## Test Data Generation

The test suite includes utilities for generating realistic test data:

### Wind Data Generator

```python
from tests.fixtures.data import WindDataGenerator

# Generate 24 hours of data
data = WindDataGenerator.generate_hourly_data("CYTZ", hours=24)

# Generate storm conditions
storm_data = WindDataGenerator.generate_storm_data("CYTZ", duration_hours=6)

# Generate calm conditions
calm_data = WindDataGenerator.generate_calm_data("CYTZ", duration_hours=12)
```

### Database Fixtures

```python
from tests.fixtures.database import TestDatabaseManager

# Create test database manager
manager = TestDatabaseManager(test_db_pool)

# Populate with test data
await manager.create_test_data("CYTZ", days=7)
```

## Testing Best Practices

### 1. Test Isolation

Each test runs in isolation with:
- Clean database state (mock or real)
- Fresh test data
- Independent WebSocket connections

### 2. Sync Testing

All tests use sync-based patterns for simplicity:

```python
def test_sync_function():
    result = sync_function()
    assert result is not None
```

### 3. Mock External Dependencies

Use mocks for external services:

```python
from unittest.mock import patch

@patch('main.get_database_url')
def test_with_mock_db(mock_db_url):
    mock_db_url.return_value = "sqlite:///./test.db"
    # Test code here
```

### 4. Test Categories

Use markers to categorize tests:

```python
@pytest.mark.unit
def test_unit_function():
    pass

@pytest.mark.integration
@pytest.mark.slow
def test_integration_function():
    pass
```

## Debugging Tests

### Common Issues

1. **Database Connection**: Ensure test database is running (if using real DB)
   ```bash
   pg_isready -h localhost -p 5432
   ```

2. **Port Conflicts**: Use different ports for test server
   ```bash
   export PORT=8001
   ```

3. **Playwright Issues**: Install browsers
   ```bash
   playwright install chromium firefox webkit
   ```

### Debug Mode

Run tests with debug output:

```bash
# Verbose output
pytest -vvs tests/unit/

# With logging
LOG_LEVEL=DEBUG pytest tests/unit/ -v

# With coverage
pytest --cov=main --cov-report=html tests/
```

## Continuous Integration

### GitHub Actions Example

```yaml
name: Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: windburglr_test
        ports: ['5432:5432']

    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.13'

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
          playwright install chromium

      - name: Run tests
        run: ./run_tests.sh
        env:
          TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/windburglr_test
```

## Frontend Testing Options

### 1. Playwright (Recommended)

- **Pros**: Modern, fast, reliable, supports multiple browsers
- **Cons**: Requires Node.js for some features
- **Use Case**: Full E2E testing

### 2. Selenium

- **Pros**: Mature, extensive browser support
- **Cons**: Slower, more complex setup
- **Use Case**: Legacy browser support

### 3. Cypress

- **Pros**: Great developer experience, time-travel debugging
- **Cons**: Limited browser support, Node.js required
- **Use Case**: Modern web apps

## Troubleshooting

### Test Database Issues

```bash
# Reset test database (if using real DB)
dropdb windburglr_test
createdb windburglr_test

# Run database migrations
psql windburglr_test < setup_notifications.sql
```

### WebSocket Testing

```bash
# Test WebSocket manually
websocat ws://localhost:8000/ws/CYTZ
```

### Coverage Reports

View coverage reports after running:

```bash
open htmlcov/index.html
```

## Support

For testing issues:
1. Check the troubleshooting section above
2. Review test logs: `pytest -vvs`
3. Check database connectivity (if using real DB)
4. Verify environment variables

### Test Database Configuration

**Mock Mode (Default)**: Tests run with mock database (no PostgreSQL required)
```bash
# Run all tests with mock database
pytest tests/unit/ tests/e2e/ -v
```

**Real Database Mode**: Set environment variable for PostgreSQL testing
```bash
export TEST_DATABASE_URL="postgresql://user:password@localhost:5432/windburglr_test"
pytest tests/unit/ tests/integration/ tests/e2e/ -v
```

## Database Test Data Management

The WindBurglr test suite provides optimized approaches for handling test data to avoid notification spam and improve performance.

### Bulk Data Loading (Recommended for Large Datasets)

For tests requiring large amounts of historical wind observation data, use the bulk data fixtures:

```python
@pytest.mark.anyio
async def test_api_with_bulk_historical_data(integration_client_with_bulk_data):
    """Test API with pre-loaded bulk data (no notification spam)."""

    # Data is already loaded - 1 day of minute-by-minute data for CYTZ
    # Bulk insert happens BEFORE app startup with disabled triggers

    response = await integration_client_with_bulk_data.get("/api/wind")
    assert response.status_code == 200

    data = response.json()
    assert data["station"] == "CYTZ"
    assert len(data["winddata"]) > 0  # Should have ~1440 observations
```

### Regular Data Insert (For Testing Notifications)

For tests that need to verify the notification system:

```python
@pytest.mark.anyio
async def test_api_with_notifications(integration_client, test_db_manager):
    """Test API with regular data insert (triggers notifications)."""

    # Small dataset - triggers notifications for each row
    await test_db_manager.create_test_data(station_name="CYYZ", days=0.1)

    response = await integration_client.get("/api/wind?station=CYYZ")
    assert response.status_code == 200
```

### Single Observation Testing (For Real-time Updates)

For testing real-time wind observation updates:

```python
@pytest.mark.anyio
async def test_realtime_notification(integration_client, test_db_manager):
    """Test real-time wind observation notifications."""
    from datetime import datetime, timezone

    # Insert single observation that triggers notification
    await test_db_manager.insert_new_wind_obs(
        station_name="CYTZ",
        direction=270,
        speed_kts=15,
        gust_kts=18,
        obs_time=datetime.now(timezone.utc)
    )

    response = await integration_client.get("/api/wind/latest?station=CYTZ")
    assert response.status_code == 200
```

### Available Test Fixtures

**Database Managers:**
- `test_db_manager`: Basic database manager for manual data creation
- `test_db_with_bulk_data`: Manager with pre-loaded 1 day of CYTZ data (no notifications)

**App Instances:**
- `app`: FastAPI app with empty database
- `app_with_bulk_data`: FastAPI app with pre-loaded bulk data (recommended)

**HTTP Clients:**
- `integration_client`: HTTP client with basic app (empty database)
- `integration_client_with_bulk_data`: HTTP client with pre-loaded data (recommended for API tests)
- `ws_integration_client`: WebSocket client for real-time testing

### Performance Comparison

**Bulk Insert Approach (Recommended):**
- ✅ Fast: Uses `executemany()` for bulk operations
- ✅ Clean logs: Temporarily disables triggers during insert
- ✅ Realistic: 1 day = 1440 observations at 1-minute intervals
- ✅ Safe: Automatically restores triggers after insert

**Individual Insert Approach:**
- ⚠️ Slow: Individual `INSERT` statements
- ⚠️ Log spam: Each insert triggers PostgreSQL notification
- ✅ Real notifications: Good for testing notification system
- ⚠️ Resource intensive: Don't use for large datasets


### Database Cleanup

All test fixtures handle automatic cleanup:
- Bulk data fixtures delete all test stations and their wind observations
- Database triggers are restored after bulk operations
- Connection pools are properly closed
- No deadlock risks from simplified cleanup approach
