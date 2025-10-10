# YetAI Sports Betting MVP - Backend Dockerfile
# Optimized for Railway deployment

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including curl for health check
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Create non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check - Railway handles healthchecks, so we disable Docker's
# HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
#     CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Run the application using startup script
CMD ["./start.sh"]