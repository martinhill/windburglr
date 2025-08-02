#!/bin/bash

# Load environment variables if .env file exists
if [ -f .env ]; then
    export $(cat .env | xargs)
fi

# Start the FastAPI application
fastapi dev main.py
# uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --reload
