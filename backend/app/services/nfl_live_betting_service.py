"""
NFL-Specific Live Betting Service
Enhanced betting markets and features specifically for NFL games
"""
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import logging

from app.services.live_nfl_service import live_nfl_service, LiveNFLGame, LiveNFLOdds
from app.models.live_bet_models import (
    LiveBet, LiveBetStatus, GameStatus, LiveBettingMarket,
    PlaceLiveBetRequest, LiveBetResponse
)

logger = logging.getLogger(__name__)

@dataclass
class NFLLiveBettingMarket:
    """NFL-specific live betting market"""
    game_id: str
    home_team: str
    away_team: str
    
    # Game state
    quarter: int
    time_remaining: str
    home_score: int
    away_score: int
    possession: Optional[str]
    down_and_distance: Optional[str]
    field_position: Optional[str]
    
    # Standard markets
    moneyline_home: Optional[int]
    moneyline_away: Optional[int]
    spread_line: Optional[float]
    spread_home_odds: Optional[int]
    spread_away_odds: Optional[int]
    total_line: Optional[float]
    total_over_odds: Optional[int]
    total_under_odds: Optional[int]
    
    # NFL-specific in-game markets
    next_score_touchdown_odds: Optional[int]
    next_score_field_goal_odds: Optional[int]
    next_score_safety_odds: Optional[int]
    next_score_none_odds: Optional[int]
    
    # Drive outcome markets
    drive_result_touchdown: Optional[int]
    drive_result_field_goal: Optional[int]
    drive_result_punt: Optional[int]
    drive_result_turnover: Optional[int]
    
    # Player prop markets (if available)
    player_props: List[Dict[str, Any]]
    
    # Market availability
    is_suspended: bool
    suspension_reason: Optional[str]
    last_updated: datetime

class NFLLiveBettingService:
    """Service for NFL-specific live betting functionality"""
    
    def __init__(self):
        self.live_markets: Dict[str, NFLLiveBettingMarket] = {}
        self.nfl_bets: Dict[str, LiveBet] = {}
    
    async def get_nfl_live_markets(self) -> List[Dict[str, Any]]:
        """Get all available NFL live betting markets with enhanced data"""
        
        # Get live games and odds from the live NFL service
        live_games = await live_nfl_service.get_live_games()
        live_odds_list = await live_nfl_service.get_live_odds()
        
        # Create odds lookup
        odds_by_game = {odds['game_id']: odds for odds in live_odds_list}
        
        markets = []
        
        for game in live_games:
            try:
                game_id = game['game_id']
                odds = odds_by_game.get(game_id, {})
                
                # Only include games that are actually live or about to start
                if game['status'] in ['PRE', 'FINAL']:
                    continue
                
                # Create NFL-specific market
                market = await self._create_nfl_market(game, odds)
                if market:
                    markets.append(market)
                    
            except Exception as e:
                logger.error(f"Error creating NFL market for game {game.get('game_id')}: {e}")
                continue
        
        return markets
    
    async def _create_nfl_market(self, game: Dict, odds: Dict) -> Optional[Dict[str, Any]]:
        """Create NFL-specific betting market with enhanced features"""
        
        try:
            game_id = game['game_id']
            
            # Generate NFL-specific in-game odds
            next_score_odds = self._generate_next_score_odds(game)
            drive_odds = self._generate_drive_outcome_odds(game)
            player_props = self._generate_player_props(game)
            
            # Check if markets should be suspended
            is_suspended, suspension_reason = self._check_market_suspension(game)
            
            market_data = {
                'game_id': game_id,
                'sport': 'NFL',
                'home_team': game['home_team'],
                'away_team': game['away_team'],
                
                # Enhanced game state
                'quarter': game['quarter'],
                'time_remaining': game['time_remaining'],
                'home_score': game['home_score'],
                'away_score': game['away_score'],
                'possession': game.get('possession'),
                'down_and_distance': game.get('down_and_distance'),
                'field_position': game.get('field_position'),
                'last_play': game.get('last_play'),
                'status': game['status'],
                
                # Standard betting markets
                'moneyline_home': odds.get('moneyline_home'),
                'moneyline_away': odds.get('moneyline_away'),
                'spread_line': odds.get('spread_line'),
                'spread_home_odds': odds.get('spread_home_odds'),
                'spread_away_odds': odds.get('spread_away_odds'),
                'total_line': odds.get('total_line'),
                'total_over_odds': odds.get('total_over_odds'),
                'total_under_odds': odds.get('total_under_odds'),
                
                # NFL-specific markets
                'next_score': next_score_odds,
                'drive_outcome': drive_odds,
                'player_props': player_props,
                
                # Market status
                'markets_available': self._get_available_markets(game, is_suspended),
                'is_suspended': is_suspended,
                'suspension_reason': suspension_reason,
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
            return market_data
            
        except Exception as e:
            logger.error(f"Error creating NFL market: {e}")
            return None
    
    def _generate_next_score_odds(self, game: Dict) -> Dict[str, Any]:
        """Generate odds for next scoring play"""
        
        # Base odds that adjust based on game situation
        base_odds = {
            'touchdown': 250,  # +250
            'field_goal': 180,  # +180
            'safety': 2500,    # +2500
            'no_score': 150    # +150
        }
        
        # Adjust based on field position and down/distance
        field_pos = game.get('field_position', '')
        down_distance = game.get('down_and_distance', '')
        
        # If team is in red zone, increase touchdown odds
        if field_pos and 'red zone' in field_pos.lower():
            base_odds['touchdown'] = 120  # More likely
            base_odds['field_goal'] = 300  # Less likely
        
        # If it's 4th down, adjust accordingly
        if down_distance and '4th' in down_distance:
            base_odds['field_goal'] = 150  # More likely on 4th
            base_odds['no_score'] = 200    # Punt/turnover more likely
        
        return base_odds
    
    def _generate_drive_outcome_odds(self, game: Dict) -> Dict[str, Any]:
        """Generate odds for current drive outcome"""
        
        # Base drive outcome odds
        drive_odds = {
            'touchdown': 350,
            'field_goal': 280,
            'punt': 200,
            'turnover': 450,
            'turnover_on_downs': 800
        }
        
        # Adjust based on field position
        field_pos = game.get('field_position', '')
        if field_pos:
            if 'red zone' in field_pos.lower():
                drive_odds['touchdown'] = 180
                drive_odds['field_goal'] = 250
                drive_odds['punt'] = 1000  # Very unlikely in red zone
            elif 'midfield' in field_pos.lower():
                drive_odds['punt'] = 150
                drive_odds['field_goal'] = 200
        
        return drive_odds
    
    def _generate_player_props(self, game: Dict) -> List[Dict[str, Any]]:
        """Generate player prop betting options"""
        
        # In a real implementation, this would pull from:
        # - Current player statistics
        # - Live player tracking data
        # - Injury reports
        # - Weather conditions
        
        props = []
        
        # Example quarterback props
        if game.get('possession'):
            props.extend([
                {
                    'type': 'passing_yards_next_drive',
                    'player': 'Team QB',
                    'line': 25.5,
                    'over_odds': -110,
                    'under_odds': -110
                },
                {
                    'type': 'completion_next_pass',
                    'player': 'Team QB',
                    'yes_odds': -150,
                    'no_odds': 120
                }
            ])
        
        # Running back props
        props.extend([
            {
                'type': 'rushing_yards_next_play',
                'player': 'Team RB',
                'line': 4.5,
                'over_odds': -105,
                'under_odds': -115
            }
        ])
        
        return props
    
    def _check_market_suspension(self, game: Dict) -> tuple[bool, Optional[str]]:
        """Check if betting markets should be suspended"""
        
        status = game.get('status', '')
        time_remaining = game.get('time_remaining', '')
        
        # Suspend during timeouts, reviews, injuries, etc.
        suspension_keywords = [
            'timeout', 'review', 'injury', 'delay', 'penalty'
        ]
        
        last_play = game.get('last_play', '').lower()
        for keyword in suspension_keywords:
            if keyword in last_play:
                return True, f"Markets suspended due to {keyword}"
        
        # Suspend in final 2 minutes of each half for more accurate live odds
        if 'Q2' in status and time_remaining and ':' in time_remaining:
            try:
                minutes, seconds = time_remaining.split(':')
                if int(minutes) < 2:
                    return True, "Markets suspended - final 2 minutes of half"
            except:
                pass
        
        if 'Q4' in status and time_remaining and ':' in time_remaining:
            try:
                minutes, seconds = time_remaining.split(':')
                if int(minutes) < 2:
                    return True, "Markets suspended - final 2 minutes of game"
            except:
                pass
        
        return False, None
    
    def _get_available_markets(self, game: Dict, is_suspended: bool) -> List[str]:
        """Get list of available betting markets based on game state"""
        
        if is_suspended:
            return []
        
        markets = ['moneyline', 'spread', 'total']
        
        # Add NFL-specific markets based on game state
        status = game.get('status', '')
        
        if status in ['Q1', 'Q2', 'Q3', 'Q4']:
            markets.extend([
                'next_score',
                'drive_outcome'
            ])
        
        # Add player props if there's active possession
        if game.get('possession'):
            markets.append('player_props')
        
        # Quarter-specific markets
        if status == 'Q1':
            markets.append('first_quarter_winner')
        elif status == 'Q2':
            markets.append('first_half_winner')
        elif status in ['Q3', 'Q4']:
            markets.append('second_half_winner')
        
        return markets
    
    async def place_nfl_live_bet(self, user_id: int, request: PlaceLiveBetRequest) -> LiveBetResponse:
        """Place a live bet on NFL-specific markets"""
        
        # Get current game state
        game = await live_nfl_service.get_game_by_id(request.game_id)
        if not game:
            return LiveBetResponse(
                success=False,
                error="Game not found or not available for live betting"
            )
        
        # Check if game is still live
        if game['status'] in ['FINAL', 'PRE']:
            return LiveBetResponse(
                success=False,
                error="Game is not currently live"
            )
        
        # Check market-specific rules
        if request.bet_type in ['next_score', 'drive_outcome']:
            # These markets require active possession
            if not game.get('possession'):
                return LiveBetResponse(
                    success=False,
                    error="This market requires active possession"
                )
        
        # Check suspension status
        is_suspended, reason = self._check_market_suspension(game)
        if is_suspended:
            return LiveBetResponse(
                success=False,
                error=f"Market suspended: {reason}"
            )
        
        # Calculate potential win based on NFL odds
        potential_win = self._calculate_nfl_potential_win(request.amount, request.odds, request.bet_type)
        
        # Create the bet
        bet_id = str(uuid.uuid4())
        nfl_bet = LiveBet(
            id=bet_id,
            user_id=user_id,
            game_id=request.game_id,
            bet_type=request.bet_type,
            selection=request.selection,
            original_odds=request.odds,
            current_odds=request.odds,
            amount=request.amount,
            potential_win=potential_win,
            current_potential_win=potential_win,
            status=LiveBetStatus.ACTIVE,
            placed_at=datetime.now(timezone.utc),
            game_status_at_placement=game['status'],
            current_game_status=game['status'],
            home_score_at_placement=game['home_score'],
            away_score_at_placement=game['away_score'],
            current_home_score=game['home_score'],
            current_away_score=game['away_score'],
            cash_out_available=True,
            cash_out_value=request.amount * 0.95  # Initial cash out
        )
        
        self.nfl_bets[bet_id] = nfl_bet
        
        return LiveBetResponse(
            success=True,
            bet=nfl_bet,
            message=f"NFL live bet placed successfully for {game['away_team']} @ {game['home_team']}"
        )
    
    def _calculate_nfl_potential_win(self, amount: float, odds: int, bet_type: str) -> float:
        """Calculate potential win for NFL betting with special market adjustments"""
        
        # Standard American odds calculation
        if odds > 0:
            base_win = amount * (odds / 100)
        else:
            base_win = amount * (100 / abs(odds))
        
        # Apply any NFL-specific adjustments for special markets
        if bet_type in ['next_score', 'drive_outcome']:
            # These markets might have different calculation rules
            pass
        
        return base_win
    
    async def get_nfl_bet_history(self, user_id: int) -> List[Dict[str, Any]]:
        """Get user's NFL live betting history"""
        
        user_bets = [
            bet for bet in self.nfl_bets.values() 
            if bet.user_id == user_id
        ]
        
        # Add game context to each bet
        enriched_bets = []
        for bet in user_bets:
            game = await live_nfl_service.get_game_by_id(bet.game_id)
            bet_dict = bet.__dict__.copy()
            bet_dict['game_context'] = game
            enriched_bets.append(bet_dict)
        
        return sorted(enriched_bets, key=lambda x: x['placed_at'], reverse=True)

# Global instance
nfl_live_betting_service = NFLLiveBettingService()