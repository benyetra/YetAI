"""
Quick script to populate PlayerAnalytics with schema-compliant data
"""
import sys
import os
sys.path.append(os.getcwd())

from app.core.database import SessionLocal
from app.models.fantasy_models import FantasyPlayer, PlayerAnalytics
import random
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def populate_analytics():
    """Populate analytics with data that matches the exact schema"""
    
    db = SessionLocal()
    
    try:
        # Get all fantasy players
        players = db.query(FantasyPlayer).all()
        logger.info(f"Found {len(players)} fantasy players to populate analytics for")
        
        records_created = 0
        weeks = [8, 9, 10, 11, 12]
        season = 2024
        
        for player in players:
            for week in weeks:
                # Check if analytics already exist
                existing = db.query(PlayerAnalytics).filter(
                    PlayerAnalytics.player_id == player.id,
                    PlayerAnalytics.week == week,
                    PlayerAnalytics.season == season
                ).first()
                
                if existing:
                    continue
                
                # Create realistic data based on position
                position = player.position.value if hasattr(player.position, 'value') else str(player.position)
                
                # Base data for all positions
                analytics_data = {
                    'opponent': random.choice(['BUF', 'MIA', 'NE', 'NYJ', 'KC', 'LAC', 'DEN', 'LV']),
                    'game_date': None,
                    
                    # Snap data
                    'total_snaps': random.randint(25, 75) if position != 'QB' else random.randint(60, 78),
                    'offensive_snaps': random.randint(20, 70) if position != 'QB' else random.randint(55, 75),
                    'special_teams_snaps': random.randint(0, 15),
                    'snap_percentage': random.uniform(30.0, 95.0) if position != 'QB' else random.uniform(85.0, 98.0),
                    'snap_share_rank': random.randint(1, 12),
                    
                    # Target data
                    'targets': 0 if position == 'QB' else random.randint(0, 14),
                    'team_total_targets': random.randint(25, 45),
                    'target_share': 0.0 if position == 'QB' else random.uniform(0.05, 0.35),
                    'air_yards': 0 if position == 'QB' else random.randint(20, 280),
                    'air_yards_share': 0.0 if position == 'QB' else random.uniform(0.05, 0.4),
                    'average_depth_of_target': 0.0 if position == 'QB' else random.uniform(5.0, 18.0),
                    'target_separation': random.uniform(1.0, 4.5) if position in ['WR', 'TE'] else None,
                    
                    # Red zone
                    'red_zone_snaps': random.randint(3, 12),
                    'red_zone_targets': 0 if position == 'QB' else random.randint(0, 5),
                    'red_zone_carries': random.randint(0, 8) if position in ['QB', 'RB'] else 0,
                    'red_zone_touches': random.randint(0, 10) if position != 'TE' else random.randint(0, 5),
                    'red_zone_share': random.uniform(0.05, 0.4),
                    'red_zone_efficiency': random.uniform(0.4, 0.85),
                    
                    # Routes (WR/TE mainly)
                    'routes_run': 0 if position == 'QB' else random.randint(8, 52),
                    'route_participation': 0.0 if position == 'QB' else random.uniform(0.3, 0.95),
                    'slot_rate': random.uniform(0.1, 0.8) if position in ['WR', 'TE'] else random.uniform(0.0, 0.3),
                    'deep_target_rate': 0.0 if position == 'QB' else random.uniform(0.02, 0.3),
                    
                    # Rushing (RB mainly)
                    'carries': random.randint(8, 25) if position == 'RB' else random.randint(0, 3),
                    'rushing_yards': random.randint(30, 150) if position == 'RB' else random.randint(0, 25),
                    'goal_line_carries': random.randint(0, 4),
                    'carry_share': random.uniform(0.15, 0.7) if position == 'RB' else random.uniform(0.0, 0.1),
                    'yards_before_contact': random.uniform(1.0, 3.5) if position == 'RB' else None,
                    'yards_after_contact': random.uniform(1.5, 4.2) if position == 'RB' else None,
                    'broken_tackles': random.randint(0, 6) if position == 'RB' else random.randint(0, 2),
                    
                    # Receiving
                    'receptions': 0 if position == 'QB' else random.randint(0, 12),
                    'receiving_yards': 0 if position == 'QB' else random.randint(0, 180),
                    'yards_after_catch': random.randint(0, 80) if position != 'QB' else 0,
                    'yards_after_catch_per_reception': random.uniform(2.0, 8.5) if position != 'QB' else None,
                    'contested_catch_rate': random.uniform(0.3, 0.8) if position in ['WR', 'TE'] else None,
                    'drop_rate': random.uniform(0.02, 0.15) if position != 'QB' else None,
                    
                    # Team context
                    'team_pass_attempts': random.randint(28, 48),
                    'team_rush_attempts': random.randint(18, 38),
                    'team_red_zone_attempts': random.randint(2, 8),
                    'game_script': random.uniform(-15.0, 15.0),  # Positive = winning
                    'time_of_possession': random.uniform(25.0, 35.0),
                    
                    # Fantasy points
                    'ppr_points': random.uniform(4.0, 35.0) if position != 'QB' else random.uniform(15.0, 40.0),
                    'half_ppr_points': random.uniform(3.0, 32.0) if position != 'QB' else random.uniform(15.0, 40.0),
                    'standard_points': random.uniform(2.0, 28.0) if position != 'QB' else random.uniform(15.0, 40.0),
                    
                    # Efficiency
                    'points_per_snap': random.uniform(0.1, 0.6),
                    'points_per_target': 0.0 if position == 'QB' else random.uniform(1.0, 4.0),
                    'points_per_touch': random.uniform(0.8, 3.5),
                    
                    # Consistency
                    'boom_rate': random.uniform(0.1, 0.6),
                    'bust_rate': random.uniform(0.1, 0.5),
                    'weekly_variance': random.uniform(5.0, 18.0),
                    'floor_score': random.uniform(2.0, 15.0),
                    'ceiling_score': random.uniform(15.0, 45.0),
                    
                    # Injury
                    'injury_designation': random.choice([None, None, None, 'Questionable', 'Probable']),
                    'snaps_missed_injury': random.randint(0, 5),
                    'games_missed_season': random.randint(0, 2),
                    
                    'created_at': datetime.utcnow()
                }
                
                # Create the analytics record
                analytics_record = PlayerAnalytics(
                    player_id=player.id,
                    week=week,
                    season=season,
                    **analytics_data
                )
                
                db.add(analytics_record)
                records_created += 1
                
                # Commit in batches
                if records_created % 100 == 0:
                    db.commit()
                    logger.info(f"Created {records_created} analytics records...")
        
        # Final commit
        db.commit()
        logger.info(f"Successfully created {records_created} total analytics records")
        
        return records_created
        
    except Exception as e:
        logger.error(f"Error populating analytics: {str(e)}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    records = populate_analytics()
    print(f"Created {records} analytics records")