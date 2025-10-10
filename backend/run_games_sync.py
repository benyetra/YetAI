#!/usr/bin/env python3
"""
Manual script to run games sync.
This populates the database with games from Odds API and marks nationally televised games.
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.services.games_sync_service import run_games_sync


async def main():
    print("Starting manual games sync...")
    try:
        stats = await run_games_sync()
        print("\n✅ Games sync completed successfully!")
        print(f"\nStatistics:")
        print(f"  Total games fetched: {stats['total_games_fetched']}")
        print(f"  Total games created: {stats['total_games_created']}")
        print(f"  Total games updated: {stats['total_games_updated']}")
        print(f"  Duration: {stats['duration_seconds']:.2f} seconds")

        if stats["errors"]:
            print(f"\n⚠️  Errors encountered:")
            for error in stats["errors"]:
                print(f"    - {error}")

        print(f"\nSports synced:")
        for sport, sport_stats in stats["sports_synced"].items():
            print(
                f"  {sport}: {sport_stats['games_fetched']} fetched, "
                f"{sport_stats['games_created']} created, "
                f"{sport_stats['games_updated']} updated"
            )

        return 0
    except Exception as e:
        print(f"\n❌ Games sync failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
