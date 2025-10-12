#!/bin/bash
# Script to run database migrations on Railway
# Usage: railway run bash scripts/run_migration.sh

set -e

echo "==================================="
echo "Running Database Migrations"
echo "==================================="

# Check if alembic is available
if ! command -v alembic &> /dev/null; then
    echo "ERROR: alembic not found. Installing..."
    pip install alembic
fi

# Check database connection
echo "Checking database connection..."
python -c "
from app.core.database import SessionLocal
try:
    db = SessionLocal()
    db.execute('SELECT 1')
    print('✓ Database connection successful')
    db.close()
except Exception as e:
    print(f'✗ Database connection failed: {e}')
    exit(1)
"

# Run migrations
echo ""
echo "Running alembic migrations..."
alembic upgrade head

echo ""
echo "==================================="
echo "Migration completed successfully!"
echo "==================================="
