#!/usr/bin/env python3
"""
Script to populate FantasyPlayer and FantasyRosterSpot data from SleeperRoster and SleeperPlayer data
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db
from app.models.database_models import SleeperPlayer, SleeperRoster
from app.models.fantasy_models import FantasyPlayer, FantasyRosterSpot, FantasyTeam
from sqlalchemy.orm import Session


def populate_fantasy_data():
    """Populate FantasyPlayer and FantasyRosterSpot from Sleeper data"""
    db = next(get_db())

    try:
        print("Populating FantasyPlayer table...")

        # Create FantasyPlayer records for all SleeperPlayers
        sleeper_players = db.query(SleeperPlayer).all()
        fantasy_players_created = 0

        for sleeper_player in sleeper_players:
            # Check if FantasyPlayer already exists
            existing_fp = (
                db.query(FantasyPlayer)
                .filter(
                    FantasyPlayer.platform_player_id == sleeper_player.sleeper_player_id
                )
                .first()
            )

            if not existing_fp:
                fantasy_player = FantasyPlayer(
                    platform="sleeper",
                    platform_player_id=sleeper_player.sleeper_player_id,
                    name=sleeper_player.full_name
                    or f"{sleeper_player.first_name or ''} {sleeper_player.last_name or ''}".strip(),
                    position=sleeper_player.position,
                    team=sleeper_player.team,
                    age=sleeper_player.age,
                )
                db.add(fantasy_player)
                fantasy_players_created += 1

                if fantasy_players_created % 50 == 0:
                    print(f"Created {fantasy_players_created} FantasyPlayer records...")

        db.commit()
        print(f"Created {fantasy_players_created} FantasyPlayer records")

        print("Populating FantasyRosterSpot table...")

        # Create FantasyRosterSpot records from SleeperRoster data
        roster_spots_created = 0

        # For each FantasyTeam, find corresponding SleeperRoster and create roster spots
        fantasy_teams = db.query(FantasyTeam).all()

        for fantasy_team in fantasy_teams:
            # Find corresponding SleeperRoster using platform_team_id
            sleeper_roster = (
                db.query(SleeperRoster)
                .filter(
                    SleeperRoster.sleeper_roster_id
                    == str(fantasy_team.platform_team_id)
                )
                .first()
            )

            if sleeper_roster and sleeper_roster.players:
                for player_id in sleeper_roster.players:
                    # Find corresponding FantasyPlayer
                    fantasy_player = (
                        db.query(FantasyPlayer)
                        .filter(FantasyPlayer.platform_player_id == player_id)
                        .first()
                    )

                    if fantasy_player:
                        # Check if roster spot already exists
                        existing_spot = (
                            db.query(FantasyRosterSpot)
                            .filter(
                                FantasyRosterSpot.team_id == fantasy_team.id,
                                FantasyRosterSpot.player_id == fantasy_player.id,
                            )
                            .first()
                        )

                        if not existing_spot:
                            roster_spot = FantasyRosterSpot(
                                team_id=fantasy_team.id,
                                player_id=fantasy_player.id,
                                position=fantasy_player.position,
                                week=8,  # Current week
                                is_starter=player_id in (sleeper_roster.starters or []),
                                points_scored=0.0,
                                projected_points=0.0,
                            )
                            db.add(roster_spot)
                            roster_spots_created += 1

                            if roster_spots_created % 50 == 0:
                                print(
                                    f"Created {roster_spots_created} FantasyRosterSpot records..."
                                )

        db.commit()
        print(f"Created {roster_spots_created} FantasyRosterSpot records")

        # Verify final counts
        total_fantasy_players = db.query(FantasyPlayer).count()
        total_roster_spots = db.query(FantasyRosterSpot).count()

        print(f"\nFinal counts:")
        print(f"  FantasyPlayer records: {total_fantasy_players}")
        print(f"  FantasyRosterSpot records: {total_roster_spots}")

        # Show sample team roster
        sample_team = db.query(FantasyTeam).first()
        if sample_team:
            roster_spots = (
                db.query(FantasyRosterSpot)
                .filter(FantasyRosterSpot.team_id == sample_team.id)
                .limit(5)
                .all()
            )

            print(f"\nSample roster for team '{sample_team.name}':")
            for spot in roster_spots:
                print(
                    f"  {spot.player.name} ({spot.position}) - Starter: {spot.is_starter}"
                )

    except Exception as e:
        print(f"Error populating fantasy data: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    populate_fantasy_data()
