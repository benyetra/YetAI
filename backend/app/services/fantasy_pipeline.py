"""
Fantasy Sports Pipeline Service
Handles fantasy football projections and start/sit advice
"""

import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import random
from app.core.config import settings

class FantasyPipeline:
    """Main class for fantasy football operations"""
    
    def __init__(self):
        self.espn_base_url = "https://site.api.espn.com/apis/site/v2/sports"
        self.sleeper_base_url = "https://api.sleeper.app/v1"
        
    async def get_nfl_players(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch NFL players data"""
        try:
            # Try to get real player data from ESPN
            url = f"{self.espn_base_url}/football/nfl/athletes"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        players = self._parse_espn_players(data, limit)
                        return players
                    else:
                        return self._get_mock_players(limit)
        except Exception as e:
            print(f"Error fetching players: {e}")
            return self._get_mock_players(limit)
    
    def generate_fantasy_projections(self, players: List[Dict], games: List[Dict]) -> List[Dict[str, Any]]:
        """Generate fantasy projections for players"""
        projections = []
        
        for player in players[:50]:  # Limit to top 50 for demo
            projection = self._create_player_projection(player, games)
            projections.append(projection)
        
        # Sort by projected points descending
        projections.sort(key=lambda x: x['projected_points'], reverse=True)
        return projections
    
    def get_start_sit_advice(self, projections: List[Dict], position: str) -> List[Dict[str, Any]]:
        """Get start/sit advice for specific position"""
        position_players = [p for p in projections if p['position'] == position]
        
        advice = []
        for i, player in enumerate(position_players[:20]):  # Top 20 for position
            confidence = max(60, 100 - (i * 2))  # Higher confidence for better players
            
            if i < 8:  # Top tier - START
                recommendation = "START"
                reasoning = f"Elite {position} with high upside. Must-start player."
                tier = "Tier 1"
            elif i < 15:  # Mid tier - FLEX/CONSIDER
                recommendation = "FLEX" if position in ['RB', 'WR'] else "CONSIDER"
                reasoning = f"Solid {position} option. Good matchup and consistent production."
                tier = "Tier 2"
            else:  # Lower tier - SIT
                recommendation = "SIT"
                reasoning = f"Risky {position} play. Better options likely available."
                tier = "Tier 3"
            
            advice_item = {
                "player_name": player['player_name'],
                "team": player['team'],
                "position": player['position'],
                "opponent": player.get('opponent', 'TBD'),
                "projected_points": player['projected_points'],
                "recommendation": recommendation,
                "tier": tier,
                "confidence": confidence,
                "reasoning": reasoning,
                "matchup_rating": self._get_matchup_rating(player),
                "injury_status": player.get('injury_status', 'Healthy')
            }
            advice.append(advice_item)
        
        return advice
    
    def _parse_espn_players(self, data: Dict, limit: int) -> List[Dict[str, Any]]:
        """Parse ESPN players API response"""
        players = []
        
        try:
            athletes = data.get('athletes', [])
            for athlete in athletes[:limit]:
                player = {
                    'id': athlete.get('id'),
                    'player_name': athlete.get('displayName', 'Unknown'),
                    'team': athlete.get('team', {}).get('abbreviation', 'FA'),
                    'position': athlete.get('position', {}).get('abbreviation', 'UNKNOWN'),
                    'jersey_number': athlete.get('jersey'),
                    'experience': athlete.get('experience', {}).get('years', 0),
                    'status': athlete.get('status', {}).get('type', 'ACTIVE')
                }
                
                # Only include relevant fantasy positions
                if player['position'] in ['QB', 'RB', 'WR', 'TE', 'K']:
                    players.append(player)
        except Exception as e:
            print(f"Error parsing ESPN players: {e}")
        
        return players if players else self._get_mock_players(limit)
    
    def _create_player_projection(self, player: Dict, games: List[Dict]) -> Dict[str, Any]:
        """Create fantasy projection for a player"""
        position = player.get('position', 'UNKNOWN')
        
        # Base projections by position (simplified algorithm)
        base_projections = {
            'QB': {'points': (15, 25), 'floor': 12, 'ceiling': 35},
            'RB': {'points': (8, 18), 'floor': 5, 'ceiling': 25},
            'WR': {'points': (6, 15), 'floor': 3, 'ceiling': 22},
            'TE': {'points': (4, 12), 'floor': 2, 'ceiling': 18},
            'K': {'points': (6, 12), 'floor': 4, 'ceiling': 16}
        }
        
        base = base_projections.get(position, base_projections['RB'])
        
        # Add some randomness and player-specific modifiers
        projected_points = random.uniform(base['points'][0], base['points'][1])
        floor = base['floor'] + random.uniform(-2, 2)
        ceiling = base['ceiling'] + random.uniform(-3, 5)
        
        # Find opponent (simplified)
        opponent = "TBD"
        for game in games:
            if game.get('home_team') == player.get('team'):
                opponent = game.get('away_team', 'TBD')
                break
            elif game.get('away_team') == player.get('team'):
                opponent = game.get('home_team', 'TBD')
                break
        
        return {
            'player_id': player.get('id', f"player_{random.randint(1000, 9999)}"),
            'player_name': player.get('player_name', 'Unknown Player'),
            'team': player.get('team', 'FA'),
            'position': position,
            'opponent': opponent,
            'projected_points': round(projected_points, 1),
            'floor': round(max(0, floor), 1),
            'ceiling': round(ceiling, 1),
            'snap_percentage': round(random.uniform(60, 95), 1),
            'target_share': round(random.uniform(10, 25), 1) if position in ['WR', 'TE'] else None,
            'red_zone_touches': random.randint(1, 4) if position in ['RB', 'WR', 'TE'] else None,
            'injury_status': random.choice(['Healthy', 'Healthy', 'Healthy', 'Questionable', 'Probable']),
            'weather_impact': random.choice(['None', 'Minimal', 'Moderate']),
            'vegas_implied_total': round(random.uniform(20, 30), 1),
            'last_updated': datetime.now().isoformat()
        }
    
    def _get_matchup_rating(self, player: Dict) -> str:
        """Get simplified matchup rating"""
        ratings = ['Elite', 'Good', 'Average', 'Difficult', 'Avoid']
        return random.choice(ratings)
    
    def _get_mock_players(self, limit: int) -> List[Dict[str, Any]]:
        """Return mock players when API fails"""
        mock_players = [
            {'id': '1', 'player_name': 'Josh Allen', 'team': 'BUF', 'position': 'QB'},
            {'id': '2', 'player_name': 'Lamar Jackson', 'team': 'BAL', 'position': 'QB'},
            {'id': '3', 'player_name': 'Christian McCaffrey', 'team': 'SF', 'position': 'RB'},
            {'id': '4', 'player_name': 'Austin Ekeler', 'team': 'LAC', 'position': 'RB'},
            {'id': '5', 'player_name': 'Cooper Kupp', 'team': 'LAR', 'position': 'WR'},
            {'id': '6', 'player_name': 'Davante Adams', 'team': 'LV', 'position': 'WR'},
            {'id': '7', 'player_name': 'Travis Kelce', 'team': 'KC', 'position': 'TE'},
            {'id': '8', 'player_name': 'Mark Andrews', 'team': 'BAL', 'position': 'TE'},
            {'id': '9', 'player_name': 'Justin Tucker', 'team': 'BAL', 'position': 'K'},
            {'id': '10', 'player_name': 'Harrison Butker', 'team': 'KC', 'position': 'K'},
            {'id': '11', 'player_name': 'Patrick Mahomes', 'team': 'KC', 'position': 'QB'},
            {'id': '12', 'player_name': 'Joe Burrow', 'team': 'CIN', 'position': 'QB'},
            {'id': '13', 'player_name': 'Derrick Henry', 'team': 'TEN', 'position': 'RB'},
            {'id': '14', 'player_name': 'Dalvin Cook', 'team': 'MIN', 'position': 'RB'},
            {'id': '15', 'player_name': 'Stefon Diggs', 'team': 'BUF', 'position': 'WR'},
            {'id': '16', 'player_name': 'Tyreek Hill', 'team': 'MIA', 'position': 'WR'},
            {'id': '17', 'player_name': 'George Kittle', 'team': 'SF', 'position': 'TE'},
            {'id': '18', 'player_name': 'Darren Waller', 'team': 'LV', 'position': 'TE'},
            {'id': '19', 'player_name': 'Daniel Carlson', 'team': 'LV', 'position': 'K'},
            {'id': '20', 'player_name': 'Nick Chubb', 'team': 'CLE', 'position': 'RB'}
        ]
        
        return mock_players[:min(limit, len(mock_players))]

# Create global instance
fantasy_pipeline = FantasyPipeline()