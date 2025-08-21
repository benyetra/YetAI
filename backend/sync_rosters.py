#!/usr/bin/env python3
"""
Script to manually sync roster data from Sleeper API to populate FantasyRosterSpot records
"""
import asyncio
import aiohttp
import sys
import os

# Add the parent directory to Python path so we can import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.models.fantasy_models import FantasyLeague, FantasyTeam, FantasyPlayer, FantasyRosterSpot
from sqlalchemy.orm import Session
from sqlalchemy import and_

async def sync_league_rosters(league_platform_id: str):
    """Sync all rosters for a league from Sleeper API"""
    
    print(f"Starting roster sync for Sleeper league: {league_platform_id}")
    
    # Get database session
    db = SessionLocal()
    
    try:
        # Find the league in our database
        league = db.query(FantasyLeague).filter(
            FantasyLeague.platform_league_id == league_platform_id
        ).first()
        
        if not league:
            print(f"League {league_platform_id} not found in database!")
            return
        
        print(f"Found league in database: ID {league.id}, Name: {league.name}")
        
        # Get teams for this league
        teams = db.query(FantasyTeam).filter(FantasyTeam.league_id == league.id).all()
        print(f"Found {len(teams)} teams in database")
        
        # Clear existing roster spots for this league
        print("Clearing existing roster spots...")
        for team in teams:
            db.query(FantasyRosterSpot).filter(FantasyRosterSpot.team_id == team.id).delete()
        db.commit()
        
        # Get rosters from Sleeper API
        async with aiohttp.ClientSession() as session:
            print(f"Fetching rosters from Sleeper API...")
            url = f"https://api.sleeper.app/v1/league/{league_platform_id}/rosters"
            
            async with session.get(url) as response:
                if response.status != 200:
                    print(f"Failed to fetch rosters: HTTP {response.status}")
                    return
                
                rosters_data = await response.json()
                print(f"Retrieved {len(rosters_data)} rosters from Sleeper")
                
                # Process each roster
                for roster_data in rosters_data:
                    roster_id = roster_data.get('roster_id')
                    owner_id = roster_data.get('owner_id')
                    players = roster_data.get('players', [])
                    
                    print(f"Processing roster {roster_id} with {len(players)} players")
                    
                    # Find the corresponding team in our database
                    team = db.query(FantasyTeam).filter(
                        and_(
                            FantasyTeam.league_id == league.id,
                            FantasyTeam.platform_team_id == str(roster_id)
                        )
                    ).first()
                    
                    if not team:
                        print(f"  Team not found for roster_id {roster_id}")
                        continue
                    
                    print(f"  Found team: {team.name} (ID: {team.id})")
                    
                    # Process each player in the roster
                    for player_sleeper_id in players:
                        # Find or create the player in our database
                        player = db.query(FantasyPlayer).filter(
                            FantasyPlayer.platform_player_id == player_sleeper_id
                        ).first()
                        
                        if not player:
                            print(f"    Player {player_sleeper_id} not found in database, skipping")
                            continue
                        
                        # Create roster spot
                        roster_spot = FantasyRosterSpot(
                            team_id=team.id,
                            player_id=player.id,
                            position=player.position,
                            week=1,  # Current week
                            is_starter=True,  # We'll assume all are starters for now
                            points_scored=0.0,
                            projected_points=0.0
                        )
                        
                        db.add(roster_spot)
                    
                    print(f"  Added {len(players)} roster spots for {team.name}")
                
                # Commit all changes
                db.commit()
                print("Successfully synced all rosters!")
                
                # Show summary
                total_roster_spots = db.query(FantasyRosterSpot).join(FantasyTeam).filter(
                    FantasyTeam.league_id == league.id
                ).count()
                print(f"Total roster spots created: {total_roster_spots}")
                
    except Exception as e:
        print(f"Error syncing rosters: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    # Sync the known league
    league_id = "1257417114529054720"
    asyncio.run(sync_league_rosters(league_id))