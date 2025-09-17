#!/usr/bin/env python3
"""
Script to fix roster data with actual current roster
"""
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db
from app.models.database_models import SleeperPlayer
from app.models.fantasy_models import FantasyPlayer, FantasyRosterSpot, FantasyTeam
from sqlalchemy.orm import Session


def fix_roster_data():
    """Fix roster data with actual current players"""
    db = next(get_db())

    try:
        # Current actual roster based on user's input
        actual_roster = [
            {"name": "Jayden Daniels", "position": "QB", "team": "WAS"},
            {
                "name": "Brian Robinson Jr.",
                "position": "RB",
                "team": "ATL",
            },  # Listed as B Robinson
            {"name": "Isaiah Guerendo", "position": "RB", "team": "SF"},
            {
                "name": "Deebo Samuel",
                "position": "WR",
                "team": "WAS",
            },  # Listed as D Samuel
            {"name": "Mike Evans", "position": "WR", "team": "TB"},  # Listed as M Evans
            {
                "name": "Evan Engram",
                "position": "TE",
                "team": "DEN",
            },  # Listed as E Engram
            {"name": "Joe Mixon", "position": "RB", "team": "HOU"},  # Listed as J Mixon
            {
                "name": "Minnesota Vikings",
                "position": "DEF",
                "team": "MIN",
            },  # Listed as MIN DEF
            {"name": "Jared Goff", "position": "QB", "team": "DET"},  # Listed as J Goff
            {
                "name": "C.J. Stroud",
                "position": "QB",
                "team": "HOU",
            },  # Listed as C Stroud
            {
                "name": "Chuba Hubbard",
                "position": "RB",
                "team": "CAR",
            },  # Listed as C Hubbard
            {
                "name": "Jaylen Waddle",
                "position": "WR",
                "team": "MIA",
            },  # Listed as J Waddle
            {
                "name": "Chris Olave",
                "position": "WR",
                "team": "NO",
            },  # Listed as C Olave
            {"name": "Tank Dell", "position": "WR", "team": "HOU"},  # Listed as T Dell
        ]

        print("Updating roster data for Sir Spanks-A-LOT team...")

        # Get the team
        team = db.query(FantasyTeam).filter(FantasyTeam.id == 1).first()
        if not team:
            print("Team not found!")
            return

        # Clear existing roster spots
        existing_spots = (
            db.query(FantasyRosterSpot)
            .filter(FantasyRosterSpot.team_id == team.id)
            .all()
        )
        for spot in existing_spots:
            db.delete(spot)
        print(f"Cleared {len(existing_spots)} existing roster spots")

        # Add new roster spots with actual players
        added_count = 0
        for player_info in actual_roster:
            # Try to find existing FantasyPlayer by name
            fantasy_player = (
                db.query(FantasyPlayer)
                .filter(FantasyPlayer.name.ilike(f"%{player_info['name']}%"))
                .first()
            )

            if not fantasy_player:
                # Create new FantasyPlayer
                fantasy_player = FantasyPlayer(
                    platform="sleeper",
                    platform_player_id=f"manual_{player_info['name'].replace(' ', '_').lower()}",
                    name=player_info["name"],
                    position=player_info["position"],
                    team=player_info["team"],
                    age=None,
                )
                db.add(fantasy_player)
                db.flush()  # Get the ID
                print(f"Created new FantasyPlayer: {player_info['name']}")

            # Create roster spot
            roster_spot = FantasyRosterSpot(
                team_id=team.id,
                player_id=fantasy_player.id,
                position=player_info["position"],
                week=8,
                is_starter=True,  # Assume starters for now
                points_scored=0.0,
                projected_points=0.0,
            )
            db.add(roster_spot)
            added_count += 1

        db.commit()
        print(f"Added {added_count} new roster spots with actual current players")

        # Verify the update
        updated_spots = (
            db.query(FantasyRosterSpot)
            .filter(FantasyRosterSpot.team_id == team.id)
            .all()
        )
        print(f"\\nVerification - Team now has {len(updated_spots)} players:")
        for spot in updated_spots:
            print(f"  - {spot.player.name} ({spot.player.position})")

    except Exception as e:
        print(f"Error fixing roster data: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    fix_roster_data()
