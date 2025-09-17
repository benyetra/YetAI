#!/usr/bin/env python3

import sys

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

from app.core.database import SessionLocal
from app.models.database_models import Bet, BetStatus, ParlayBet
from sqlalchemy import desc
from datetime import datetime, timedelta


def check_pending_bets():
    db = SessionLocal()
    try:
        # Get pending individual bets
        pending_bets = (
            db.query(Bet)
            .filter(Bet.status == BetStatus.PENDING, Bet.parlay_id.is_(None))
            .order_by(desc(Bet.placed_at))
            .all()
        )

        print(f"Found {len(pending_bets)} pending individual bets:")

        for bet in pending_bets[:10]:  # Show first 10
            print(f"  - Bet ID: {bet.id}")
            print(f"    Game ID: {bet.game_id}")
            print(f"    Selection: {bet.selection}")
            print(f"    Amount: ${bet.amount}")
            print(f"    Placed: {bet.placed_at}")
            print(f"    Sport: {bet.sport}")
            print(f"    Home: {bet.home_team} vs Away: {bet.away_team}")
            print(f"    Commence Time: {bet.commence_time}")
            print("---")

        # Get pending parlays
        pending_parlays = (
            db.query(ParlayBet)
            .filter(ParlayBet.status == BetStatus.PENDING)
            .order_by(desc(ParlayBet.placed_at))
            .all()
        )

        print(f"\nFound {len(pending_parlays)} pending parlays:")

        for parlay in pending_parlays[:5]:  # Show first 5
            print(f"  - Parlay ID: {parlay.id}")
            print(f"    Legs: {parlay.leg_count}")
            print(f"    Amount: ${parlay.amount}")
            print(f"    Placed: {parlay.placed_at}")

            # Get parlay legs
            legs = db.query(Bet).filter(Bet.parlay_id == parlay.id).all()
            for i, leg in enumerate(legs):
                print(f"      Leg {i+1}: {leg.selection} (Game: {leg.game_id})")
            print("---")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    check_pending_bets()
