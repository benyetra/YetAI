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

# Cache buster: 2025-01-12-v1
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
    echo "=== google-auth successfully installed ==="

# Copy application code
COPY . .

# Make the celery-worker entrypoint executable. Railway calls this from the
# celery-worker service's start command — it forces cd /app before celery
# runs so module imports work regardless of how Railway invokes the command.
RUN chmod +x /app/start_celery_worker.sh

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port (Railway will set PORT env var)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Use shell form to allow environment variable expansion
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
