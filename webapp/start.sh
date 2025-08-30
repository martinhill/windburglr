#!/bin/bash

# Use Poetry to run the application with proper environment
# This ensures all Poetry-managed dependencies are available

# Load environment variables if .env file exists
if [ -f .env ]; then
    export $(sed 's/#.*$//' .env | xargs)
fi

# Start the FastAPI application using Poetry
poetry run fastapi dev main.py --host 0.0.0.0 --port ${PORT:-8000}
