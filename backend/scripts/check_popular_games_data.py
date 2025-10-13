#!/usr/bin/env python3
"""
Diagnostic script to check what data the popular_games endpoint will return.
Run this on your deployed server to verify the data is correct.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.database_models import Game
from datetime import datetime, timezone
import json


def check_popular_games_data():
    """Check what data will be returned by popular_games endpoint"""
    db = SessionLocal()

    try:
        # Get today's date range (same as popular_games endpoint)
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

        print("=" * 80)
        print("Popular Games Data Check")
        print("=" * 80)
        print(f"Current UTC time: {now}")
        print(f"Today range: {today_start} to {today_end}")
        print()

        # Query games (same as popular_games endpoint)
        games = (
            db.query(Game)
            .filter(
                Game.commence_time >= today_start,
                Game.commence_time <= today_end,
            )
            .order_by(Game.commence_time)
            .all()
        )

        print(f"Total games found for today: {len(games)}")
        print()

        if not games:
            print("⚠️  No games found for today!")
            print("   Run: python3 scripts/fetch_todays_games.py")
            return

        # Check first 5 games
        print("First 5 games that will be returned:")
        print("-" * 80)

        for i, game in enumerate(games[:5], 1):
            print(f"\n{i}. {game.away_team} @ {game.home_team}")
            print(f"   Sport: {game.sport_key}")
            print(f"   Time: {game.commence_time}")

            # Check odds_data
            has_odds = bool(
                game.odds_data and isinstance(game.odds_data, list) and game.odds_data
            )
            if has_odds:
                print(f"   ✅ Has odds: {len(game.odds_data)} bookmakers")
            else:
                print(f"   ❌ No odds data")

            # Check broadcast_info
            if game.broadcast_info:
                networks = game.broadcast_info.get("networks", [])
                print(
                    f"   ✅ Has broadcast: {networks} (National: {game.is_nationally_televised})"
                )
            else:
                print(f"   ⚠️  No broadcast info")

        print()
        print("=" * 80)
        print("Summary:")
        print("=" * 80)

        games_with_odds = sum(
            1
            for g in games
            if g.odds_data and isinstance(g.odds_data, list) and g.odds_data
        )
        games_with_broadcast = sum(1 for g in games if g.broadcast_info)

        print(f"Games with odds: {games_with_odds}/{len(games)}")
        print(f"Games with broadcast info: {games_with_broadcast}/{len(games)}")
        print()

        if games_with_odds < len(games):
            print("⚠️  Some games missing odds data!")
            print("   Run: python3 scripts/fetch_todays_games.py")
        else:
            print("✅ All games have odds data")

        if games_with_broadcast == 0:
            print("⚠️  No games have broadcast info!")
            print("   ESPN API may not have broadcast data for these games,")
            print("   or you need to run: python3 scripts/fetch_todays_games.py")
        else:
            print(
                f"✅ {games_with_broadcast} games have broadcast info (ESPN API working)"
            )

        print()
        print("=" * 80)
        print("Next Steps:")
        print("=" * 80)
        print("1. If data looks correct here but API returns empty:")
        print("   → Restart your backend server")
        print()
        print("2. If data is missing:")
        print("   → Run: python3 scripts/fetch_todays_games.py")
        print()
        print("3. To verify API endpoint directly:")
        print("   → curl http://localhost:8000/api/v1/popular-games")

    finally:
        db.close()


if __name__ == "__main__":
    check_popular_games_data()
