"""
Complete Live NFL Data Service
Provides real-time NFL game scores, odds, and betting markets
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import aiohttp
import json
from dataclasses import dataclass

from app.core.config import settings
from app.services.odds_api_service import OddsAPIService, SportKey, MarketKey, OddsFormat

logger = logging.getLogger(__name__)

@dataclass
class LiveNFLGame:
    """Live NFL game data structure"""
    game_id: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    quarter: int
    time_remaining: str
    status: str  # PRE, LIVE, FINAL, HALFTIME
    possession: Optional[str]
    down_and_distance: Optional[str]
    field_position: Optional[str]
    last_play: Optional[str]
    commence_time: datetime
    last_updated: datetime

@dataclass 
class LiveNFLOdds:
    """Live NFL odds data structure"""
    game_id: str
    home_team: str
    away_team: str
    moneyline_home: Optional[int]
    moneyline_away: Optional[int]
    spread_line: Optional[float]
    spread_home_odds: Optional[int]
    spread_away_odds: Optional[int]
    total_line: Optional[float]
    total_over_odds: Optional[int]
    total_under_odds: Optional[int]
    last_updated: datetime

class LiveNFLService:
    """Service for live NFL data aggregation from multiple sources"""
    
    def __init__(self):
        self.live_games: Dict[str, LiveNFLGame] = {}
        self.live_odds: Dict[str, LiveNFLOdds] = {}
        self.update_interval = 15  # seconds
        self.running = False
        
    async def start_live_updates(self):
        """Start continuous live data updates"""
        self.running = True
        logger.info("Starting live NFL data updates...")
        
        # Create background tasks for different data sources
        tasks = [
            asyncio.create_task(self._update_scores_loop()),
            asyncio.create_task(self._update_odds_loop()),
        ]
        
        try:
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"Error in live updates: {e}")
        finally:
            self.running = False

    async def stop_live_updates(self):
        """Stop live data updates"""
        self.running = False
        logger.info("Stopping live NFL data updates")

    async def _update_scores_loop(self):
        """Continuous loop to update live game scores"""
        while self.running:
            try:
                await self._fetch_live_scores()
                await asyncio.sleep(self.update_interval)
            except Exception as e:
                logger.error(f"Error updating scores: {e}")
                await asyncio.sleep(30)  # Wait longer on error

    async def _update_odds_loop(self):
        """Continuous loop to update live odds"""
        while self.running:
            try:
                await self._fetch_live_odds()
                await asyncio.sleep(self.update_interval * 2)  # Update odds less frequently
            except Exception as e:
                logger.error(f"Error updating odds: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def _fetch_live_scores(self):
        """Fetch live NFL scores from multiple sources"""
        try:
            # Try ESPN API first
            espn_games = await self._fetch_espn_scores()
            
            # Try CBS Sports API as backup
            if not espn_games:
                cbs_games = await self._fetch_cbs_scores()
                
            # Try NFL.com API as another backup
            if not espn_games:
                nfl_games = await self._fetch_nfl_com_scores()
                
            logger.info(f"Updated {len(self.live_games)} live NFL games")
            
        except Exception as e:
            logger.error(f"Error fetching live scores: {e}")

    async def _fetch_espn_scores(self) -> List[LiveNFLGame]:
        """Fetch live scores from ESPN API"""
        try:
            url = "http://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return await self._process_espn_data(data)
                    else:
                        logger.warning(f"ESPN API returned status {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching ESPN scores: {e}")
            return []

    async def _process_espn_data(self, data: Dict) -> List[LiveNFLGame]:
        """Process ESPN scoreboard data"""
        games = []
        
        try:
            events = data.get('events', [])
            
            for event in events:
                game_id = event.get('id')
                if not game_id:
                    continue
                
                # Extract teams
                competitions = event.get('competitions', [])
                if not competitions:
                    continue
                    
                competition = competitions[0]
                competitors = competition.get('competitors', [])
                
                if len(competitors) != 2:
                    continue
                
                home_team = None
                away_team = None
                home_score = 0
                away_score = 0
                
                for competitor in competitors:
                    team_name = competitor.get('team', {}).get('displayName', '')
                    score = int(competitor.get('score', 0))
                    
                    if competitor.get('homeAway') == 'home':
                        home_team = team_name
                        home_score = score
                    else:
                        away_team = team_name
                        away_score = score
                
                # Extract game status
                status = event.get('status', {})
                status_type = status.get('type', {}).get('name', 'PRE')
                period = status.get('period', 0)
                display_clock = status.get('displayClock', '0:00')
                
                # Convert to our status format
                game_status = self._convert_espn_status(status_type, period)
                
                # Extract additional live data
                situation = competition.get('situation', {})
                possession = situation.get('possession')
                down_distance = situation.get('downDistanceText')
                
                # Get commence time
                commence_time_str = event.get('date')
                commence_time = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00')) if commence_time_str else datetime.now(timezone.utc)
                
                game = LiveNFLGame(
                    game_id=game_id,
                    home_team=home_team,
                    away_team=away_team,
                    home_score=home_score,
                    away_score=away_score,
                    quarter=period,
                    time_remaining=display_clock,
                    status=game_status,
                    possession=possession,
                    down_and_distance=down_distance,
                    field_position=situation.get('yardLine'),
                    last_play=situation.get('lastPlay', {}).get('text'),
                    commence_time=commence_time,
                    last_updated=datetime.now(timezone.utc)
                )
                
                self.live_games[game_id] = game
                games.append(game)
                
        except Exception as e:
            logger.error(f"Error processing ESPN data: {e}")
        
        return games

    async def _fetch_cbs_scores(self) -> List[LiveNFLGame]:
        """Fetch live scores from CBS Sports API (backup)"""
        try:
            url = "https://www.cbssports.com/api/1/sports/football/nfl/games/scores"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return await self._process_cbs_data(data)
                    else:
                        logger.warning(f"CBS API returned status {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching CBS scores: {e}")
            return []

    async def _process_cbs_data(self, data: Dict) -> List[LiveNFLGame]:
        """Process CBS Sports data"""
        games = []
        # Implementation would be similar to ESPN processing
        # but adapted to CBS data structure
        return games

    async def _fetch_nfl_com_scores(self) -> List[LiveNFLGame]:
        """Fetch live scores from NFL.com API (backup)"""
        try:
            # NFL.com has various endpoints for live data
            url = "https://api.nfl.com/v1/current/games"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return await self._process_nfl_com_data(data)
                    else:
                        logger.warning(f"NFL.com API returned status {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching NFL.com scores: {e}")
            return []

    async def _process_nfl_com_data(self, data: Dict) -> List[LiveNFLGame]:
        """Process NFL.com data"""
        games = []
        # Implementation would process NFL.com specific data structure
        return games

    async def _fetch_live_odds(self):
        """Fetch live NFL odds from The Odds API"""
        try:
            if not settings.ODDS_API_KEY:
                logger.warning("No Odds API key configured - skipping odds updates")
                return
            
            async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
                odds_data = await odds_service.get_odds(
                    sport=SportKey.AMERICANFOOTBALL_NFL.value,
                    markets=[MarketKey.H2H.value, MarketKey.SPREADS.value, MarketKey.TOTALS.value],
                    regions=['us'],
                    odds_format=OddsFormat.AMERICAN
                )
                
                await self._process_odds_data(odds_data)
                logger.info(f"Updated odds for {len(self.live_odds)} NFL games")
                
        except Exception as e:
            logger.error(f"Error fetching live odds: {e}")

    async def _process_odds_data(self, odds_data):
        """Process odds data from The Odds API"""
        try:
            games_data = odds_data if isinstance(odds_data, list) else odds_data.get('data', [])
            
            for game in games_data:
                game_id = game.id if hasattr(game, 'id') else game.get('id')
                home_team = game.home_team if hasattr(game, 'home_team') else game.get('home_team')
                away_team = game.away_team if hasattr(game, 'away_team') else game.get('away_team')
                
                # Extract odds from bookmakers
                bookmakers = game.bookmakers if hasattr(game, 'bookmakers') else game.get('bookmakers', [])
                if not bookmakers:
                    continue
                
                # Use first bookmaker for simplicity
                bookmaker = bookmakers[0]
                markets = bookmaker.markets if hasattr(bookmaker, 'markets') else bookmaker.get('markets', [])
                
                odds = LiveNFLOdds(
                    game_id=game_id,
                    home_team=home_team,
                    away_team=away_team,
                    moneyline_home=None,
                    moneyline_away=None,
                    spread_line=None,
                    spread_home_odds=None,
                    spread_away_odds=None,
                    total_line=None,
                    total_over_odds=None,
                    total_under_odds=None,
                    last_updated=datetime.now(timezone.utc)
                )
                
                # Extract different market types
                for market in markets:
                    market_key = market.key if hasattr(market, 'key') else market.get('key')
                    outcomes = market.outcomes if hasattr(market, 'outcomes') else market.get('outcomes', [])
                    
                    if market_key == 'h2h':
                        for outcome in outcomes:
                            name = outcome.name if hasattr(outcome, 'name') else outcome.get('name')
                            price = outcome.price if hasattr(outcome, 'price') else outcome.get('price')
                            
                            if name == home_team:
                                odds.moneyline_home = price
                            elif name == away_team:
                                odds.moneyline_away = price
                    
                    elif market_key == 'spreads':
                        for outcome in outcomes:
                            name = outcome.name if hasattr(outcome, 'name') else outcome.get('name')
                            price = outcome.price if hasattr(outcome, 'price') else outcome.get('price')
                            point = outcome.point if hasattr(outcome, 'point') else outcome.get('point')
                            
                            if name == home_team:
                                odds.spread_line = point
                                odds.spread_home_odds = price
                            elif name == away_team:
                                odds.spread_away_odds = price
                    
                    elif market_key == 'totals':
                        for outcome in outcomes:
                            name = outcome.name if hasattr(outcome, 'name') else outcome.get('name')
                            price = outcome.price if hasattr(outcome, 'price') else outcome.get('price')
                            point = outcome.point if hasattr(outcome, 'point') else outcome.get('point')
                            
                            if name == 'Over':
                                odds.total_line = point
                                odds.total_over_odds = price
                            elif name == 'Under':
                                odds.total_under_odds = price
                
                self.live_odds[game_id] = odds
                
        except Exception as e:
            logger.error(f"Error processing odds data: {e}")

    def _convert_espn_status(self, status_type: str, period: int) -> str:
        """Convert ESPN status to our format"""
        if status_type in ['STATUS_SCHEDULED', 'STATUS_PREGAME']:
            return 'PRE'
        elif status_type == 'STATUS_FINAL':
            return 'FINAL'
        elif status_type == 'STATUS_HALFTIME':
            return 'HALFTIME'
        elif status_type in ['STATUS_IN_PROGRESS', 'STATUS_ACTIVE']:
            if period == 1:
                return 'Q1'
            elif period == 2:
                return 'Q2'
            elif period == 3:
                return 'Q3'
            elif period == 4:
                return 'Q4'
            elif period > 4:
                return 'OT'
            else:
                return 'LIVE'
        else:
            return 'LIVE'

    async def get_live_games(self) -> List[Dict[str, Any]]:
        """Get current live NFL games"""
        return [
            {
                'game_id': game.game_id,
                'home_team': game.home_team,
                'away_team': game.away_team,
                'home_score': game.home_score,
                'away_score': game.away_score,
                'quarter': game.quarter,
                'time_remaining': game.time_remaining,
                'status': game.status,
                'possession': game.possession,
                'down_and_distance': game.down_and_distance,
                'field_position': game.field_position,
                'last_play': game.last_play,
                'commence_time': game.commence_time.isoformat(),
                'last_updated': game.last_updated.isoformat()
            }
            for game in self.live_games.values()
        ]

    async def get_live_odds(self) -> List[Dict[str, Any]]:
        """Get current live NFL odds"""
        return [
            {
                'game_id': odds.game_id,
                'home_team': odds.home_team,
                'away_team': odds.away_team,
                'moneyline_home': odds.moneyline_home,
                'moneyline_away': odds.moneyline_away,
                'spread_line': odds.spread_line,
                'spread_home_odds': odds.spread_home_odds,
                'spread_away_odds': odds.spread_away_odds,
                'total_line': odds.total_line,
                'total_over_odds': odds.total_over_odds,
                'total_under_odds': odds.total_under_odds,
                'last_updated': odds.last_updated.isoformat()
            }
            for odds in self.live_odds.values()
        ]

    async def get_game_by_id(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get specific live game by ID"""
        game = self.live_games.get(game_id)
        if not game:
            return None
        
        return {
            'game_id': game.game_id,
            'home_team': game.home_team,
            'away_team': game.away_team,
            'home_score': game.home_score,
            'away_score': game.away_score,
            'quarter': game.quarter,
            'time_remaining': game.time_remaining,
            'status': game.status,
            'possession': game.possession,
            'down_and_distance': game.down_and_distance,
            'field_position': game.field_position,
            'last_play': game.last_play,
            'commence_time': game.commence_time.isoformat(),
            'last_updated': game.last_updated.isoformat()
        }

    async def get_odds_by_game_id(self, game_id: str) -> Optional[Dict[str, Any]]:
        """Get specific live odds by game ID"""
        odds = self.live_odds.get(game_id)
        if not odds:
            return None
        
        return {
            'game_id': odds.game_id,
            'home_team': odds.home_team,
            'away_team': odds.away_team,
            'moneyline_home': odds.moneyline_home,
            'moneyline_away': odds.moneyline_away,
            'spread_line': odds.spread_line,
            'spread_home_odds': odds.spread_home_odds,
            'spread_away_odds': odds.spread_away_odds,
            'total_line': odds.total_line,
            'total_over_odds': odds.total_over_odds,
            'total_under_odds': odds.total_under_odds,
            'last_updated': odds.last_updated.isoformat()
        }

# Global instance
live_nfl_service = LiveNFLService()