#!/bin/sh
# Startup script for Railway deployment
# Handles PORT environment variable properly

# Use Railway's PORT or default to 8000
PORT=${PORT:-8000}

echo "Starting uvicorn on port $PORT"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1
