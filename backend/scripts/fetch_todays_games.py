#!/usr/bin/env python3
"""
Simple script to fetch today's games from Odds API and store in database.
This bypasses the service layer and directly makes API calls.

Usage:
    cd backend
    .venv/bin/python3 scripts/fetch_todays_games.py
"""

import sys
import os
import json
from datetime import datetime, timedelta

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.models.database_models import Game, GameStatus
from app.core.config import settings
from app.services.espn_api_service import espn_api_service
import requests


def fetch_and_store_games():
    """Fetch games from Odds API and store in database"""

    print("=" * 60)
    print("Fetch Today's Games Script")
    print("=" * 60)
    print()

    # Check if API key is configured
    if not settings.ODDS_API_KEY:
        print("❌ ERROR: ODDS_API_KEY not configured!")
        print("Please set your Odds API key in the .env file:")
        print("  ODDS_API_KEY=your_api_key_here")
        print()
        print("Get a free API key at: https://the-odds-api.com/")
        return

    print(f"✅ API key configured: {settings.ODDS_API_KEY[:8]}...")
    print()

    # Sports to fetch
    sports = [
        "americanfootball_nfl",
        "baseball_mlb",
        "basketball_nba",
        "icehockey_nhl",
    ]

    db = SessionLocal()
    total_created = 0
    total_updated = 0

    try:
        for sport in sports:
            print(f"🔄 Fetching {sport.upper()} games...")

            # Call Odds API
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
            params = {
                "apiKey": settings.ODDS_API_KEY,
                "regions": "us",
                "markets": "h2h,spreads,totals",
                "oddsFormat": "american",
            }

            try:
                response = requests.get(url, params=params, timeout=10)
                response.raise_for_status()
                games_data = response.json()

                print(f"  Found {len(games_data)} games")

                # Fetch broadcast info from ESPN for this sport
                print(f"  Fetching broadcast info from ESPN...")

                # Store each game in database
                for game_data in games_data:
                    game_id = game_data["id"]
                    home_team = game_data["home_team"]
                    away_team = game_data["away_team"]
                    commence_time = datetime.fromisoformat(
                        game_data["commence_time"].replace("Z", "+00:00")
                    )

                    # Try to get broadcast info from ESPN
                    broadcast_info = espn_api_service.extract_broadcast_info(
                        home_team=home_team,
                        away_team=away_team,
                        commence_time=commence_time,
                        sport_key=sport,
                    )

                    # Set is_nationally_televised based on broadcast info
                    is_national = False
                    if broadcast_info and broadcast_info.get("is_national"):
                        is_national = True

                    # Check if game exists
                    existing_game = db.query(Game).filter(Game.id == game_id).first()

                    if existing_game:
                        # Update existing game
                        existing_game.odds_data = game_data.get("bookmakers", [])
                        existing_game.broadcast_info = broadcast_info
                        existing_game.is_nationally_televised = is_national
                        existing_game.last_update = datetime.utcnow()
                        total_updated += 1
                    else:
                        # Create new game
                        new_game = Game(
                            id=game_id,
                            sport_key=game_data["sport_key"],
                            sport_title=game_data["sport_title"],
                            home_team=home_team,
                            away_team=away_team,
                            commence_time=commence_time,
                            status=GameStatus.SCHEDULED,
                            odds_data=game_data.get("bookmakers", []),
                            broadcast_info=broadcast_info,
                            is_nationally_televised=is_national,
                        )
                        db.add(new_game)
                        total_created += 1

                        network_str = ""
                        if broadcast_info and broadcast_info.get("networks"):
                            network_str = f" [{', '.join(broadcast_info['networks'])}]"
                        print(f"    ✅ {away_team} @ {home_team}{network_str}")

                db.commit()

            except requests.exceptions.RequestException as e:
                print(f"  ❌ Error fetching {sport}: {e}")
                continue

        print()
        print("=" * 60)
        print("Sync Results:")
        print("=" * 60)
        print(f"Total Created: {total_created}")
        print(f"Total Updated: {total_updated}")
        print(f"Total Games: {total_created + total_updated}")
        print()
        print("✅ Sync completed successfully!")

    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    fetch_and_store_games()
