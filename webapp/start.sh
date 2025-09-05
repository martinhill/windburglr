#!/bin/bash
# Run a fastapi development server with live data

# Load environment variables if .env file exists
# This should be configured with read-only database credentials
# and optionally SENTRY_DSN + SENTRY_ENVIRONMENT
if [ -f .env ]; then
    export $(sed 's/#.*$//' .env | xargs)
fi

# Start the FastAPI application using Poetry
poetry run fastapi dev main.py --host 0.0.0.0 --port ${PORT:-8000}
