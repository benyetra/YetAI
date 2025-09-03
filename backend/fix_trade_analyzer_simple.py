#!/usr/bin/env python3
"""
Quick fix for trade analyzer by updating existing APIs to work correctly
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.database import get_db
from app.models.database_models import User
from app.models.fantasy_models import FantasyTeam, FantasyLeague

def fix_trade_analyzer():
    """Fix the trade analyzer by ensuring proper league ownership"""
    db = next(get_db())
    
    try:
        print("🔧 Fixing trade analyzer...")
        
        # Find the correct user and league
        user = db.query(User).filter(User.email == "byetra@gmail.com").first()
        if not user:
            print("❌ User not found")
            return False
            
        print(f"Found user: {user.email} (ID: {user.id})")
        
        # Find the 2025 league that should belong to this user
        league_2025 = db.query(FantasyLeague).filter(
            FantasyLeague.season == 2025,
            FantasyLeague.platform_league_id == "1257417114529054720"
        ).first()
        
        if not league_2025:
            print("❌ 2025 league not found")
            return False
            
        print(f"Found 2025 league: {league_2025.name} (ID: {league_2025.id})")
        
        # Update league ownership to point to the correct user
        league_2025.fantasy_user_id = 3  # FantasyUser 3 belongs to User 8 (byetra@gmail.com)
        
        # Make sure the team is in the right league and marked as user team
        team = db.query(FantasyTeam).filter(FantasyTeam.name == "Sir Spanks-A-LOT").first()
        if team:
            team.league_id = league_2025.id
            team.is_user_team = True
            print(f"Updated team: {team.name} -> League {league_2025.id}")
        
        db.commit()
        print("✅ Fixed trade analyzer configuration")
        
        # Verify the fix
        print("\n🔍 Verification:")
        print(f"  League {league_2025.id} belongs to FantasyUser {league_2025.fantasy_user_id}")
        print(f"  Team {team.id} is in League {team.league_id}")
        print(f"  Team is_user_team: {team.is_user_team}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    if fix_trade_analyzer():
        print("\n🚀 Trade analyzer should now work!")
        print("Try refreshing the page and testing:")
        print("  - Standings")
        print("  - Trade analyzer") 
        print("  - Player names should show correctly")
    else:
        print("\n❌ Fix failed")