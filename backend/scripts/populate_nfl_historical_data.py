#!/usr/bin/env python3
"""
NFL Historical Data Population Script
Fetches and populates historical NFL player data from multiple sources
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
import requests
import json

from app.core.database import SessionLocal
from app.models.fantasy_models import FantasyPlayer, PlayerAnalytics
from app.models.database_models import SleeperPlayer

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NFLDataPopulator:
    def __init__(self):
        self.db = SessionLocal()
        self.espn_base_url = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    def fetch_espn_players(self, season: int = 2024) -> List[Dict]:
        """Fetch player data from ESPN API"""
        try:
            # ESPN API endpoints for player stats
            url = f"{self.espn_base_url}/athletes"
            params = {"limit": 1000}
            
            response = requests.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                return data.get('items', [])
            else:
                logger.error(f"Failed to fetch ESPN data: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching ESPN data: {str(e)}")
            return []
    
    def fetch_weekly_stats_from_github(self) -> pd.DataFrame:
        """
        Fetch NFL stats from public GitHub repositories
        Many developers share cleaned NFL data on GitHub
        """
        try:
            # nflverse maintains public data
            base_url = "https://github.com/nflverse/nfldata/raw/master/data/"
            
            # Try to fetch player stats CSV
            stats_urls = [
                "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/player_stats.csv",
                "https://raw.githubusercontent.com/nflverse/nflverse-data/master/data/weekly_player_data.csv"
            ]
            
            for url in stats_urls:
                try:
                    df = pd.read_csv(url)
                    logger.info(f"Successfully fetched data from {url}")
                    return df
                except:
                    continue
                    
            logger.warning("Could not fetch data from GitHub sources")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error fetching GitHub data: {str(e)}")
            return pd.DataFrame()
    
    def use_nfl_data_py(self):
        """
        Use nfl_data_py package if available
        This is the recommended approach for getting comprehensive NFL data
        """
        try:
            import nfl_data_py as nfl
            
            logger.info("Using nfl_data_py package for data fetching...")
            
            # Import various datasets
            years = [2020, 2021, 2022, 2023, 2024]
            
            # Get weekly player data
            logger.info("Fetching weekly player data...")
            weekly_data = nfl.import_weekly_data(years)
            
            # Get player IDs for mapping
            logger.info("Fetching player ID mappings...")
            player_ids = nfl.import_ids()
            
            # Get seasonal data
            logger.info("Fetching seasonal data...")
            seasonal_data = nfl.import_seasonal_data(years)
            
            return {
                'weekly': weekly_data,
                'players': player_ids,
                'seasonal': seasonal_data
            }
        except ImportError:
            logger.warning("nfl_data_py not installed. Install with: pip install nfl-data-py")
            return None
        except Exception as e:
            logger.error(f"Error using nfl_data_py: {str(e)}")
            return None
    
    def populate_from_nfl_data_py(self, data: Dict):
        """Populate database using nfl_data_py data"""
        if not data:
            return
        
        weekly_df = data.get('weekly', pd.DataFrame())
        players_df = data.get('players', pd.DataFrame())
        
        if weekly_df.empty:
            logger.error("No weekly data available")
            return
        
        logger.info(f"Processing {len(weekly_df)} weekly records...")
        
        # Map player names to our database IDs
        fantasy_players = self.db.query(FantasyPlayer).all()
        player_map = {p.name.lower(): p.id for p in fantasy_players}
        
        # Also try mapping by platform_player_id if available
        platform_map = {p.platform_player_id: p.id for p in fantasy_players if p.platform_player_id}
        
        records_added = 0
        
        for _, row in weekly_df.iterrows():
            try:
                # Try to find player in our database
                player_name = str(row.get('player_display_name', '')).lower()
                player_id = player_map.get(player_name)
                
                if not player_id:
                    # Try by player ID if available
                    external_id = str(row.get('player_id', ''))
                    player_id = platform_map.get(external_id)
                
                if not player_id:
                    # Skip players not in our database
                    continue
                
                week = int(row.get('week', 0))
                season = int(row.get('season', 0))
                
                if week == 0 or season == 0:
                    continue
                
                # Check if record already exists
                existing = self.db.query(PlayerAnalytics).filter(
                    PlayerAnalytics.player_id == player_id,
                    PlayerAnalytics.week == week,
                    PlayerAnalytics.season == season
                ).first()
                
                if existing:
                    continue
                
                # Calculate analytics from the data
                analytics = PlayerAnalytics(
                    player_id=player_id,
                    week=week,
                    season=season,
                    opponent=row.get('recent_team', 'UNK'),
                    
                    # Snap data
                    total_snaps=int(row.get('offense_snaps', 0) or 0),
                    snap_percentage=float(row.get('offense_pct', 0) or 0) * 100,
                    
                    # Target/Reception data
                    targets=int(row.get('targets', 0) or 0),
                    target_share=float(row.get('target_share', 0) or 0),
                    receptions=int(row.get('receptions', 0) or 0),
                    
                    # Yards
                    air_yards=float(row.get('air_yards', 0) or 0),
                    air_yards_share=float(row.get('air_yards_share', 0) or 0),
                    
                    # Red zone
                    red_zone_targets=int(row.get('red_zone_targets', 0) or 0),
                    red_zone_carries=int(row.get('red_zone_carries', 0) or 0),
                    red_zone_touches=int(row.get('red_zone_touches', 0) or 0),
                    
                    # Fantasy points
                    ppr_points=float(row.get('fantasy_points_ppr', 0) or 0),
                    
                    # Calculate efficiency metrics
                    points_per_snap=float(row.get('fantasy_points_ppr', 0) or 0) / max(int(row.get('offense_snaps', 1) or 1), 1),
                    points_per_target=float(row.get('fantasy_points_ppr', 0) or 0) / max(int(row.get('targets', 1) or 1), 1) if int(row.get('targets', 0) or 0) > 0 else 0,
                    
                    # Additional metrics
                    routes_run=int(row.get('routes', 0) or 0),
                    average_depth_of_target=float(row.get('aDOT', 0) or 0),
                )
                
                self.db.add(analytics)
                records_added += 1
                
                if records_added % 100 == 0:
                    self.db.commit()
                    logger.info(f"Added {records_added} analytics records...")
                    
            except Exception as e:
                logger.error(f"Error processing row: {str(e)}")
                continue
        
        self.db.commit()
        logger.info(f"Successfully added {records_added} analytics records")
    
    def populate_missing_players(self):
        """Ensure we have all active NFL players in our database"""
        try:
            # Get current Sleeper players if not already populated
            sleeper_players = self.db.query(SleeperPlayer).all()
            
            if len(sleeper_players) < 100:
                logger.info("Fetching Sleeper players list...")
                response = requests.get("https://api.sleeper.app/v1/players/nfl")
                if response.status_code == 200:
                    players_data = response.json()
                    
                    for player_id, player_info in players_data.items():
                        if not player_info.get('active'):
                            continue
                        
                        # Check if player exists
                        existing = self.db.query(SleeperPlayer).filter(
                            SleeperPlayer.player_id == player_id
                        ).first()
                        
                        if not existing:
                            sleeper_player = SleeperPlayer(
                                player_id=player_id,
                                first_name=player_info.get('first_name', ''),
                                last_name=player_info.get('last_name', ''),
                                team=player_info.get('team', ''),
                                position=player_info.get('position', ''),
                                status=player_info.get('status', 'Active'),
                                injury_status=player_info.get('injury_status'),
                                age=player_info.get('age'),
                                years_exp=player_info.get('years_exp', 0),
                                college=player_info.get('college', ''),
                                height=player_info.get('height', ''),
                                weight=player_info.get('weight', ''),
                                birth_date=player_info.get('birth_date'),
                                full_data=player_info
                            )
                            self.db.add(sleeper_player)
                    
                    self.db.commit()
                    logger.info(f"Added {len(players_data)} Sleeper players to database")
            
            # Sync to fantasy_players table
            self._sync_to_fantasy_players()
            
        except Exception as e:
            logger.error(f"Error populating players: {str(e)}")
    
    def _sync_to_fantasy_players(self):
        """Sync Sleeper players to fantasy_players table"""
        sleeper_players = self.db.query(SleeperPlayer).all()
        
        for sp in sleeper_players:
            # Check if exists in fantasy_players
            existing = self.db.query(FantasyPlayer).filter(
                FantasyPlayer.platform_player_id == sp.player_id
            ).first()
            
            if not existing:
                fantasy_player = FantasyPlayer(
                    platform_player_id=sp.player_id,
                    name=f"{sp.first_name} {sp.last_name}".strip(),
                    position=sp.position,
                    team=sp.team,
                    age=sp.age,
                    years_exp=sp.years_exp or 0
                )
                self.db.add(fantasy_player)
        
        self.db.commit()
        logger.info("Synced Sleeper players to fantasy_players table")
    
    def run_population(self):
        """Main population process"""
        logger.info("Starting NFL historical data population...")
        
        # Step 1: Ensure we have all players
        logger.info("Step 1: Populating player database...")
        self.populate_missing_players()
        
        # Step 2: Try nfl_data_py first (best option)
        logger.info("Step 2: Fetching historical data...")
        nfl_data = self.use_nfl_data_py()
        
        if nfl_data:
            logger.info("Step 3: Populating analytics from nfl_data_py...")
            self.populate_from_nfl_data_py(nfl_data)
        else:
            logger.info("Step 3: Falling back to alternative sources...")
            # Try GitHub sources
            github_data = self.fetch_weekly_stats_from_github()
            if not github_data.empty:
                logger.info("Using GitHub data source...")
                # Process GitHub data (similar to nfl_data_py)
            else:
                logger.warning("No data sources available. Please install nfl-data-py:")
                logger.warning("pip install nfl-data-py")
        
        logger.info("Population complete!")
        
        # Show summary
        total_analytics = self.db.query(PlayerAnalytics).count()
        unique_players = self.db.query(PlayerAnalytics.player_id).distinct().count()
        seasons = self.db.query(PlayerAnalytics.season).distinct().all()
        
        logger.info(f"Summary:")
        logger.info(f"- Total analytics records: {total_analytics}")
        logger.info(f"- Unique players with data: {unique_players}")
        logger.info(f"- Seasons covered: {[s[0] for s in seasons]}")

if __name__ == "__main__":
    populator = NFLDataPopulator()
    
    # First, check if nfl_data_py is available
    try:
        import nfl_data_py
        logger.info("nfl_data_py is installed and ready to use!")
    except ImportError:
        logger.warning("nfl_data_py is not installed.")
        logger.warning("For best results, install it with:")
        logger.warning("pip install nfl-data-py")
        logger.warning("")
        response = input("Do you want to continue with alternative sources? (y/n): ")
        if response.lower() != 'y':
            sys.exit(0)
    
    populator.run_population()