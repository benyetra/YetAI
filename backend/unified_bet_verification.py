#!/usr/bin/env python3
"""
Quick Unified Bet Verification Script
Verifies pending bets in the simple_unified_bets table
"""

import sys
import os
from datetime import datetime

# Add the backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.simple_unified_bet_model import SimpleUnifiedBet
from app.models.database_models import BetStatus
from sqlalchemy import text
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def verify_pending_bets():
    """Manually verify and settle completed bets"""
    db = SessionLocal()
    try:
        # Get all pending bets
        pending_bets = (
            db.query(SimpleUnifiedBet)
            .filter(SimpleUnifiedBet.status == BetStatus.PENDING)
            .all()
        )

        logger.info(f"Found {len(pending_bets)} pending bets to check")

        if not pending_bets:
            logger.info("No pending bets found")
            return

        # For now, let's just show what games these bets are for
        for bet in pending_bets:
            logger.info(
                f"Bet {bet.id[:8]}: {bet.selection} ({bet.sport}) - {bet.home_team} vs {bet.away_team}"
            )

            # Check if game commenced time has passed (simple completion check)
            if bet.commence_time and bet.commence_time < datetime.now():
                logger.info(f"  Game has started/completed at {bet.commence_time}")
            else:
                logger.info(f"  Game hasn't started yet: {bet.commence_time}")

        logger.info(
            "Manual verification needed - automatic settlement requires game score lookup"
        )

    finally:
        db.close()


if __name__ == "__main__":
    verify_pending_bets()
