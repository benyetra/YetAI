#!/usr/bin/env python3

import sys

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

from app.core.database import SessionLocal
from app.models.database_models import Bet, ParlayBet
from sqlalchemy import and_

db = SessionLocal()
try:
    # Get all pending individual bets
    pending_bets = (
        db.query(Bet)
        .filter(and_(Bet.status == "PENDING", Bet.parlay_id.is_(None)))
        .all()
    )

    print(f"=== PENDING INDIVIDUAL BETS ({len(pending_bets)}) ===")
    for bet in pending_bets:
        print(f"Bet ID: {bet.id}")
        print(f"  Game ID: {bet.game_id}")
        print(f"  Sport: {bet.sport}")
        print(f"  Teams: {bet.away_team} @ {bet.home_team}")
        print(f"  Selection: {bet.selection}")
        print(f"  Type: {bet.bet_type}")
        print(f"  Amount: ${bet.amount}")
        print(f"  Placed: {bet.placed_at}")
        print()

    # Get all pending parlays
    pending_parlays = db.query(ParlayBet).filter(ParlayBet.status == "PENDING").all()
    print(f"=== PENDING PARLAYS ({len(pending_parlays)}) ===")
    for parlay in pending_parlays:
        print(f"Parlay ID: {parlay.id}")
        print(f"  Legs: {parlay.leg_count}")
        print(f"  Amount: ${parlay.amount}")
        print(f"  Placed: {parlay.placed_at}")

        # Get parlay legs
        legs = db.query(Bet).filter(Bet.parlay_id == parlay.id).all()
        for i, leg in enumerate(legs):
            print(
                f"    Leg {i+1}: {leg.selection} (Game: {leg.game_id}, Sport: {leg.sport})"
            )
        print()

finally:
    db.close()
