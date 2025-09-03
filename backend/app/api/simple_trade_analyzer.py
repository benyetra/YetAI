"""
Simplified trade analyzer API that works directly with Sleeper data
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.models.database_models import User, SleeperLeague, SleeperRoster, SleeperPlayer
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/standings/{league_id}")
async def get_standings(
    league_id: str,
    current_user: User = Depends(lambda: None),  # Simplified for now
    db: Session = Depends(get_db)
):
    """Get league standings using Sleeper data directly"""
    try:
        # Find the Sleeper league
        sleeper_league = db.query(SleeperLeague).filter(
            SleeperLeague.sleeper_league_id == league_id
        ).first()
        
        if not sleeper_league:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="League not found"
            )
        
        # Get all rosters for this league
        rosters = db.query(SleeperRoster).filter(
            SleeperRoster.league_id == sleeper_league.id
        ).order_by(SleeperRoster.wins.desc(), SleeperRoster.points_for.desc()).all()
        
        standings = []
        for i, roster in enumerate(rosters):
            standings.append({
                "rank": i + 1,
                "team_name": roster.team_name or f"Team {roster.sleeper_roster_id}",
                "owner_name": roster.owner_name or "Unknown",
                "wins": roster.wins,
                "losses": roster.losses,
                "ties": roster.ties,
                "points_for": roster.points_for,
                "points_against": roster.points_against,
                "win_percentage": roster.wins / (roster.wins + roster.losses + roster.ties) if (roster.wins + roster.losses + roster.ties) > 0 else 0
            })
        
        return {
            "success": True,
            "league_name": sleeper_league.name,
            "season": sleeper_league.season,
            "standings": standings
        }
        
    except Exception as e:
        logger.error(f"Error getting standings: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get standings"
        )

@router.get("/team-analysis/{roster_id}")
async def get_team_analysis(
    roster_id: str,
    current_user: User = Depends(lambda: None),  # Simplified for now  
    db: Session = Depends(get_db)
):
    """Get team analysis using Sleeper data directly"""
    try:
        # Find the roster
        roster = db.query(SleeperRoster).filter(
            SleeperRoster.sleeper_roster_id == roster_id
        ).first()
        
        if not roster or not roster.players:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Roster not found"
            )
        
        # Get player details
        players = []
        starters = roster.starters or []
        
        for player_id in roster.players:
            sleeper_player = db.query(SleeperPlayer).filter(
                SleeperPlayer.sleeper_player_id == str(player_id)
            ).first()
            
            if sleeper_player:
                name = sleeper_player.full_name or f"{sleeper_player.first_name or ''} {sleeper_player.last_name or ''}".strip()
                if not name or name.isspace():
                    name = f"Player {player_id}"
                
                players.append({
                    "id": player_id,
                    "name": name,
                    "position": sleeper_player.position,
                    "team": sleeper_player.team,
                    "is_starter": player_id in starters
                })
        
        # Simple position analysis
        position_counts = {}
        for player in players:
            pos = player["position"]
            if pos not in position_counts:
                position_counts[pos] = {"total": 0, "starters": 0}
            position_counts[pos]["total"] += 1
            if player["is_starter"]:
                position_counts[pos]["starters"] += 1
        
        # Identify expendable players (simplified logic)
        expendable_players = []
        valuable_players = []
        
        for player in players:
            if not player["is_starter"] and player["position"] in ["RB", "WR", "TE"]:
                expendable_players.append({
                    "name": player["name"],
                    "position": player["position"],
                    "trade_value": 15.0  # Simplified trade value
                })
            elif player["is_starter"]:
                valuable_players.append({
                    "name": player["name"],
                    "position": player["position"],
                    "trade_value": 25.0  # Simplified trade value
                })
        
        return {
            "success": True,
            "team_analysis": {
                "team_info": {
                    "team_name": roster.team_name or f"Team {roster.sleeper_roster_id}",
                    "owner_name": roster.owner_name or "Unknown",
                    "record": f"{roster.wins}-{roster.losses}-{roster.ties}",
                    "points_for": roster.points_for,
                    "points_against": roster.points_against
                },
                "roster_construction": {
                    "total_players": len(players),
                    "starters": len(starters),
                    "bench_players": len(players) - len(starters),
                    "position_breakdown": position_counts
                },
                "tradeable_players": {
                    "expendable": expendable_players,
                    "valuable": valuable_players
                },
                "team_needs": {
                    "primary_needs": ["Depth analysis available in full version"],
                    "secondary_needs": ["Upgrade opportunities identified"]
                }
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting team analysis: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get team analysis"
        )