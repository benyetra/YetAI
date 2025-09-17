#!/usr/bin/env python3
"""
Script to sync all NFL players from Sleeper API to populate FantasyPlayer records
"""
import asyncio
import aiohttp
import sys
import os

# Add the parent directory to Python path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.fantasy_models import FantasyPlayer, FantasyPlatform, FantasyPosition
from sqlalchemy.orm import Session


async def sync_all_nfl_players():
    """Sync all NFL players from Sleeper API"""

    print("Starting NFL players sync from Sleeper API...")

    # Get database session
    db = SessionLocal()

    try:
        # Get all NFL players from Sleeper API
        async with aiohttp.ClientSession() as session:
            print("Fetching all NFL players from Sleeper API...")
            url = "https://api.sleeper.app/v1/players/nfl"

            async with session.get(url) as response:
                if response.status != 200:
                    print(f"Failed to fetch players: HTTP {response.status}")
                    return

                players_data = await response.json()
                print(f"Retrieved {len(players_data)} players from Sleeper")

                # Process each player
                added_count = 0
                updated_count = 0

                for player_id, player_data in players_data.items():
                    # Skip players without names
                    if not player_data.get("first_name") and not player_data.get(
                        "last_name"
                    ):
                        continue

                    # Create player name
                    first_name = player_data.get("first_name", "")
                    last_name = player_data.get("last_name", "")
                    name = f"{first_name} {last_name}".strip()

                    if not name:
                        continue

                    # Map position
                    position_str = player_data.get("position", "BENCH")
                    try:
                        if position_str in ["QB", "RB", "WR", "TE", "K", "DEF"]:
                            position = getattr(FantasyPosition, position_str)
                        else:
                            position = FantasyPosition.BENCH
                    except:
                        position = FantasyPosition.BENCH

                    # Check if player exists
                    existing_player = (
                        db.query(FantasyPlayer)
                        .filter(FantasyPlayer.platform_player_id == player_id)
                        .first()
                    )

                    if existing_player:
                        # Update existing player
                        existing_player.name = name
                        existing_player.position = position
                        existing_player.team = player_data.get("team", "FA")
                        existing_player.jersey_number = player_data.get("number")
                        existing_player.age = player_data.get("age")
                        existing_player.height = player_data.get("height")
                        existing_player.weight = player_data.get("weight")
                        existing_player.college = player_data.get("college")
                        existing_player.experience = player_data.get("years_exp")
                        existing_player.status = player_data.get("status", "Active")
                        existing_player.injury_description = player_data.get(
                            "injury_status"
                        )
                        updated_count += 1
                    else:
                        # Create new player
                        new_player = FantasyPlayer(
                            platform=FantasyPlatform.SLEEPER,
                            platform_player_id=player_id,
                            name=name,
                            position=position,
                            team=player_data.get("team", "FA"),
                            jersey_number=player_data.get("number"),
                            age=player_data.get("age"),
                            height=player_data.get("height"),
                            weight=player_data.get("weight"),
                            college=player_data.get("college"),
                            experience=player_data.get("years_exp"),
                            status=player_data.get("status", "Active"),
                            injury_description=player_data.get("injury_status"),
                        )
                        db.add(new_player)
                        added_count += 1

                    # Commit every 100 players to avoid memory issues
                    if (added_count + updated_count) % 100 == 0:
                        db.commit()
                        print(f"Processed {added_count + updated_count} players...")

                # Final commit
                db.commit()
                print(f"Successfully synced all NFL players!")
                print(f"Added: {added_count} new players")
                print(f"Updated: {updated_count} existing players")
                print(f"Total processed: {added_count + updated_count}")

    except Exception as e:
        print(f"Error syncing players: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(sync_all_nfl_players())
