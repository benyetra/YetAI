#!/usr/bin/env python3

import sys

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

import asyncio
from app.services.odds_api_service import OddsAPIService
from app.core.config import settings


async def test_api_calls():
    print("Testing The Odds API integration...")
    print(f"API Key configured: {'Yes' if settings.ODDS_API_KEY else 'No'}")

    if not settings.ODDS_API_KEY:
        print("❌ No API key found in settings!")
        return

    print(f"API Key (first 10 chars): {settings.ODDS_API_KEY[:10]}...")

    async with OddsAPIService(settings.ODDS_API_KEY) as api:
        # Test NFL scores (likely games from last night)
        print("\n🏈 Testing NFL scores...")
        try:
            nfl_scores = await api.get_scores("americanfootball_nfl", days_from=3)
            print(f"Found {len(nfl_scores)} NFL games")

            for i, score in enumerate(nfl_scores[:5]):
                print(f"  Game {i+1}:")
                print(f"    ID: {score.id}")
                print(f"    {score.away_team} @ {score.home_team}")
                print(f"    Score: {score.away_score} - {score.home_score}")
                print(f"    Completed: {score.completed}")
                print(f"    Commence: {score.commence_time}")

        except Exception as e:
            print(f"❌ NFL API error: {e}")

        # Test MLB scores (wait a bit to avoid rate limits)
        import time

        print("\n⚾ Testing MLB scores (waiting 2 seconds to avoid rate limit)...")
        time.sleep(2)
        try:
            mlb_scores = await api.get_scores("baseball_mlb", days_from=1)
            print(f"Found {len(mlb_scores)} MLB games")

            completed_mlb = [s for s in mlb_scores if s.completed]
            print(f"Completed MLB games: {len(completed_mlb)}")

            for i, score in enumerate(completed_mlb[:3]):
                print(f"  Game {i+1}:")
                print(f"    ID: {score.id}")
                print(f"    {score.away_team} @ {score.home_team}")
                print(f"    Score: {score.away_score} - {score.home_score}")
                print(f"    Completed: {score.completed}")
                print(f"    Commence: {score.commence_time}")

        except Exception as e:
            print(f"❌ MLB API error: {e}")

        print("\n(Skipping NBA to avoid rate limits)")


if __name__ == "__main__":
    asyncio.run(test_api_calls())
