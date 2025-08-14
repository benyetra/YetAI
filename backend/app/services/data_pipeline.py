"""
Sports Data Pipeline Service
Handles fetching data from ESPN API and Odds API
"""

import asyncio
import aiohttp
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import os
from app.core.config import settings

class SportsDataPipeline:
    """Main class for sports data pipeline operations"""
    
    def __init__(self):
        self.odds_api_key = settings.ODDS_API_KEY
        self.espn_base_url = "https://site.api.espn.com/apis/site/v2/sports"
        self.odds_base_url = "https://api.the-odds-api.com/v4/sports"
        
    async def get_nfl_games_today(self) -> List[Dict[str, Any]]:
        """Fetch today's NFL games from ESPN API"""
        try:
            url = f"{self.espn_base_url}/football/nfl/scoreboard"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        games = self._parse_espn_games(data)
                        return games
                    else:
                        print(f"ESPN API error: {response.status}")
                        return self._get_mock_games()
        except Exception as e:
            print(f"Error fetching ESPN games: {e}")
            return self._get_mock_games()
    
    async def get_nfl_odds(self) -> List[Dict[str, Any]]:
        """Fetch NFL odds from Odds API"""
        if not self.odds_api_key or self.odds_api_key == "your_odds_api_key_here":
            return self._get_mock_odds()
        
        try:
            url = f"{self.odds_base_url}/americanfootball_nfl/odds"
            params = {
                'apiKey': self.odds_api_key,
                'regions': 'us',
                'markets': 'h2h,spreads,totals',
                'oddsFormat': 'american'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        odds = self._parse_odds_data(data)
                        return odds
                    else:
                        print(f"Odds API error: {response.status}")
                        return self._get_mock_odds()
        except Exception as e:
            print(f"Error fetching odds: {e}")
            return self._get_mock_odds()
    
    def generate_simple_predictions(self, games: List[Dict], odds: List[Dict]) -> List[Dict[str, Any]]:
        """Generate simple AI predictions based on games and odds"""
        predictions = []
        
        for game in games:
            game_id = game.get('id')
            home_team = game.get('home_team')
            away_team = game.get('away_team')
            
            # Find corresponding odds
            game_odds = None
            for odd in odds:
                if odd.get('home_team') == home_team and odd.get('away_team') == away_team:
                    game_odds = odd
                    break
            
            if game_odds:
                prediction = self._create_prediction(game, game_odds)
                predictions.append(prediction)
        
        return predictions
    
    def _parse_espn_games(self, data: Dict) -> List[Dict[str, Any]]:
        """Parse ESPN API response"""
        games = []
        
        try:
            events = data.get('events', [])
            for event in events[:5]:  # Limit to 5 games
                competition = event.get('competitions', [{}])[0]
                competitors = competition.get('competitors', [])
                
                if len(competitors) >= 2:
                    home_team = competitors[0]['team']['displayName']
                    away_team = competitors[1]['team']['displayName']
                    
                    game = {
                        'id': event.get('id'),
                        'home_team': home_team,
                        'away_team': away_team,
                        'date': event.get('date'),
                        'status': competition.get('status', {}).get('type', {}).get('description', 'Scheduled'),
                        'venue': competition.get('venue', {}).get('fullName', 'TBD')
                    }
                    games.append(game)
        except Exception as e:
            print(f"Error parsing ESPN data: {e}")
        
        return games
    
    def _parse_odds_data(self, data: List) -> List[Dict[str, Any]]:
        """Parse Odds API response"""
        odds = []
        
        try:
            for game in data[:5]:  # Limit to 5 games
                home_team = game.get('home_team')
                away_team = game.get('away_team')
                
                bookmaker = game.get('bookmakers', [{}])[0]
                markets = bookmaker.get('markets', [])
                
                game_odds = {
                    'home_team': home_team,
                    'away_team': away_team,
                    'commence_time': game.get('commence_time'),
                    'moneyline': {},
                    'spread': {},
                    'total': {}
                }
                
                for market in markets:
                    market_key = market.get('key')
                    outcomes = market.get('outcomes', [])
                    
                    if market_key == 'h2h':  # Moneyline
                        for outcome in outcomes:
                            if outcome.get('name') == home_team:
                                game_odds['moneyline']['home'] = outcome.get('price')
                            elif outcome.get('name') == away_team:
                                game_odds['moneyline']['away'] = outcome.get('price')
                    
                    elif market_key == 'spreads':  # Point spread
                        for outcome in outcomes:
                            if outcome.get('name') == home_team:
                                game_odds['spread']['home'] = {
                                    'point': outcome.get('point'),
                                    'price': outcome.get('price')
                                }
                            elif outcome.get('name') == away_team:
                                game_odds['spread']['away'] = {
                                    'point': outcome.get('point'),
                                    'price': outcome.get('price')
                                }
                
                odds.append(game_odds)
        except Exception as e:
            print(f"Error parsing odds data: {e}")
        
        return odds
    
    def _create_prediction(self, game: Dict, odds: Dict) -> Dict[str, Any]:
        """Create AI prediction for a game"""
        home_team = game.get('home_team')
        away_team = game.get('away_team')
        
        # Simple prediction logic (replace with actual AI model)
        home_ml = odds.get('moneyline', {}).get('home', 0)
        away_ml = odds.get('moneyline', {}).get('away', 0)
        
        # Favorite is the team with negative moneyline
        if home_ml < 0 and abs(home_ml) > abs(away_ml):
            predicted_winner = home_team
            confidence = min(90, abs(home_ml) / 10)
        elif away_ml < 0 and abs(away_ml) > abs(home_ml):
            predicted_winner = away_team
            confidence = min(90, abs(away_ml) / 10)
        else:
            predicted_winner = home_team  # Default to home
            confidence = 55
        
        return {
            'game_id': game.get('id'),
            'home_team': home_team,
            'away_team': away_team,
            'predicted_winner': predicted_winner,
            'confidence': round(confidence, 1),
            'recommended_bet': 'moneyline',
            'reasoning': f"Based on odds analysis, {predicted_winner} is favored",
            'risk_level': 'medium' if confidence > 60 else 'high',
            'timestamp': datetime.now().isoformat()
        }
    
    def _get_mock_games(self) -> List[Dict[str, Any]]:
        """Return mock games data when APIs fail"""
        return [
            {
                'id': 'mock_001',
                'home_team': 'Kansas City Chiefs',
                'away_team': 'Buffalo Bills',
                'date': '2024-01-01T13:00:00Z',
                'status': 'Scheduled',
                'venue': 'Arrowhead Stadium'
            },
            {
                'id': 'mock_002',
                'home_team': 'Dallas Cowboys',
                'away_team': 'Philadelphia Eagles',
                'date': '2024-01-01T16:30:00Z',
                'status': 'Scheduled',
                'venue': 'AT&T Stadium'
            }
        ]
    
    def _get_mock_odds(self) -> List[Dict[str, Any]]:
        """Return mock odds data when API fails"""
        return [
            {
                'home_team': 'Kansas City Chiefs',
                'away_team': 'Buffalo Bills',
                'commence_time': '2024-01-01T13:00:00Z',
                'moneyline': {'home': -150, 'away': +130},
                'spread': {
                    'home': {'point': -3.5, 'price': -110},
                    'away': {'point': +3.5, 'price': -110}
                }
            },
            {
                'home_team': 'Dallas Cowboys',
                'away_team': 'Philadelphia Eagles',
                'commence_time': '2024-01-01T16:30:00Z',
                'moneyline': {'home': +110, 'away': -130},
                'spread': {
                    'home': {'point': +2.5, 'price': -110},
                    'away': {'point': -2.5, 'price': -110}
                }
            }
        ]

# Create global instance
sports_pipeline = SportsDataPipeline()