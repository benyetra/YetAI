"""
Sync script to populate FantasyPlayer table from SleeperPlayer data
"""
import sys
import os
sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.database_models import SleeperPlayer
from app.models.fantasy_models import FantasyPlayer, FantasyPosition, FantasyPlatform, PlayerStatus
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def sync_sleeper_to_fantasy_players():
    """Sync SleeperPlayer data to FantasyPlayer table"""
    
    db = SessionLocal()
    
    try:
        # Get all sleeper players
        sleeper_players = db.query(SleeperPlayer).filter(
            SleeperPlayer.position.in_(['QB', 'RB', 'WR', 'TE'])
        ).all()
        
        logger.info(f"Found {len(sleeper_players)} sleeper players to sync")
        
        synced_count = 0
        
        for sleeper_player in sleeper_players:
            # Check if fantasy player already exists
            existing = db.query(FantasyPlayer).filter(
                FantasyPlayer.platform_player_id == sleeper_player.sleeper_player_id
            ).first()
            
            if existing:
                continue  # Skip if already exists
            
            # Map position to enum
            try:
                position_enum = FantasyPosition(sleeper_player.position)
            except ValueError:
                logger.warning(f"Unknown position {sleeper_player.position} for player {sleeper_player.full_name}")
                continue
            
            # Map status 
            try:
                if sleeper_player.status == 'Active':
                    status_enum = PlayerStatus.ACTIVE
                elif sleeper_player.injury_status:
                    if 'Out' in sleeper_player.injury_status:
                        status_enum = PlayerStatus.OUT
                    elif 'Questionable' in sleeper_player.injury_status:
                        status_enum = PlayerStatus.QUESTIONABLE
                    elif 'Doubtful' in sleeper_player.injury_status:
                        status_enum = PlayerStatus.DOUBTFUL
                    else:
                        status_enum = PlayerStatus.ACTIVE
                else:
                    status_enum = PlayerStatus.ACTIVE
            except:
                status_enum = PlayerStatus.ACTIVE
            
            # Create FantasyPlayer record
            fantasy_player = FantasyPlayer(
                platform=FantasyPlatform.SLEEPER,
                platform_player_id=sleeper_player.sleeper_player_id,
                name=sleeper_player.full_name,
                position=position_enum,
                team=sleeper_player.team or 'FA',
                jersey_number=None,  # Not available in sleeper data
                age=sleeper_player.age,
                height=sleeper_player.height,
                weight=sleeper_player.weight,
                college=sleeper_player.college,
                experience=sleeper_player.years_exp,
                status=status_enum,
                injury_description=sleeper_player.injury_status,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            db.add(fantasy_player)
            synced_count += 1
            
            # Commit in batches
            if synced_count % 50 == 0:
                db.commit()
                logger.info(f"Synced {synced_count} players...")
        
        # Final commit
        db.commit()
        logger.info(f"Successfully synced {synced_count} players from Sleeper to FantasyPlayer table")
        
        return synced_count
        
    except Exception as e:
        logger.error(f"Error syncing players: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    synced = sync_sleeper_to_fantasy_players()
    print(f"Synced {synced} players")