# YetAI Sports Betting MVP - Backend Dockerfile
# Optimized for Railway deployment with dynamic PORT

FROM python:3.11-slim

# Set working directory + PYTHONPATH so `app.X` imports resolve from /app
# regardless of which CWD the runtime command happens to use. Railway's
# start-command override on the celery-worker service runs from /, not /app,
# which broke `celery -A app.celery_app` until this was set.
WORKDIR /app
ENV PYTHONPATH=/app
# pybaseball imports matplotlib.pyplot at import time; headless Railway images need Agg.
ENV MPLBACKEND=Agg

# Minimal apt footprint (Railway builders can run out of /var/cache/apt/archives space).
# gcc + libpq-dev for psycopg2; curl for HEALTHCHECK. No g++ (wheels are prebuilt).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libc6-dev \
        libpq-dev \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /tmp/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies (single layer; --no-cache-dir avoids doubling disk use).
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir nfl-data-py==0.3.3 --no-deps \
    && pip install --no-cache-dir appdirs fastparquet \
    && pip install --no-cache-dir boto3==1.35.0 botocore \
    && pip install --no-cache-dir google-auth==2.30.0 google-auth-oauthlib==1.2.0 \
    && python -c "import boto3, google.auth, statsapi, pybaseball, pyarrow"

# Copy application code
COPY . .

# Celery worker entrypoint: Railway may use backend/ or repo-root build context.
# Normalize to /app/scripts/railway-celery.sh so start-command overrides stay consistent.
RUN mkdir -p /app/scripts && \
    if [ ! -f /app/scripts/railway-celery.sh ] && [ -f /app/backend/scripts/railway-celery.sh ]; then \
      cp /app/backend/scripts/railway-celery.sh /app/scripts/railway-celery.sh; \
    fi && \
    if [ -f /app/scripts/railway-celery.sh ]; then chmod +x /app/scripts/railway-celery.sh; fi

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
