#!/usr/bin/env python3
"""
Populate NFL Data Using Player ID Mappings
Now that we have proper ID mappings, fetch and populate real NFL data
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from app.core.database import SessionLocal
from app.models.fantasy_models import PlayerAnalytics
from app.models.player_mapping import PlayerIDMapping

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MappingBasedDataPopulator:
    def __init__(self):
        self.db = SessionLocal()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    def populate_historical_data(self):
        """Populate historical data using player ID mappings"""
        logger.info("Starting historical data population using ID mappings...")
        
        # Get all players with Sleeper IDs
        mappings = self.db.query(PlayerIDMapping).filter(
            PlayerIDMapping.sleeper_id.isnot(None)
        ).all()
        
        logger.info(f"Found {len(mappings)} players with Sleeper IDs")
        
        total_records_added = 0
        
        # Fetch data for multiple seasons
        seasons = [2021, 2022, 2023, 2024]
        
        for season in seasons:
            logger.info(f"Processing season {season}...")
            
            # NFL regular season weeks
            max_week = 17 if season == 2021 else 18
            
            for week in range(1, max_week + 1):
                try:
                    # Fetch week data from Sleeper
                    url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
                    response = requests.get(url, timeout=30)
                    
                    if response.status_code == 200:
                        week_stats = response.json()
                        
                        if week_stats:
                            records = self.process_week_with_mappings(week_stats, season, week, mappings)
                            total_records_added += records
                            logger.info(f"Season {season}, Week {week}: Added {records} records")
                        else:
                            logger.warning(f"No stats for {season} week {week}")
                    else:
                        logger.warning(f"Failed to fetch {season} week {week}: {response.status_code}")
                        
                except Exception as e:
                    logger.error(f"Error fetching week {week} of {season}: {str(e)}")
                    continue
                
                # Commit every 500 records
                if total_records_added % 500 == 0 and total_records_added > 0:
                    self.db.commit()
                    logger.info(f"Committed {total_records_added} total records")
        
        # Final commit
        self.db.commit()
        
        # Calculate consistency metrics
        self.calculate_consistency_metrics()
        
        logger.info("=" * 50)
        logger.info(f"Successfully added {total_records_added} analytics records!")
        
        # Show summary
        self.show_summary()
        
        return total_records_added
    
    def process_week_with_mappings(self, week_stats: Dict, season: int, week: int, mappings: List[PlayerIDMapping]) -> int:
        """Process weekly stats using our ID mappings"""
        records_added = 0
        
        # Create a lookup dict for faster processing
        sleeper_to_yetai = {m.sleeper_id: m.yetai_id for m in mappings}
        
        for sleeper_id, stats in week_stats.items():
            try:
                # Check if we have a mapping for this player
                yetai_id = sleeper_to_yetai.get(sleeper_id)
                if not yetai_id:
                    continue
                
                # Check if record already exists
                existing = self.db.query(PlayerAnalytics).filter(
                    PlayerAnalytics.player_id == yetai_id,
                    PlayerAnalytics.week == week,
                    PlayerAnalytics.season == season
                ).first()
                
                if existing:
                    continue
                
                # Create analytics record with real data
                analytics = PlayerAnalytics(
                    player_id=yetai_id,
                    week=week,
                    season=season,
                    opponent=stats.get('opp', 'UNK'),
                    
                    # Snap data
                    total_snaps=int(stats.get('off_snp', 0) or 0),
                    snap_percentage=float(stats.get('off_snp_pct', 0) or 0) * 100,
                    
                    # Receiving stats
                    targets=int(stats.get('rec_tgt', 0) or 0),
                    target_share=float(stats.get('tm_tgt_share', 0) or 0),
                    receptions=int(stats.get('rec', 0) or 0),
                    air_yards=float(stats.get('rec_air_yds', 0) or 0),
                    air_yards_share=float(stats.get('tm_air_yds_share', 0) or 0),
                    average_depth_of_target=float(stats.get('rec_adot', 0) or 0),
                    
                    # Rushing stats
                    carries=int(stats.get('rush_att', 0) or 0),
                    rushing_yards=int(stats.get('rush_yd', 0) or 0),
                    
                    # Receiving yards
                    receiving_yards=int(stats.get('rec_yd', 0) or 0),
                    yards_after_catch=float(stats.get('rec_yac', 0) or 0),
                    
                    # Red zone
                    red_zone_targets=int(stats.get('rec_rz_tgt', 0) or 0),
                    red_zone_carries=int(stats.get('rush_rz_att', 0) or 0),
                    red_zone_touches=(
                        int(stats.get('rush_rz_att', 0) or 0) + 
                        int(stats.get('rec_rz_tgt', 0) or 0)
                    ),
                    
                    # Route running
                    routes_run=int(stats.get('rec_routes', 0) or 0),
                    route_participation=float(stats.get('route_participation', 0) or 0),
                    slot_rate=float(stats.get('rec_slot_snaps', 0) or 0) / max(int(stats.get('rec_routes', 1) or 1), 1),
                    
                    # Fantasy points
                    ppr_points=float(stats.get('pts_ppr', 0) or 0),
                    half_ppr_points=float(stats.get('pts_half_ppr', 0) or 0),
                    standard_points=float(stats.get('pts_std', 0) or 0),
                    
                    # Efficiency metrics
                    points_per_snap=(
                        float(stats.get('pts_ppr', 0) or 0) / 
                        max(int(stats.get('off_snp', 1) or 1), 1)
                    ),
                    points_per_target=(
                        float(stats.get('pts_ppr', 0) or 0) / 
                        max(int(stats.get('rec_tgt', 1) or 1), 1)
                    ) if int(stats.get('rec_tgt', 0) or 0) > 0 else 0,
                    
                    # Calculate points per touch
                    points_per_touch=0.0,
                    
                    # Default values for now (will calculate later)
                    snap_share_rank=0,
                    red_zone_share=0.0,
                    red_zone_efficiency=0.0,
                    deep_target_rate=0.0,
                    boom_rate=0.0,
                    bust_rate=0.0,
                    floor_score=0.0,
                    ceiling_score=0.0,
                    weekly_variance=0.0,
                    game_script='neutral'
                )
                
                # Calculate points per touch
                total_touches = (
                    int(stats.get('rec', 0) or 0) + 
                    int(stats.get('rush_att', 0) or 0)
                )
                if total_touches > 0:
                    analytics.points_per_touch = analytics.ppr_points / total_touches
                
                self.db.add(analytics)
                records_added += 1
                
            except Exception as e:
                logger.error(f"Error processing player {sleeper_id}: {str(e)}")
                continue
        
        return records_added
    
    def calculate_consistency_metrics(self):
        """Calculate boom/bust rates and consistency metrics"""
        logger.info("Calculating consistency metrics...")
        
        # Get all unique players with data
        players = self.db.query(PlayerAnalytics.player_id).distinct().all()
        
        for (player_id,) in players:
            # Get all games for this player
            games = self.db.query(PlayerAnalytics).filter(
                PlayerAnalytics.player_id == player_id
            ).all()
            
            if len(games) < 3:
                continue
            
            points = [g.ppr_points for g in games if g.ppr_points is not None]
            
            if points:
                # Calculate metrics
                boom_games = len([p for p in points if p >= 20])
                bust_games = len([p for p in points if p < 5])
                
                boom_rate = boom_games / len(points)
                bust_rate = bust_games / len(points)
                floor = min(points)
                ceiling = max(points)
                avg = sum(points) / len(points)
                
                # Calculate variance
                if len(points) > 1:
                    variance = sum((p - avg) ** 2 for p in points) / (len(points) - 1)
                else:
                    variance = 0
                
                # Update all games with these metrics
                for game in games:
                    game.boom_rate = boom_rate
                    game.bust_rate = bust_rate
                    game.floor_score = floor
                    game.ceiling_score = ceiling
                    game.weekly_variance = variance
        
        self.db.commit()
        logger.info("Consistency metrics calculated")
    
    def show_summary(self):
        """Show summary of populated data"""
        total_records = self.db.query(PlayerAnalytics).count()
        unique_players = self.db.query(PlayerAnalytics.player_id).distinct().count()
        seasons = self.db.query(PlayerAnalytics.season).distinct().order_by(PlayerAnalytics.season).all()
        
        logger.info("=" * 50)
        logger.info("Data Population Summary")
        logger.info("=" * 50)
        logger.info(f"Total analytics records: {total_records:,}")
        logger.info(f"Unique players with data: {unique_players}")
        logger.info(f"Seasons covered: {[s[0] for s in seasons]}")
        
        # Show breakdown by season
        for (season,) in seasons:
            season_records = self.db.query(PlayerAnalytics).filter(
                PlayerAnalytics.season == season
            ).count()
            
            weeks = self.db.query(PlayerAnalytics.week).filter(
                PlayerAnalytics.season == season
            ).distinct().count()
            
            players = self.db.query(PlayerAnalytics.player_id).filter(
                PlayerAnalytics.season == season
            ).distinct().count()
            
            logger.info(f"  Season {season}: {season_records:,} records, {weeks} weeks, {players} players")
        
        # Show sample of high-confidence mappings
        high_confidence = self.db.query(PlayerIDMapping).filter(
            PlayerIDMapping.confidence_score >= 0.95
        ).limit(5).all()
        
        logger.info("\nSample High-Confidence Player Mappings:")
        for mapping in high_confidence:
            logger.info(f"  {mapping.full_name}: YetAI #{mapping.yetai_id} -> Sleeper {mapping.sleeper_id} (confidence: {mapping.confidence_score:.2f})")
        
        logger.info("=" * 50)

if __name__ == "__main__":
    populator = MappingBasedDataPopulator()
    populator.populate_historical_data()