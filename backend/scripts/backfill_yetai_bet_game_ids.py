"""
Backfill game_id, home_team, and away_team for existing YetAI bets
This script matches YetAI bets to games in the database by parsing team names
"""

import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.models.database_models import YetAIBet, Game
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def backfill_yetai_bets():
    """Backfill game_id and team names for existing YetAI bets"""
    db = SessionLocal()

    try:
        # Get all YetAI bets without game_id
        bets_to_update = db.query(YetAIBet).filter(YetAIBet.game_id == None).all()

        logger.info(f"Found {len(bets_to_update)} YetAI bets without game_id")

        updated_count = 0
        not_found_count = 0

        for bet in bets_to_update:
            # Parse team names from title (format: "Away Team @ Home Team")
            if " @ " in bet.title:
                parts = bet.title.split(" @ ")
                if len(parts) == 2:
                    away_team = parts[0].strip()
                    home_team = parts[1].strip()

                    # Try to find the game in the database
                    # Only load essential fields to avoid schema issues
                    game = (
                        db.query(Game.id, Game.home_team, Game.away_team)
                        .filter(
                            Game.home_team.ilike(f"%{home_team}%"),
                            Game.away_team.ilike(f"%{away_team}%"),
                            Game.sport_title.ilike(f"%{bet.sport}%"),
                        )
                        .order_by(Game.commence_time.desc())
                        .first()
                    )

                    if game:
                        bet.game_id = game[0]  # game.id
                        bet.home_team = game[1]  # game.home_team
                        bet.away_team = game[2]  # game.away_team
                        updated_count += 1
                        logger.info(
                            f"Updated bet {bet.id[:8]}: {bet.title} -> game {game[0]}"
                        )
                    else:
                        not_found_count += 1
                        # Still set the parsed team names even if game not found
                        bet.home_team = home_team
                        bet.away_team = away_team
                        logger.warning(
                            f"Game not found for bet {bet.id[:8]}: {bet.title}"
                        )

        db.commit()
        logger.info(
            f"✅ Backfill complete: {updated_count} bets updated, {not_found_count} games not found"
        )

    except Exception as e:
        logger.error(f"Error during backfill: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    backfill_yetai_bets()
