#!/usr/bin/env python3

import sys
sys.path.append('/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend')

from app.core.database import SessionLocal
from app.models.database_models import Bet, BetStatus
from sqlalchemy import and_

db = SessionLocal()
try:
    # Get recently settled bets (our test bets)
    settled_bets = db.query(Bet).filter(
        and_(
            Bet.game_id.in_(['completed-nfl-1', 'completed-mlb-1', 'completed-nba-1']),
            Bet.status != BetStatus.PENDING
        )
    ).all()
    
    print(f'🎯 SETTLED TEST BETS ({len(settled_bets)})')
    for bet in settled_bets:
        outcome = '✅ WON' if bet.status == BetStatus.WON else ('❌ LOST' if bet.status == BetStatus.LOST else f'↔️ {bet.status.value.upper()}')
        print(f'{outcome}: {bet.selection} - ${bet.amount} → ${bet.result_amount or 0}')
        
finally:
    db.close()