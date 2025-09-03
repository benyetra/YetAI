#!/usr/bin/env python3
"""
Test the simplified trade analyzer functionality directly
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db
from app.models.database_models import SleeperLeague, SleeperRoster, SleeperPlayer

def test_simple_standings():
    """Test getting standings using Sleeper data directly"""
    db = next(get_db())
    
    try:
        league_id = "1257417114529054720"  # 2025 league
        print(f"🔍 Testing standings for league {league_id}...")
        
        # Find the Sleeper league
        sleeper_league = db.query(SleeperLeague).filter(
            SleeperLeague.sleeper_league_id == league_id
        ).first()
        
        if not sleeper_league:
            print("❌ League not found")
            return False
            
        print(f"✅ Found league: {sleeper_league.name} (season {sleeper_league.season})")
        
        # Get all rosters for this league
        rosters = db.query(SleeperRoster).filter(
            SleeperRoster.league_id == sleeper_league.id
        ).order_by(SleeperRoster.wins.desc(), SleeperRoster.points_for.desc()).all()
        
        print(f"📊 Found {len(rosters)} teams:")
        standings = []
        for i, roster in enumerate(rosters):
            team_data = {
                "rank": i + 1,
                "team_name": roster.team_name or f"Team {roster.sleeper_roster_id}",
                "owner_name": roster.owner_name or "Unknown",
                "wins": roster.wins,
                "losses": roster.losses,
                "points_for": roster.points_for,
                "points_against": roster.points_against,
            }
            standings.append(team_data)
            print(f"  {team_data['rank']}. {team_data['team_name']} ({team_data['wins']}-{team_data['losses']}) - {team_data['points_for']} pts")
        
        return standings
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return None
    finally:
        db.close()

def test_simple_team_analysis():
    """Test team analysis using Sleeper data directly"""
    db = next(get_db())
    
    try:
        print("🔍 Testing team analysis...")
        
        # Find any team with players (using Team 1 for testing)
        roster = db.query(SleeperRoster).filter(
            SleeperRoster.sleeper_roster_id == "1"
        ).first()
        
        if not roster or not roster.players:
            print("❌ Roster not found")
            return None
            
        print(f"✅ Found team: {roster.team_name} ({roster.wins}-{roster.losses})")
        print(f"   Players: {len(roster.players)}")
        print(f"   Starters: {len(roster.starters or [])}")
        
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
        
        print(f"📋 Roster breakdown:")
        starters_list = [p for p in players if p["is_starter"]]
        bench_list = [p for p in players if not p["is_starter"]]
        
        print(f"  Starters ({len(starters_list)}):")
        for player in starters_list:
            print(f"    {player['name']} ({player['position']}) - {player['team']}")
        
        print(f"  Bench ({len(bench_list)}):")
        for player in bench_list:
            print(f"    {player['name']} ({player['position']}) - {player['team']}")
        
        # Simple position analysis
        position_counts = {}
        for player in players:
            pos = player["position"]
            if pos not in position_counts:
                position_counts[pos] = {"total": 0, "starters": 0}
            position_counts[pos]["total"] += 1
            if player["is_starter"]:
                position_counts[pos]["starters"] += 1
        
        print(f"📊 Position breakdown:")
        for pos, counts in position_counts.items():
            print(f"  {pos}: {counts['starters']}/{counts['total']} (starters/total)")
        
        return {
            "team_info": {
                "team_name": roster.team_name,
                "record": f"{roster.wins}-{roster.losses}",
                "points_for": roster.points_for,
            },
            "players": players,
            "position_breakdown": position_counts
        }
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        db.close()

if __name__ == "__main__":
    print("🚀 Testing simplified trade analyzer endpoints...")
    
    print("\n" + "="*50)
    print("TEST 1: Standings")
    print("="*50)
    standings = test_simple_standings()
    
    print("\n" + "="*50)
    print("TEST 2: Team Analysis")
    print("="*50)
    analysis = test_simple_team_analysis()
    
    if standings and analysis:
        print("\n✅ All tests passed! The simplified endpoints should work.")
        print(f"   - Found {len(standings)} teams in standings")
        print(f"   - Found {len(analysis['players'])} players on user team")
        print(f"   - Team record: {analysis['team_info']['record']}")
    else:
        print("\n❌ Some tests failed")