#!/bin/bash

# WindBurglr Test Runner Script for non-nix environment

set -e

echo "🧪 WindBurglr Test Suite"
echo "========================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
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

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Function to install Podman on macOS
setup_podman() {
    print_info "Checking Podman installation..."

    if command -v podman &> /dev/null; then
        print_status "Podman is already installed"
    else
        # Detect operating system
        if [[ "$OSTYPE" == "darwin"* ]]; then
            print_warning "Podman not found. Installing via Homebrew on macOS..."

            # Check if Homebrew is installed
            if ! command -v brew &> /dev/null; then
                print_error "Homebrew not found. Please install Homebrew first:"
                echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                exit 1
            fi

            # Install Podman
            brew install podman

            print_status "Podman installation completed"
        else
            print_error "Podman not found and automatic installation is only supported on macOS."
            print_info "Please install Podman manually for your platform:"
            echo "  - Linux: Use your package manager (apt, dnf, etc.)"
            echo "  - Windows: Download from https://podman.io/getting-started/installation"
            echo "  - Or use Docker as an alternative"
            exit 1
        fi
    fi

    # Initialize Podman machine (needed on all platforms that support it)
    if command -v podman &> /dev/null; then
        print_status "Initializing Podman machine..."
        podman machine init --cpus 2 --memory 4096 --disk-size 20 2>/dev/null || print_info "Podman machine initialization skipped (may not be needed on this platform)"
    fi
}

# Function to setup TimescaleDB container
setup_timescaledb() {
    print_info "Setting up TimescaleDB test database..."

    # Container and database configuration
    CONTAINER_NAME="windburglr-pg"
    DB_NAME="windburglr_test"
    DB_USER="windburglr"
    DB_PASSWORD="windburglr"
    DB_PORT="5433"

    # Check if container already exists and is running
    if podman ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        print_warning "TimescaleDB container is already running"
        return 0
    fi

    # Remove existing stopped container if it exists
    if podman ps -a --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        print_info "Removing existing stopped container..."
        podman rm -f "${CONTAINER_NAME}"
    fi

    # Start Podman machine if not running
    if ! podman machine info &> /dev/null; then
        print_status "Starting Podman machine..."
        podman machine start

        # Wait for machine to be ready
        sleep 10
    fi

    # Pull TimescaleDB image
    print_status "Pulling TimescaleDB image..."
    podman pull timescale/timescaledb:latest-pg15

    # Run TimescaleDB container
    print_status "Starting TimescaleDB container..."
    podman run -d \
        --name "${CONTAINER_NAME}" \
        -p "${DB_PORT}:5432" \
        -e POSTGRES_DB="${DB_NAME}" \
        -e POSTGRES_USER="${DB_USER}" \
        -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        timescale/timescaledb:latest-pg15

    # Wait for database to be ready
    print_status "Waiting for database to be ready..."
    for i in {1..30}; do
        if podman exec "${CONTAINER_NAME}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" &> /dev/null; then
            break
        fi
        sleep 1
    done

    if ! podman exec "${CONTAINER_NAME}" pg_isready -U "${DB_USER}" -d "${DB_NAME}" &> /dev/null; then
        print_error "Database failed to start within 30 seconds"
        exit 1
    fi

    print_status "TimescaleDB container is ready"

    # Update .env.test file with database URL
    export TEST_DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@localhost:${DB_PORT}/${DB_NAME}"
    echo "TEST_DATABASE_URL=${TEST_DATABASE_URL}" > .env.test
}

# Function to cleanup test database
cleanup_test_db() {
    print_info "Cleaning up test database..."
    CONTAINER_NAME="windburglr-timescaledb-test"

    if podman ps --format "{{.Names}}" | grep -q "^${CONTAINER_NAME}$"; then
        print_status "Stopping and removing TimescaleDB container..."
        podman stop "${CONTAINER_NAME}"
        podman rm "${CONTAINER_NAME}"
    fi
}

# Handle cleanup on script exit
trap cleanup_test_db EXIT

# Check for cleanup flag
if [[ "$1" == "cleanup" ]]; then
    cleanup_test_db
    exit 0
fi

# Install Podman if needed
setup_podman

# Setup TimescaleDB container
setup_timescaledb

# Check if virtual environment is activated
if [[ "$VIRTUAL_ENV" == "" ]]; then
    print_warning "Virtual environment not activated. Activating..."
    source .venv/bin/activate
fi

# Install test dependencies
print_status "Installing test dependencies..."
uv sync --dev
# uv pip install pytest-cov pytest-playwright playwright
playwright install chromium

# Set test environment
if [[ -f .env.test ]]; then
    export $(cat .env.test | xargs)
fi

# Run database setup
print_status "Setting up test database schema..."
psql "$TEST_DATABASE_URL" -f ../common/timescaledb_schema.sql

# Run tests based on arguments
if [[ "$2" == "unit" || ("$1" == "unit" && "$2" == "") ]]; then
    print_status "Running unit tests..."
    pytest tests/unit -v -m "unit"
elif [[ "$2" == "integration" || ("$1" == "integration" && "$2" == "") ]]; then
    print_status "Running integration tests..."
    pytest tests/integration -v -m "integration"
elif [[ "$2" == "e2e" || ("$1" == "e2e" && "$2" == "") ]]; then
    print_status "Running end-to-end tests..."
    pytest tests/e2e -v -m "e2e"
elif [[ "$2" == "quick" || ("$1" == "quick" && "$2" == "") ]]; then
    print_status "Running quick tests (unit only)..."
    pytest tests/unit -v -m "unit and not slow"
elif [[ "$2" == "coverage" || ("$1" == "coverage" && "$2" == "") ]]; then
    print_status "Running all tests with coverage..."
    pytest tests/ -v --cov=main --cov-report=html --cov-report=term-missing
else
    if [[ "$1" != "" && "$1" != "cleanup" ]]; then
        print_warning "Unknown test type: $1. Running all tests..."
    fi
    print_status "Running all tests..."
    pytest -v
fi

print_status "Test suite completed!"
