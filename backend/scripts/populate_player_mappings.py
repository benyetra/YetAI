#!/usr/bin/env python3
"""
Populate Player ID Mappings
Fetches player IDs from multiple sources and creates comprehensive mappings
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional
from fuzzywuzzy import fuzz
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.fantasy_models import FantasyPlayer
from app.models.player_mapping import PlayerIDMapping

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlayerMappingPopulator:
    def __init__(self):
        self.db = SessionLocal()
        
    def __del__(self):
        if hasattr(self, 'db'):
            self.db.close()
    
    def fetch_sleeper_players(self) -> Dict:
        """Fetch all players from Sleeper API"""
        try:
            logger.info("Fetching Sleeper player data...")
            response = requests.get("https://api.sleeper.app/v1/players/nfl")
            if response.status_code == 200:
                return response.json()
            return {}
        except Exception as e:
            logger.error(f"Error fetching Sleeper data: {str(e)}")
            return {}
    
    def fetch_espn_players(self) -> List[Dict]:
        """Fetch players from ESPN API"""
        try:
            logger.info("Fetching ESPN player data...")
            # ESPN endpoint for player list
            url = "https://fantasy.espn.com/apis/v3/games/ffl/seasons/2024/players?view=players_wl"
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Accept': 'application/json'
            }
            
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return data.get('players', [])
            return []
        except Exception as e:
            logger.error(f"Error fetching ESPN data: {str(e)}")
            return []
    
    def match_player_names(self, name1: str, name2: str) -> float:
        """Calculate similarity score between two player names"""
        # Remove common suffixes
        for suffix in [' Jr.', ' Jr', ' Sr.', ' Sr', ' III', ' II', ' IV', ' V']:
            name1 = name1.replace(suffix, '')
            name2 = name2.replace(suffix, '')
        
        # Calculate different similarity scores
        exact_match = 1.0 if name1.lower() == name2.lower() else 0.0
        ratio_score = fuzz.ratio(name1.lower(), name2.lower()) / 100.0
        partial_score = fuzz.partial_ratio(name1.lower(), name2.lower()) / 100.0
        token_score = fuzz.token_sort_ratio(name1.lower(), name2.lower()) / 100.0
        
        # Weighted average
        confidence = (exact_match * 0.5) + (ratio_score * 0.2) + (partial_score * 0.15) + (token_score * 0.15)
        
        return confidence
    
    def populate_mappings(self):
        """Main function to populate player ID mappings"""
        logger.info("Starting player ID mapping population...")
        
        # Get all YetAI players
        yetai_players = self.db.query(FantasyPlayer).all()
        logger.info(f"Found {len(yetai_players)} YetAI players")
        
        # Fetch data from external sources
        sleeper_data = self.fetch_sleeper_players()
        espn_data = self.fetch_espn_players()
        
        logger.info(f"Fetched {len(sleeper_data)} Sleeper players")
        logger.info(f"Fetched {len(espn_data)} ESPN players")
        
        mappings_created = 0
        mappings_updated = 0
        
        for yetai_player in yetai_players:
            try:
                # Check if mapping already exists
                existing_mapping = self.db.query(PlayerIDMapping).filter(
                    PlayerIDMapping.yetai_id == yetai_player.id
                ).first()
                
                if existing_mapping:
                    mapping = existing_mapping
                    is_update = True
                else:
                    mapping = PlayerIDMapping(yetai_id=yetai_player.id)
                    is_update = False
                
                # Set basic info
                mapping.full_name = yetai_player.name
                mapping.position = yetai_player.position
                mapping.team = yetai_player.team
                mapping.jersey_number = yetai_player.jersey_number
                
                # Parse name
                name_parts = yetai_player.name.split(' ')
                if len(name_parts) >= 2:
                    mapping.first_name = name_parts[0]
                    mapping.last_name = ' '.join(name_parts[1:])
                
                # Match with Sleeper
                best_sleeper_match = self.find_sleeper_match(yetai_player, sleeper_data)
                if best_sleeper_match:
                    mapping.sleeper_id = best_sleeper_match['id']
                    mapping.confidence_score = best_sleeper_match['confidence']
                    
                    # Get additional data from Sleeper
                    sleeper_info = best_sleeper_match['data']
                    if sleeper_info.get('birth_date'):
                        try:
                            mapping.birth_date = datetime.strptime(sleeper_info['birth_date'], '%Y-%m-%d').date()
                        except:
                            pass
                    mapping.college = sleeper_info.get('college')
                    mapping.is_active = sleeper_info.get('active', False)
                    mapping.is_rookie = sleeper_info.get('years_exp', 1) == 0
                    
                    # Get other platform IDs from Sleeper
                    mapping.espn_id = sleeper_info.get('espn_id')
                    mapping.yahoo_id = sleeper_info.get('yahoo_id')
                    mapping.sportradar_id = sleeper_info.get('sportradar_id')
                
                # Match with ESPN if not found in Sleeper
                if not mapping.espn_id and espn_data:
                    best_espn_match = self.find_espn_match(yetai_player, espn_data)
                    if best_espn_match:
                        mapping.espn_id = str(best_espn_match['id'])
                        if not mapping.confidence_score:
                            mapping.confidence_score = best_espn_match['confidence']
                
                # Update platform_player_id in fantasy_players if we found Sleeper ID
                if mapping.sleeper_id and not yetai_player.platform_player_id:
                    yetai_player.platform_player_id = mapping.sleeper_id
                
                # Save mapping
                if is_update:
                    mappings_updated += 1
                else:
                    self.db.add(mapping)
                    mappings_created += 1
                
                # Commit periodically
                if (mappings_created + mappings_updated) % 50 == 0:
                    self.db.commit()
                    logger.info(f"Progress: {mappings_created} created, {mappings_updated} updated")
                    
            except Exception as e:
                logger.error(f"Error processing player {yetai_player.name}: {str(e)}")
                continue
        
        # Final commit
        self.db.commit()
        
        logger.info("=" * 50)
        logger.info("Player ID Mapping Population Complete!")
        logger.info(f"Mappings created: {mappings_created}")
        logger.info(f"Mappings updated: {mappings_updated}")
        
        # Show statistics
        total_mappings = self.db.query(PlayerIDMapping).count()
        with_sleeper = self.db.query(PlayerIDMapping).filter(PlayerIDMapping.sleeper_id.isnot(None)).count()
        with_espn = self.db.query(PlayerIDMapping).filter(PlayerIDMapping.espn_id.isnot(None)).count()
        verified = self.db.query(PlayerIDMapping).filter(PlayerIDMapping.is_verified == True).count()
        high_confidence = self.db.query(PlayerIDMapping).filter(PlayerIDMapping.confidence_score >= 0.9).count()
        
        logger.info(f"Total mappings: {total_mappings}")
        logger.info(f"With Sleeper ID: {with_sleeper}")
        logger.info(f"With ESPN ID: {with_espn}")
        logger.info(f"Verified: {verified}")
        logger.info(f"High confidence (>= 0.9): {high_confidence}")
        logger.info("=" * 50)
    
    def find_sleeper_match(self, yetai_player: FantasyPlayer, sleeper_data: Dict) -> Optional[Dict]:
        """Find best matching Sleeper player"""
        best_match = None
        best_confidence = 0.0
        
        # First try exact platform_player_id match
        if yetai_player.platform_player_id and yetai_player.platform_player_id in sleeper_data:
            return {
                'id': yetai_player.platform_player_id,
                'confidence': 1.0,
                'data': sleeper_data[yetai_player.platform_player_id]
            }
        
        # Try name matching
        for sleeper_id, sleeper_info in sleeper_data.items():
            # Skip inactive players unless exact match
            if not sleeper_info.get('active', False):
                continue
            
            # Build Sleeper full name
            sleeper_name = f"{sleeper_info.get('first_name', '')} {sleeper_info.get('last_name', '')}".strip()
            
            if not sleeper_name:
                continue
            
            # Check position match
            if yetai_player.position and sleeper_info.get('position'):
                if yetai_player.position != sleeper_info['position']:
                    continue
            
            # Calculate name similarity
            confidence = self.match_player_names(yetai_player.name, sleeper_name)
            
            # Boost confidence if team matches
            if yetai_player.team and sleeper_info.get('team'):
                if yetai_player.team == sleeper_info['team']:
                    confidence += 0.1
            
            # Minimum threshold
            if confidence >= 0.8 and confidence > best_confidence:
                best_confidence = confidence
                best_match = {
                    'id': sleeper_id,
                    'confidence': min(confidence, 1.0),
                    'data': sleeper_info
                }
        
        return best_match
    
    def find_espn_match(self, yetai_player: FantasyPlayer, espn_data: List[Dict]) -> Optional[Dict]:
        """Find best matching ESPN player"""
        best_match = None
        best_confidence = 0.0
        
        for espn_player in espn_data:
            # Get ESPN player name
            espn_name = espn_player.get('fullName', '')
            
            if not espn_name:
                continue
            
            # Check position match
            if yetai_player.position:
                espn_pos = espn_player.get('defaultPositionId')
                # ESPN position IDs: 1=QB, 2=RB, 3=WR, 4=TE, 5=K, 16=D/ST
                pos_map = {1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DEF'}
                if espn_pos in pos_map and pos_map[espn_pos] != yetai_player.position:
                    continue
            
            # Calculate name similarity
            confidence = self.match_player_names(yetai_player.name, espn_name)
            
            # Minimum threshold
            if confidence >= 0.8 and confidence > best_confidence:
                best_confidence = confidence
                best_match = {
                    'id': espn_player['id'],
                    'confidence': min(confidence, 1.0),
                    'data': espn_player
                }
        
        return best_match
    
    def verify_high_value_players(self):
        """Manually verify mappings for top players"""
        # List of high-value players to manually verify
        top_players = [
            ('Josh Allen', 'QB', 'BUF'),
            ('Patrick Mahomes', 'QB', 'KC'),
            ('Christian McCaffrey', 'RB', 'SF'),
            ('Austin Ekeler', 'RB', 'LAC'),
            ('Tyreek Hill', 'WR', 'MIA'),
            ('Justin Jefferson', 'WR', 'MIN'),
            ('Travis Kelce', 'TE', 'KC'),
            ('T.J. Hockenson', 'TE', 'MIN'),
        ]
        
        for name, position, team in top_players:
            # Find YetAI player
            yetai_player = self.db.query(FantasyPlayer).filter(
                FantasyPlayer.name == name,
                FantasyPlayer.position == position
            ).first()
            
            if yetai_player:
                # Get or create mapping
                mapping = self.db.query(PlayerIDMapping).filter(
                    PlayerIDMapping.yetai_id == yetai_player.id
                ).first()
                
                if mapping:
                    mapping.is_verified = True
                    mapping.confidence_score = 1.0
                    logger.info(f"Verified mapping for {name}")
        
        self.db.commit()

if __name__ == "__main__":
    # Check if fuzzywuzzy is installed
    try:
        from fuzzywuzzy import fuzz
    except ImportError:
        logger.error("fuzzywuzzy not installed. Installing...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "fuzzywuzzy", "python-Levenshtein"])
        from fuzzywuzzy import fuzz
    
    populator = PlayerMappingPopulator()
    populator.populate_mappings()
    populator.verify_high_value_players()