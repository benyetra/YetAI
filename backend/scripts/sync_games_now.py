#!/usr/bin/env python3
"""
Manual script to sync games from Odds API to database.
Run this to populate the database with today's games.

Usage:
    cd backend
    .venv/bin/python3 scripts/sync_games_now.py
"""

import asyncio
import sys
import os

# Add the backend directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.game_sync_service import game_sync_service
from app.core.config import settings


async def main():
    print("=" * 60)
    print("Manual Game Sync Script")
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

    # Check if service is available
    if not game_sync_service.is_available():
        print("❌ ERROR: Game sync service is not available")
        return

    print("🔄 Syncing upcoming games (next 7 days)...")
    print()

    # Sync upcoming games
    result = await game_sync_service.sync_upcoming_games(days_ahead=7)

    print()
    print("=" * 60)
    print("Sync Results:")
    print("=" * 60)
    print(f"Status: {result.get('status', 'unknown')}")
    print(f"Message: {result.get('message', 'No message')}")
    print(f"Total Updated: {result.get('total_updated', 0)}")
    print(f"Total Created: {result.get('total_created', 0)}")
    print(f"Sports Synced: {', '.join(result.get('sports_synced', []))}")
    print()

    if result.get("status") == "success":
        print("✅ Sync completed successfully!")
    else:
        print("❌ Sync failed!")
        if "error" in result:
            print(f"Error: {result['error']}")
        if result.get("status") == "skipped":
            print(f"Reason: {result.get('reason', 'unknown')}")


if __name__ == "__main__":
    asyncio.run(main())
