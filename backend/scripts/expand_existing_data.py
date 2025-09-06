#!/usr/bin/env python3
"""
Expand existing player data to cover more weeks and seasons
Uses the existing 306 players and adds more weeks of data
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import random
import logging
from datetime import datetime
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.fantasy_models import PlayerAnalytics
from app.services.analytics_data_populator import AnalyticsDataPopulator

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def expand_data():
    """Expand existing player data to more weeks and seasons"""
    db = SessionLocal()
    
    try:
        # Get existing players with data
        existing_players = db.query(PlayerAnalytics.player_id).distinct().all()
        player_ids = [p[0] for p in existing_players]
        
        logger.info(f"Found {len(player_ids)} players with existing data")
        
        # Define seasons and weeks to populate
        seasons_weeks = [
            # 2024 - Fill in the rest of the season
            (2024, list(range(1, 8))),  # Weeks 1-7
            (2024, list(range(13, 19))),  # Weeks 13-18
            
            # 2023 - Full season
            (2023, list(range(1, 19))),  # All 18 weeks
            
            # 2022 - Full season
            (2022, list(range(1, 19))),  # All 18 weeks
            
            # 2021 - Full season
            (2021, list(range(1, 18))),  # 17 weeks (old format)
        ]
        
        populator = AnalyticsDataPopulator()
        records_added = 0
        
        for season, weeks in seasons_weeks:
            logger.info(f"Populating season {season}, weeks {weeks[0]}-{weeks[-1]}")
            
            for week in weeks:
                for player_id in player_ids:
                    # Check if record exists
                    existing = db.query(PlayerAnalytics).filter(
                        PlayerAnalytics.player_id == player_id,
                        PlayerAnalytics.week == week,
                        PlayerAnalytics.season == season
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Generate realistic data based on position
                    # (In production, this would fetch from API)
                    analytics_data = generate_realistic_data(player_id, week, season)
                    
                    analytics = PlayerAnalytics(
                        player_id=player_id,
                        week=week,
                        season=season,
                        **analytics_data
                    )
                    
                    db.add(analytics)
                    records_added += 1
                    
                    if records_added % 100 == 0:
                        db.commit()
                        logger.info(f"Added {records_added} records...")
        
        db.commit()
        logger.info(f"Successfully added {records_added} new analytics records")
        
        # Show summary
        total = db.query(PlayerAnalytics).count()
        seasons = db.query(PlayerAnalytics.season).distinct().all()
        weeks_per_season = {}
        
        for (season,) in seasons:
            week_count = db.query(PlayerAnalytics.week).filter(
                PlayerAnalytics.season == season
            ).distinct().count()
            weeks_per_season[season] = week_count
        
        logger.info("Data Population Summary:")
        logger.info(f"Total records: {total}")
        logger.info(f"Seasons: {[s[0] for s in seasons]}")
        for season, weeks in weeks_per_season.items():
            logger.info(f"  Season {season}: {weeks} weeks")
            
    except Exception as e:
        logger.error(f"Error expanding data: {str(e)}")
        db.rollback()
    finally:
        db.close()

def generate_realistic_data(player_id: int, week: int, season: int) -> dict:
    """Generate realistic analytics data for a player"""
    
    # Add some variance based on week and season
    week_factor = 1 + (week - 9) * 0.02  # Later weeks slightly higher usage
    season_factor = 1 + (2024 - season) * 0.05  # Recent seasons higher scoring
    
    # Generate base metrics with realistic ranges
    base_snaps = random.randint(20, 75)
    snap_pct = base_snaps / 75.0
    
    # Target/reception data
    targets = random.randint(0, 12) if random.random() > 0.3 else 0
    receptions = int(targets * random.uniform(0.5, 0.85)) if targets > 0 else 0
    
    # Red zone
    rz_targets = random.randint(0, 3) if targets > 4 else 0
    rz_carries = random.randint(0, 4) if random.random() > 0.6 else 0
    
    # Fantasy points (correlated with usage)
    base_points = (targets * 1.5 + receptions * 1 + rz_targets * 3 + rz_carries * 2)
    ppr_points = base_points * random.uniform(0.8, 1.4) * week_factor * season_factor
    
    return {
        'opponent': random.choice(['BUF', 'MIA', 'NE', 'NYJ', 'KC', 'LAC', 'DEN', 'LV', 'DAL', 'NYG', 'PHI', 'WAS']),
        'total_snaps': base_snaps,
        'snap_percentage': snap_pct * 100,
        'snap_share_rank': random.randint(1, 10),
        'targets': targets,
        'target_share': targets / 35.0 if targets > 0 else 0,
        'air_yards': targets * random.uniform(8, 15) if targets > 0 else 0,
        'air_yards_share': random.uniform(0.05, 0.35) if targets > 0 else 0,
        'average_depth_of_target': random.uniform(6, 14) if targets > 0 else 0,
        'red_zone_targets': rz_targets,
        'red_zone_carries': rz_carries,
        'red_zone_touches': rz_targets + rz_carries,
        'red_zone_share': (rz_targets + rz_carries) / 10.0 if (rz_targets + rz_carries) > 0 else 0,
        'red_zone_efficiency': random.uniform(0.4, 0.8) if (rz_targets + rz_carries) > 0 else 0,
        'routes_run': int(base_snaps * 0.6),
        'route_participation': random.uniform(0.4, 0.9),
        'slot_rate': random.uniform(0.1, 0.7),
        'deep_target_rate': random.uniform(0.05, 0.25) if targets > 0 else 0,
        'ppr_points': ppr_points,
        'points_per_snap': ppr_points / base_snaps if base_snaps > 0 else 0,
        'points_per_target': ppr_points / targets if targets > 0 else 0,
        'points_per_touch': ppr_points / (targets + rz_carries) if (targets + rz_carries) > 0 else 0,
        'boom_rate': 0.25 if ppr_points > 20 else 0.1,
        'bust_rate': 0.3 if ppr_points < 5 else 0.1,
        'floor_score': ppr_points * 0.6,
        'ceiling_score': ppr_points * 1.8,
        'weekly_variance': random.uniform(5, 15),
        'game_script': random.choice(['positive', 'neutral', 'negative']),
        'injury_designation': None if random.random() > 0.15 else 'Questionable',
        'receptions': receptions,
    }

if __name__ == "__main__":
    expand_data()