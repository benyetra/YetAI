# YetAI Sports Betting MVP - Backend Dockerfile
# Optimized for Railway deployment with dynamic PORT

FROM python:3.11-slim

# Set working directory + PYTHONPATH so `app.X` imports resolve from /app
# regardless of which CWD the runtime command happens to use. Railway's
# start-command override on the celery-worker service runs from /, not /app,
# which broke `celery -A app.celery_app` until this was set.
WORKDIR /app
ENV PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Cache buster: 2026-05-19-mlb-statsapi
# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir boto3==1.35.0 botocore && \
    pip install --no-cache-dir google-auth==2.30.0 google-auth-oauthlib==1.2.0 && \
    echo "=== Verifying boto3 installation ===" && \
    pip show boto3 && \
    python -c "import boto3; print(f'boto3 version: {boto3.__version__}')" && \
    echo "=== boto3 successfully installed ===" && \
    echo "=== Verifying google-auth installation ===" && \
    pip show google-auth && \
    python -c "import google.auth; print('google-auth successfully imported')" && \
    echo "=== google-auth successfully installed ===" && \
    echo "=== Verifying MLB-StatsAPI (import statsapi) ===" && \
    pip show MLB-StatsAPI && \
    python -c "import statsapi; print('statsapi successfully imported')"

# Copy application code
COPY . .

# Worker entrypoint for Railway (start-command override may skip Dockerfile ENTRYPOINT)
RUN chmod +x /app/scripts/railway-celery.sh

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# ENTRYPOINT forces `cd /app` before any exec so module imports work regardless
# of where Railway's start-command override runs from. Shape: receives the
# CMD/override as args, cd's, then exec's them. Works for both:
#   - API service (default CMD below, shell-form → Docker wraps it as
#     ["/bin/sh", "-c", "uvicorn ..."] before passing to ENTRYPOINT)
#   - celery-worker service (Railway start-command override is wrapped by
#     Railway as sh -c too, same arg shape)
# This unblocks Development-7l5.
ENTRYPOINT ["/bin/bash", "-c", "cd /app && exec \"$@\"", "--"]

# Use shell form to allow environment variable expansion
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
