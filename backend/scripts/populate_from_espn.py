#!/usr/bin/env python3
"""
ESPN Data Population Script
Fetches NFL player data directly from ESPN's public API
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.fantasy_models import FantasyPlayer, PlayerAnalytics
from app.models.database_models import SleeperPlayer

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ESPNDataFetcher:
    def __init__(self):
        self.db = SessionLocal()
        self.base_url = "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl"
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    def fetch_season_data(self, season: int = 2024):
        """Fetch season data from ESPN"""
        try:
            # Get teams and schedule
            teams_url = f"{self.base_url}/seasons/{season}/teams"
            response = requests.get(teams_url)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Found {len(data.get('items', []))} teams for season {season}")
                return data
            else:
                logger.error(f"Failed to fetch teams: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Error fetching ESPN data: {str(e)}")
            return None
    
    def fetch_player_stats(self, season: int, week: int):
        """Fetch player stats for a specific week"""
        try:
            # ESPN Fantasy API endpoint
            url = f"https://fantasy.espn.com/football/playerstatsbyleague"
            params = {
                'leagueId': 0,  # Public league
                'seasonId': season,
                'scoringPeriodId': week,
                'statSourceId': 0,  # Actual stats
                'statSplitTypeId': 1  # Weekly
            }
            
            response = requests.get(url, params=params)
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.warning(f"Could not fetch week {week} of season {season}")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching player stats: {str(e)}")
            return None
    
    def use_sleeper_stats_api(self):
        """Use Sleeper's stats endpoint for historical data"""
        try:
            logger.info("Fetching historical stats from Sleeper API...")
            
            # Sleeper provides weekly stats
            seasons = [2021, 2022, 2023, 2024]
            
            for season in seasons:
                for week in range(1, 19):  # Regular season weeks
                    url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
                    
                    response = requests.get(url)
                    if response.status_code == 200:
                        stats = response.json()
                        self.process_sleeper_stats(stats, season, week)
                        logger.info(f"Processed week {week} of {season}")
                    else:
                        logger.warning(f"No data for week {week} of {season}")
                        
        except Exception as e:
            logger.error(f"Error fetching Sleeper stats: {str(e)}")
    
    def process_sleeper_stats(self, stats: Dict, season: int, week: int):
        """Process Sleeper stats and save to database"""
        
        # Get player mappings
        fantasy_players = self.db.query(FantasyPlayer).all()
        player_map = {p.platform_player_id: p.id for p in fantasy_players if p.platform_player_id}
        
        records_added = 0
        
        for player_id, player_stats in stats.items():
            try:
                # Check if we have this player
                internal_id = player_map.get(player_id)
                if not internal_id:
                    continue
                
                # Check if record exists
                existing = self.db.query(PlayerAnalytics).filter(
                    PlayerAnalytics.player_id == internal_id,
                    PlayerAnalytics.week == week,
                    PlayerAnalytics.season == season
                ).first()
                
                if existing:
                    continue
                
                # Extract stats
                analytics = PlayerAnalytics(
                    player_id=internal_id,
                    week=week,
                    season=season,
                    opponent=player_stats.get('opp', 'UNK'),
                    
                    # Offensive snaps
                    total_snaps=int(player_stats.get('off_snp', 0) or 0),
                    snap_percentage=float(player_stats.get('off_snp_pct', 0) or 0),
                    
                    # Receiving stats
                    targets=int(player_stats.get('rec_tgt', 0) or 0),
                    target_share=float(player_stats.get('rec_tgt_share', 0) or 0),
                    receptions=int(player_stats.get('rec', 0) or 0),
                    air_yards=float(player_stats.get('rec_air_yds', 0) or 0),
                    air_yards_share=float(player_stats.get('rec_air_yds_share', 0) or 0),
                    average_depth_of_target=float(player_stats.get('rec_adot', 0) or 0),
                    
                    # Rushing stats
                    red_zone_carries=int(player_stats.get('rush_rz_att', 0) or 0),
                    
                    # Red zone
                    red_zone_targets=int(player_stats.get('rec_rz_tgt', 0) or 0),
                    red_zone_touches=(
                        int(player_stats.get('rush_rz_att', 0) or 0) + 
                        int(player_stats.get('rec_rz_tgt', 0) or 0)
                    ),
                    
                    # Fantasy points
                    ppr_points=float(player_stats.get('pts_ppr', 0) or 0),
                    
                    # Efficiency
                    points_per_snap=(
                        float(player_stats.get('pts_ppr', 0) or 0) / 
                        max(int(player_stats.get('off_snp', 1) or 1), 1)
                    ),
                    points_per_target=(
                        float(player_stats.get('pts_ppr', 0) or 0) / 
                        max(int(player_stats.get('rec_tgt', 1) or 1), 1)
                    ) if int(player_stats.get('rec_tgt', 0) or 0) > 0 else 0,
                    
                    # Additional
                    routes_run=int(player_stats.get('rec_routes', 0) or 0),
                    slot_rate=float(player_stats.get('rec_slot_pct', 0) or 0),
                    deep_target_rate=float(player_stats.get('rec_deep_tgt_pct', 0) or 0),
                    
                    # Set some reasonable defaults for missing fields
                    snap_share_rank=0,
                    red_zone_share=0.0,
                    red_zone_efficiency=0.0,
                    route_participation=0.0,
                    points_per_touch=0.0,
                    boom_rate=0.0,
                    bust_rate=0.0,
                    floor_score=0.0,
                    ceiling_score=0.0,
                    weekly_variance=0.0,
                    consistency_score=0.0,
                    game_script='neutral'
                )
                
                self.db.add(analytics)
                records_added += 1
                
                if records_added % 100 == 0:
                    self.db.commit()
                    logger.info(f"Added {records_added} records...")
                    
            except Exception as e:
                logger.error(f"Error processing player {player_id}: {str(e)}")
                continue
        
        self.db.commit()
        logger.info(f"Added {records_added} records for week {week} of {season}")
        
        return records_added
    
    def calculate_derived_metrics(self):
        """Calculate boom/bust rates and other derived metrics after initial population"""
        logger.info("Calculating derived metrics...")
        
        # Get all unique players
        players = self.db.query(PlayerAnalytics.player_id).distinct().all()
        
        for (player_id,) in players:
            # Get all games for this player
            games = self.db.query(PlayerAnalytics).filter(
                PlayerAnalytics.player_id == player_id
            ).all()
            
            if len(games) < 3:
                continue
            
            # Calculate boom/bust rates
            points = [g.ppr_points for g in games if g.ppr_points is not None]
            
            if points:
                boom_games = len([p for p in points if p >= 20])
                bust_games = len([p for p in points if p < 5])
                
                boom_rate = boom_games / len(points)
                bust_rate = bust_games / len(points)
                
                floor = min(points)
                ceiling = max(points)
                avg = sum(points) / len(points)
                
                # Calculate variance
                variance = sum((p - avg) ** 2 for p in points) / len(points)
                
                # Update all games with these metrics
                for game in games:
                    game.boom_rate = boom_rate
                    game.bust_rate = bust_rate
                    game.floor_score = floor
                    game.ceiling_score = ceiling
                    game.weekly_variance = variance
                    game.consistency_score = 1 - (variance / (avg + 1))  # Simple consistency metric
        
        self.db.commit()
        logger.info("Derived metrics calculated")
    
    def run(self):
        """Main execution"""
        logger.info("Starting ESPN/Sleeper data population...")
        
        # First ensure we have players
        logger.info("Checking player database...")
        player_count = self.db.query(FantasyPlayer).count()
        
        if player_count < 100:
            logger.warning(f"Only {player_count} players found. Please run player sync first.")
            return
        
        logger.info(f"Found {player_count} players in database")
        
        # Use Sleeper stats API (it's free and comprehensive)
        self.use_sleeper_stats_api()
        
        # Calculate derived metrics
        self.calculate_derived_metrics()
        
        # Summary
        total_records = self.db.query(PlayerAnalytics).count()
        unique_players = self.db.query(PlayerAnalytics.player_id).distinct().count()
        seasons = self.db.query(PlayerAnalytics.season).distinct().all()
        
        logger.info("Population complete!")
        logger.info(f"Total analytics records: {total_records}")
        logger.info(f"Unique players with data: {unique_players}")
        logger.info(f"Seasons covered: {[s[0] for s in seasons]}")

if __name__ == "__main__":
    fetcher = ESPNDataFetcher()
    fetcher.run()