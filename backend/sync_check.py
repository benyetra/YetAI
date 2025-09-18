#!/usr/bin/env python3

import sys
import os
import asyncio
from sqlalchemy import text, create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append('/app')

async def sync_status():
    # Use production DATABASE_URL
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print("❌ No DATABASE_URL found")
        return

    engine = create_engine(db_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        query = """
        SELECT DISTINCT
            b.id, b.user_id, b.status, bh.new_status, bh.amount, bh.timestamp
        FROM bets b
        JOIN bet_history bh ON b.id = bh.bet_id
        WHERE b.status = 'PENDING'
        AND bh.action = 'settled'
        AND bh.new_status IN ('won', 'lost', 'cancelled')
        """
        result = db.execute(text(query))
        mismatched = result.fetchall()

        print(f"🔍 Found {len(mismatched)} mismatched bets:")
        for bet in mismatched:
            bet_id = bet[0]
            print(f"  - {bet_id[:8]}... status: {bet[2]} -> {bet[3]}")

        if len(mismatched) > 0:
            print("✨ Use the admin endpoint /api/admin/bets/sync-status to fix these!")
        else:
            print("✅ No mismatched bets found!")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(sync_status())