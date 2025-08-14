#!/bin/bash
echo "🗄️  Setting up PostgreSQL database..."

# Check if PostgreSQL is running
if ! pg_isready -q; then
    echo "❌ PostgreSQL is not running. Please start it first:"
    echo "   macOS: brew services start postgresql"
    echo "   Linux: sudo systemctl start postgresql"
    exit 1
fi

# Create user and database
echo "Creating database user and database..."
sudo -u postgres psql << 'EOSQL'
CREATE USER sports_user WITH PASSWORD 'sports_pass';
CREATE DATABASE sports_betting_ai OWNER sports_user;
GRANT ALL PRIVILEGES ON DATABASE sports_betting_ai TO sports_user;
\q
EOSQL

# Run schema
echo "Running database schema..."
PGPASSWORD=sports_pass psql -h localhost -U sports_user -d sports_betting_ai -f schema.sql

echo "✅ Database setup complete!"
echo "   Database: sports_betting_ai"
echo "   User: sports_user"
echo "   Password: sports_pass"