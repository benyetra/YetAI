#!/usr/bin/env python3
"""
Script to populate SleeperPlayer table with data from Sleeper API
"""

import requests
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db
from app.models.database_models import SleeperPlayer, SleeperRoster
from sqlalchemy.orm import Session


def populate_sleeper_players():
    """Fetch and populate player data from Sleeper API"""
    db = next(get_db())

    print("Fetching player data from Sleeper API...")

    try:
        # Fetch all NFL players from Sleeper API
        response = requests.get("https://api.sleeper.app/v1/players/nfl")
        response.raise_for_status()
        players_data = response.json()

        print(f"Retrieved {len(players_data)} players from Sleeper API")

        # Get unique player IDs from our rosters
        roster_player_ids = set()
        rosters = db.query(SleeperRoster).all()
        for roster in rosters:
            if roster.players:
                roster_player_ids.update(roster.players)

        print(f"Found {len(roster_player_ids)} unique player IDs in our rosters")

        # Only insert players that are actually in our rosters
        players_inserted = 0
        for player_id, player_data in players_data.items():
            if player_id in roster_player_ids:
                # Check if player already exists
                existing_player = (
                    db.query(SleeperPlayer)
                    .filter(SleeperPlayer.sleeper_player_id == player_id)
                    .first()
                )

                if not existing_player:
                    # Helper function to safely convert to int
                    def safe_int(value):
                        if value is None:
                            return None
                        try:
                            return int(value)
                        except (ValueError, TypeError):
                            return None

                    # Create new player record
                    sleeper_player = SleeperPlayer(
                        sleeper_player_id=player_id,
                        first_name=player_data.get("first_name"),
                        last_name=player_data.get("last_name"),
                        full_name=player_data.get("full_name"),
                        position=player_data.get("position"),
                        team=player_data.get("team"),
                        age=safe_int(player_data.get("age")),
                        height=player_data.get("height"),
                        weight=player_data.get("weight"),
                        years_exp=safe_int(player_data.get("years_exp")),
                        college=player_data.get("college"),
                        fantasy_positions=player_data.get("fantasy_positions", []),
                        status=player_data.get("status"),
                        injury_status=player_data.get("injury_status"),
                        depth_chart_position=safe_int(
                            player_data.get("depth_chart_position")
                        ),
                        depth_chart_order=safe_int(
                            player_data.get("depth_chart_order")
                        ),
                        search_rank=safe_int(player_data.get("search_rank")),
                        hashtag=player_data.get("hashtag"),
                        espn_id=safe_int(player_data.get("espn_id")),
                        yahoo_id=safe_int(player_data.get("yahoo_id")),
                        fantasy_data_id=safe_int(player_data.get("fantasy_data_id")),
                        rotoworld_id=safe_int(player_data.get("rotoworld_id")),
                        rotowire_id=safe_int(player_data.get("rotowire_id")),
                        sportradar_id=player_data.get("sportradar_id"),
                        stats_id=safe_int(player_data.get("stats_id")),
                    )

                    db.add(sleeper_player)
                    players_inserted += 1

                    if players_inserted % 50 == 0:
                        print(f"Inserted {players_inserted} players...")

        # Commit all changes
        db.commit()
        print(f"Successfully inserted {players_inserted} players into the database!")

        # Verify insertion
        total_players = db.query(SleeperPlayer).count()
        print(f"Total SleeperPlayer records in database: {total_players}")

        # Show sample players
        sample_players = db.query(SleeperPlayer).limit(5).all()
        print("\nSample players:")
        for player in sample_players:
            name = (
                player.full_name
                or f"{player.first_name or ''} {player.last_name or ''}".strip()
            )
            print(
                f"  ID: {player.sleeper_player_id}, Name: {name}, Position: {player.position}, Team: {player.team}"
            )

    except Exception as e:
        print(f"Error populating players: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    populate_sleeper_players()
