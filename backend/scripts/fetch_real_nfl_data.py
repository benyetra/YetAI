#!/usr/bin/env python3
"""
Fetch real NFL data from public APIs without requiring special packages
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
from app.models.fantasy_models import FantasyPlayer, PlayerAnalytics

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RealNFLDataFetcher:
    def __init__(self):
        self.db = SessionLocal()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    def fetch_from_nflverse(self):
        """Fetch data from nflverse GitHub repository (public data)"""
        try:
            logger.info("Fetching data from nflverse GitHub...")
            
            # nflverse maintains public CSV files with NFL data
            base_url = "https://github.com/nflverse/nflverse-data/releases/download/"
            
            # Try to fetch player stats
            stats_url = f"{base_url}player_stats/player_stats.csv"
            
            # For simplicity, we'll use the Sleeper API which is more reliable
            return self.fetch_sleeper_comprehensive_stats()
            
        except Exception as e:
            logger.error(f"Error fetching nflverse data: {str(e)}")
            return None
    
    def fetch_sleeper_comprehensive_stats(self):
        """Fetch comprehensive stats from Sleeper API for multiple seasons"""
        try:
            logger.info("Fetching comprehensive stats from Sleeper API...")
            
            # Get player mappings
            fantasy_players = self.db.query(FantasyPlayer).all()
            player_map = {p.platform_player_id: p.id for p in fantasy_players if p.platform_player_id}
            
            if not player_map:
                logger.warning("No players found with platform IDs. Fetching player list...")
                self.sync_sleeper_players()
                fantasy_players = self.db.query(FantasyPlayer).all()
                player_map = {p.platform_player_id: p.id for p in fantasy_players if p.platform_player_id}
            
            logger.info(f"Found {len(player_map)} players to fetch stats for")
            
            total_records_added = 0
            
            # Fetch stats for multiple seasons and weeks
            seasons = [2021, 2022, 2023, 2024]
            
            for season in seasons:
                logger.info(f"Processing season {season}...")
                
                # NFL regular season is 18 weeks (17 weeks in 2021)
                max_week = 17 if season == 2021 else 18
                
                for week in range(1, max_week + 1):
                    try:
                        # Sleeper provides weekly stats
                        url = f"https://api.sleeper.app/v1/stats/nfl/regular/{season}/{week}"
                        
                        response = requests.get(url, timeout=30)
                        
                        if response.status_code == 200:
                            week_stats = response.json()
                            
                            if week_stats:
                                records = self.process_week_stats(week_stats, season, week, player_map)
                                total_records_added += records
                                logger.info(f"Season {season}, Week {week}: Added {records} records")
                        else:
                            logger.warning(f"No data for {season} week {week}")
                            
                    except Exception as e:
                        logger.error(f"Error fetching week {week} of {season}: {str(e)}")
                        continue
                    
                    # Commit every 500 records
                    if total_records_added % 500 == 0 and total_records_added > 0:
                        self.db.commit()
                        logger.info(f"Committed {total_records_added} total records")
            
            # Final commit
            self.db.commit()
            logger.info(f"Successfully added {total_records_added} total analytics records")
            
            return total_records_added
            
        except Exception as e:
            logger.error(f"Error in fetch_sleeper_comprehensive_stats: {str(e)}")
            self.db.rollback()
            return 0
    
    def sync_sleeper_players(self):
        """Sync Sleeper player list to our database"""
        try:
            logger.info("Syncing Sleeper player list...")
            
            response = requests.get("https://api.sleeper.app/v1/players/nfl")
            
            if response.status_code == 200:
                players_data = response.json()
                added = 0
                
                for player_id, player_info in players_data.items():
                    # Only add active players with fantasy relevance
                    if not player_info.get('active'):
                        continue
                    
                    position = player_info.get('position', '')
                    if position not in ['QB', 'RB', 'WR', 'TE', 'K', 'DEF']:
                        continue
                    
                    # Check if player exists
                    existing = self.db.query(FantasyPlayer).filter(
                        FantasyPlayer.platform_player_id == player_id
                    ).first()
                    
                    if not existing:
                        fantasy_player = FantasyPlayer(
                            platform_player_id=player_id,
                            name=f"{player_info.get('first_name', '')} {player_info.get('last_name', '')}".strip(),
                            position=position,
                            team=player_info.get('team', ''),
                            age=player_info.get('age'),
                            years_exp=player_info.get('years_exp', 0)
                        )
                        self.db.add(fantasy_player)
                        added += 1
                
                self.db.commit()
                logger.info(f"Added {added} new players to database")
                
        except Exception as e:
            logger.error(f"Error syncing players: {str(e)}")
            self.db.rollback()
    
    def process_week_stats(self, week_stats: Dict, season: int, week: int, player_map: Dict) -> int:
        """Process weekly stats and save to database"""
        records_added = 0
        
        for player_id, stats in week_stats.items():
            try:
                # Check if we have this player
                internal_id = player_map.get(player_id)
                if not internal_id:
                    continue
                
                # Check if record already exists
                existing = self.db.query(PlayerAnalytics).filter(
                    PlayerAnalytics.player_id == internal_id,
                    PlayerAnalytics.week == week,
                    PlayerAnalytics.season == season
                ).first()
                
                if existing:
                    continue
                
                # Create analytics record with real data
                analytics = PlayerAnalytics(
                    player_id=internal_id,
                    week=week,
                    season=season,
                    opponent=stats.get('opp', 'UNK'),
                    
                    # Snap data
                    total_snaps=int(stats.get('off_snp', 0) or 0),
                    snap_percentage=float(stats.get('off_snp_pct', 0) or 0) * 100,
                    snap_share_rank=0,  # Will calculate later
                    
                    # Receiving stats
                    targets=int(stats.get('rec_tgt', 0) or 0),
                    target_share=float(stats.get('tm_tgt_share', 0) or 0),
                    receptions=int(stats.get('rec', 0) or 0),
                    air_yards=float(stats.get('rec_air_yds', 0) or 0),
                    air_yards_share=float(stats.get('tm_air_yds_share', 0) or 0),
                    average_depth_of_target=float(stats.get('rec_adot', 0) or 0),
                    
                    # Red zone
                    red_zone_targets=int(stats.get('rec_rz_tgt', 0) or 0),
                    red_zone_carries=int(stats.get('rush_rz_att', 0) or 0),
                    red_zone_touches=(
                        int(stats.get('rush_rz_att', 0) or 0) + 
                        int(stats.get('rec_rz_tgt', 0) or 0)
                    ),
                    red_zone_share=0.0,  # Will calculate if we have team data
                    red_zone_efficiency=0.0,
                    
                    # Route running
                    routes_run=int(stats.get('rec_routes', 0) or 0),
                    route_participation=float(stats.get('route_participation', 0) or 0),
                    slot_rate=float(stats.get('rec_slot_snaps', 0) or 0) / max(int(stats.get('rec_routes', 1) or 1), 1),
                    deep_target_rate=float(stats.get('rec_deep_tgt', 0) or 0) / max(int(stats.get('rec_tgt', 1) or 1), 1) if int(stats.get('rec_tgt', 0) or 0) > 0 else 0,
                    
                    # Fantasy points
                    ppr_points=float(stats.get('pts_ppr', 0) or 0),
                    
                    # Efficiency metrics
                    points_per_snap=(
                        float(stats.get('pts_ppr', 0) or 0) / 
                        max(int(stats.get('off_snp', 1) or 1), 1)
                    ),
                    points_per_target=(
                        float(stats.get('pts_ppr', 0) or 0) / 
                        max(int(stats.get('rec_tgt', 1) or 1), 1)
                    ) if int(stats.get('rec_tgt', 0) or 0) > 0 else 0,
                    points_per_touch=0.0,  # Will calculate
                    
                    # Consistency metrics (will calculate after all data is loaded)
                    boom_rate=0.0,
                    bust_rate=0.0,
                    floor_score=0.0,
                    ceiling_score=0.0,
                    weekly_variance=0.0,
                    
                    # Game context
                    game_script='neutral',
                    injury_designation=None
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
                logger.error(f"Error processing player {player_id}: {str(e)}")
                continue
        
        return records_added
    
    def calculate_consistency_metrics(self):
        """Calculate boom/bust rates and consistency metrics after data is loaded"""
        logger.info("Calculating consistency metrics...")
        
        # Get all unique players
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
    
    def run(self):
        """Main execution"""
        logger.info("Starting real NFL data fetch...")
        
        # Fetch comprehensive stats
        records = self.fetch_sleeper_comprehensive_stats()
        
        if records > 0:
            # Calculate derived metrics
            self.calculate_consistency_metrics()
        
        # Summary
        total_records = self.db.query(PlayerAnalytics).count()
        unique_players = self.db.query(PlayerAnalytics.player_id).distinct().count()
        seasons = self.db.query(PlayerAnalytics.season).distinct().all()
        
        logger.info("=" * 50)
        logger.info("Data Population Complete!")
        logger.info(f"Total analytics records: {total_records}")
        logger.info(f"Unique players with data: {unique_players}")
        logger.info(f"Seasons covered: {sorted([s[0] for s in seasons])}")
        
        # Show breakdown by season
        for (season,) in sorted(seasons):
            season_records = self.db.query(PlayerAnalytics).filter(
                PlayerAnalytics.season == season
            ).count()
            weeks = self.db.query(PlayerAnalytics.week).filter(
                PlayerAnalytics.season == season
            ).distinct().count()
            logger.info(f"  Season {season}: {season_records} records, {weeks} weeks")
        
        logger.info("=" * 50)

if __name__ == "__main__":
    fetcher = RealNFLDataFetcher()
    fetcher.run()