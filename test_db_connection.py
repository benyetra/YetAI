#!/usr/bin/env python3
"""
Quick test to verify database connection with Railway PostgreSQL
"""
import os
from sqlalchemy import create_engine, text

# Use Railway's DATABASE_URL format
DATABASE_URL = "postgresql://postgres:zLubiZyhJeBJFZDqxeTtYPfnvWmQtolA@postgres.railway.internal:5432/railway"

print("Testing database connection...")
print(f"DATABASE_URL: {DATABASE_URL[:50]}...")

try:
    # Create engine with Railway-specific settings
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=True  # Show SQL queries
    )
    
    # Test connection
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1 as test"))
        row = result.fetchone()
        print(f"✅ Database connection successful! Result: {row}")
        
        # Test if we can see tables
        result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
        tables = result.fetchall()
        print(f"📋 Found {len(tables)} tables: {[t[0] for t in tables]}")
        
except Exception as e:
    print(f"❌ Database connection failed: {e}")
    print(f"Error type: {type(e)}")