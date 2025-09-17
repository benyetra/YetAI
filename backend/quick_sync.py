#!/usr/bin/env python3
"""
Quick sync script to get roster data working for Trade Analyzer
"""
import asyncio
import aiohttp
import sys
import os

# Add the parent directory to Python path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.fantasy_models import (
    FantasyPlayer,
    FantasyPlatform,
    FantasyPosition,
    FantasyRosterSpot,
    FantasyTeam,
    FantasyLeague,
)
from sqlalchemy.orm import Session
from sqlalchemy import and_


async def quick_sync_for_trade_analyzer():
    """Quick sync to get Trade Analyzer working"""

    print("Starting quick sync for Trade Analyzer...")

    # Get database session
    db = SessionLocal()

    try:
        # First, get the roster data directly from Sleeper API
        league_id = "1257417114529054720"

        async with aiohttp.ClientSession() as session:
            print(f"Fetching rosters from Sleeper league {league_id}...")
            rosters_url = f"https://api.sleeper.app/v1/league/{league_id}/rosters"

            async with session.get(rosters_url) as response:
                if response.status != 200:
                    print(f"Failed to fetch rosters: HTTP {response.status}")
                    return

                rosters_data = await response.json()
                print(f"Retrieved {len(rosters_data)} rosters")

                # Collect all unique player IDs
                all_player_ids = set()
                for roster in rosters_data:
                    players = roster.get("players", [])
                    all_player_ids.update(players)

                print(f"Found {len(all_player_ids)} unique players in rosters")

                # Get player details from Sleeper API
                print("Fetching player details from Sleeper API...")
                players_url = "https://api.sleeper.app/v1/players/nfl"

                async with session.get(players_url) as players_response:
                    if players_response.status != 200:
                        print("Failed to fetch player details")
                        return

                    all_players_data = await players_response.json()
                    print(f"Retrieved {len(all_players_data)} total NFL players")

                    # Add only the players that are in rosters
                    added_players = 0
                    for player_id in all_player_ids:
                        if player_id in all_players_data:
                            player_data = all_players_data[player_id]

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

                            if not existing_player:
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
                                added_players += 1

                    print(f"Added {added_players} new players")
                    db.commit()

                    # Now sync the rosters
                    print("Now syncing rosters...")

                    # Find the league in our database
                    league = (
                        db.query(FantasyLeague)
                        .filter(FantasyLeague.platform_league_id == league_id)
                        .first()
                    )

                    if not league:
                        print(f"League {league_id} not found in database!")
                        return

                    # Get teams for this league
                    teams = (
                        db.query(FantasyTeam)
                        .filter(FantasyTeam.league_id == league.id)
                        .all()
                    )
                    print(f"Found {len(teams)} teams in database")

                    # Clear existing roster spots
                    for team in teams:
                        db.query(FantasyRosterSpot).filter(
                            FantasyRosterSpot.team_id == team.id
                        ).delete()
                    db.commit()

                    # Sync rosters
                    total_roster_spots = 0
                    for roster_data in rosters_data:
                        roster_id = roster_data.get("roster_id")
                        players = roster_data.get("players", [])

                        # Find the corresponding team
                        team = (
                            db.query(FantasyTeam)
                            .filter(
                                and_(
                                    FantasyTeam.league_id == league.id,
                                    FantasyTeam.platform_team_id == str(roster_id),
                                )
                            )
                            .first()
                        )

                        if not team:
                            print(f"Team not found for roster_id {roster_id}")
                            continue

                        # Add roster spots for each player
                        for player_sleeper_id in players:
                            player = (
                                db.query(FantasyPlayer)
                                .filter(
                                    FantasyPlayer.platform_player_id
                                    == player_sleeper_id
                                )
                                .first()
                            )

                            if player:
                                roster_spot = FantasyRosterSpot(
                                    team_id=team.id,
                                    player_id=player.id,
                                    position=player.position,
                                    week=1,
                                    is_starter=True,
                                    points_scored=0.0,
                                    projected_points=0.0,
                                )
                                db.add(roster_spot)
                                total_roster_spots += 1

                    db.commit()
                    print(f"Successfully created {total_roster_spots} roster spots!")

                    # Verify the data
                    roster_count = (
                        db.query(FantasyRosterSpot)
                        .join(FantasyTeam)
                        .filter(FantasyTeam.league_id == league.id)
                        .count()
                    )
                    print(f"Total roster spots in league: {roster_count}")

    except Exception as e:
        print(f"Error in quick sync: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(quick_sync_for_trade_analyzer())
