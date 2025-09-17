#!/usr/bin/env python3

import sys

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

import asyncio
from app.services.odds_api_service import OddsAPIService
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.database_models import Bet, ParlayBet
from datetime import datetime, timedelta


async def debug_game_id_mapping():
    print("🔍 Debugging Game ID Mapping Issue...")

    # Get all unique game IDs from pending bets
    db = SessionLocal()
    try:
        pending_bet_game_ids = (
            db.query(Bet.game_id)
            .filter(Bet.status == "PENDING", Bet.game_id.isnot(None))
            .distinct()
            .all()
        )

        game_ids_in_db = [row[0] for row in pending_bet_game_ids]
        print(f"\n📊 Game IDs in pending bets: {len(game_ids_in_db)}")
        for gid in game_ids_in_db:
            print(f"  - {gid}")
    finally:
        db.close()

    # Check if we can find ANY completed games in the API
    print(f"\n🔍 Looking for completed games in API...")

    async with OddsAPIService(settings.ODDS_API_KEY) as api:
        try:
            # Check recent scores (preseason games might be completed)
            print("Checking NFL preseason scores...")
            nfl_scores = await api.get_scores("americanfootball_nfl", days_from=3)

            completed_nfl = [s for s in nfl_scores if s.completed]
            print(f"Found {len(completed_nfl)} completed NFL games")

            for score in completed_nfl[:5]:
                print(f"  ✅ {score.away_team} @ {score.home_team}")
                print(f"     ID: {score.id}")
                print(f"     Score: {score.away_score} - {score.home_score}")
                print(f"     Date: {score.commence_time}")

            # Check if our database game IDs exist in the API results
            print(f"\n🔍 Checking if database game IDs match API results...")
            all_api_ids = [s.id for s in nfl_scores]

            for db_game_id in game_ids_in_db:
                if db_game_id in all_api_ids:
                    print(f"  ✅ MATCH: {db_game_id}")
                else:
                    print(f"  ❌ NO MATCH: {db_game_id}")

            # Look for similar team names
            print(f"\n🔍 Looking for team name matches...")
            for db_game_id in game_ids_in_db[:3]:  # Check first 3
                # Get bet details for this game ID
                db = SessionLocal()
                try:
                    bet = db.query(Bet).filter(Bet.game_id == db_game_id).first()
                    if bet and bet.home_team and bet.away_team:
                        print(f"\nDB Game {db_game_id}:")
                        print(f"  Teams: {bet.away_team} @ {bet.home_team}")

                        # Look for team name matches in API
                        for api_score in nfl_scores[:10]:
                            if (
                                bet.home_team.lower() in api_score.home_team.lower()
                                or bet.away_team.lower() in api_score.away_team.lower()
                            ):
                                print(
                                    f"  🎯 Potential match: {api_score.away_team} @ {api_score.home_team}"
                                )
                                print(f"     API ID: {api_score.id}")
                                print(f"     Completed: {api_score.completed}")
                                break
                finally:
                    db.close()

        except Exception as e:
            print(f"❌ API Error: {e}")


if __name__ == "__main__":
    asyncio.run(debug_game_id_mapping())
