#!/bin/bash

# WindBurglr Test Runner Script

set -e

echo "🧪 WindBurglr Test Suite"
echo "========================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    print_warning "Virtual environment not activated. Activating..."
    source .venv/bin/activate
fi

# Install test dependencies
print_status "Installing test dependencies..."
#pip install -e ".[dev]"
#pip install pytest-cov pytest-playwright playwright
uv sync --extra dev
uv pip install pytest-cov pytest-playwright playwright
playwright install chromium

# Set test environment
export $(cat .env.test | xargs)

# Run database setup
print_status "Setting up test database..."
python -c "
import asyncio
import asyncpg
import os

async def setup_test_db():
    try:
        conn = await asyncpg.connect(os.getenv('TEST_DATABASE_URL'))

        # Create test schema if needed
        await conn.execute('CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";')

        await conn.execute('CREATE EXTENSION IF NOT EXISTS timescaledb;')

        # Create basic tables for testing
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS station (
                id SERIAL PRIMARY KEY,
                name VARCHAR(10) UNIQUE NOT NULL,
                timezone_name VARCHAR(50) NOT NULL DEFAULT 'UTC'
            );
        ''')

        await conn.execute('''
            CREATE TABLE IF NOT EXISTS wind_obs (
                station_id INTEGER REFERENCES station(id),
                update_time TIMESTAMP NOT NULL,
                direction INTEGER,
                speed_kts INTEGER,
                gust_kts INTEGER
            );
        ''')

        await conn.execute('''
            SELECT create_hypertable('wind_obs','update_time');
            ''')

        # Insert test stations
        await conn.execute('''
            INSERT INTO station (id, name, timezone_name) VALUES
                (1, 'CYTZ', 'America/Toronto'),
                (2, 'CYYZ', 'America/Toronto'),
                (3, 'CYVR', 'America/Vancouver')
            ON CONFLICT (id) DO NOTHING;
        ''')

        await conn.close()
        print('✓ Test database setup complete')
    except Exception as e:
        print(f'✗ Test database setup failed: {e}')
        exit(1)

asyncio.run(setup_test_db())
"

# Run tests based on arguments
if [[ "$1" == "unit" ]]; then
    print_status "Running unit tests..."
    pytest tests/unit -v -m "unit"
elif [[ "$1" == "integration" ]]; then
    print_status "Running integration tests..."
    pytest tests/integration -v -m "integration"
elif [[ "$1" == "e2e" ]]; then
    print_status "Running end-to-end tests..."
    pytest tests/e2e -v -m "e2e"
elif [[ "$1" == "quick" ]]; then
    print_status "Running quick tests (unit only)..."
    pytest tests/unit -v -m "unit and not slow"
elif [[ "$1" == "coverage" ]]; then
    print_status "Running all tests with coverage..."
    pytest tests/ -v --cov=main --cov-report=html --cov-report=term-missing
else
    print_status "Running all tests..."
    pytest tests/ -v
fi

print_status "Test suite completed!"
