#!/usr/bin/env python3
"""
Fix Production Bet Status Sync Issue

This script fixes the issue where bet_history has settlement records
but the main bets table still shows PENDING status.
"""

import sys
import asyncio
from sqlalchemy import text

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

from app.core.database import SessionLocal
from app.models.database_models import Bet, BetStatus


async def fix_bet_status_sync():
    """
    Find bets where bet_history shows 'settled' but bets table shows 'PENDING'
    and sync the status from bet_history to bets table
    """
    print("🔧 Fixing bet status sync issue...")

    db = SessionLocal()
    try:
        # Find all bets that are PENDING in bets table but have settlement
        # records in bet_history
        query = """
        SELECT DISTINCT
            b.id,
            b.user_id,
            b.status as current_status,
            bh.new_status as history_status,
            bh.amount as result_amount,
            bh.timestamp as settled_at
        FROM bets b
        JOIN bet_history bh ON b.id = bh.bet_id
        WHERE b.status = 'PENDING'
        AND bh.action = 'settled'
        AND bh.new_status IN ('won', 'lost', 'cancelled')
        ORDER BY bh.timestamp DESC
        """

        result = db.execute(text(query))
        mismatched_bets = result.fetchall()

        if not mismatched_bets:
            print("✅ No bet status mismatches found - all good!")
            return

        print(f"🔍 Found {len(mismatched_bets)} bets with status mismatches:")

        for bet_row in mismatched_bets:
            bet_id = bet_row[0]
            user_id = bet_row[1]
            current_status = bet_row[2]
            history_status = bet_row[3]
            result_amount = bet_row[4]
            settled_at = bet_row[5]

            print(
                f"  - Bet {bet_id[:8]}... (user {user_id}): "
                f"{current_status} → {history_status}"
            )

            # Update the bet record to match bet_history
            bet = db.query(Bet).filter(Bet.id == bet_id).first()
            if bet:
                # Map string status to enum
                if history_status.lower() == "won":
                    bet.status = BetStatus.WON
                elif history_status.lower() == "lost":
                    bet.status = BetStatus.LOST
                elif history_status.lower() == "cancelled":
                    bet.status = BetStatus.CANCELLED

                bet.result_amount = result_amount or 0
                bet.settled_at = settled_at

                print(f"    ✅ Updated bet {bet_id[:8]}... to {bet.status.value}")
            else:
                print(f"    ❌ Bet {bet_id[:8]}... not found in bets table")

        # Commit all changes
        db.commit()
        print(f"\n🎉 Successfully synced {len(mismatched_bets)} bet statuses!")

    except Exception as e:
        db.rollback()
        print(f"❌ Error fixing bet status sync: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(fix_bet_status_sync())
