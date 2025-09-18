#!/usr/bin/env python3

import sys
import asyncio

sys.path.append("/Users/byetz/Development/YetAI/ai-sports-betting-mvp/backend")

from app.services.game_sync_service import game_sync_service


async def manual_sync_games():
    print("🔄 Manual Game Sync...")
    print("This will sync recent game scores from the Odds API")

    try:
        result = await game_sync_service.sync_game_scores(days_back=3)

        print("\nResults:")
        print(f"  - Success: {result.get('success', False)}")
        print(f"  - Message: {result.get('message', 'No message')}")
        print(f"  - Games Updated: {result.get('games_updated', 0)}")
        print(f"  - Games Added: {result.get('games_added', 0)}")

        if "error" in result:
            print(f"  - Error: {result['error']}")

    except Exception as e:
        print(f"Error: {e}")

    print("\n✅ Manual sync complete!")


if __name__ == "__main__":
    asyncio.run(manual_sync_games())
