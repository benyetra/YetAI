"""
Database-powered live betting service for persistent storage
"""
import random
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.core.database import SessionLocal
from app.models.database_models import User, LiveBet as LiveBetDB, BetStatus
from app.models.live_bet_models import (
    LiveBet, LiveBetStatus, GameStatus, 
    LiveOddsUpdate, LiveGameUpdate,
    CashOutOffer, LiveBettingMarket,
    PlaceLiveBetRequest, LiveBetResponse,
    CashOutHistory
)
from app.services.odds_api_service import OddsAPIService, SportKey, MarketKey, OddsFormat
from app.core.config import settings

logger = logging.getLogger(__name__)

class LiveBettingServiceDB:
    """Database-powered live betting service with persistent storage"""
    
    def __init__(self):
        # In-memory caches for real-time data that doesn't need persistence
        self.live_games: Dict[str, LiveGameUpdate] = {}
        self.live_odds: Dict[str, LiveOddsUpdate] = {}
        self.cash_out_offers: Dict[str, CashOutOffer] = {}
        self.suspended_markets: set = set()
        # Cache for consistent game states
        self.game_state_cache: Dict[str, Dict] = {}
        self.cache_timestamp: Optional[datetime] = None
        # Cache for game team names and sport details
        self.game_details_cache: Dict[str, tuple] = {}
        # Cache markets for bet placement
        self.cached_markets: List[LiveBettingMarket] = []
        
    async def get_real_live_scores(self, sport_key: str) -> Dict[str, Any]:
        """Fetch real live scores from The Odds API"""
        try:
            async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
                scores = await odds_service.get_scores(sport_key, days_from=1)
                
                # Convert scores to a game_id -> score mapping
                live_scores = {}
                for score in scores:
                    # Only include games that are live or recently completed
                    if not score.completed and score.home_score is not None and score.away_score is not None:
                        live_scores[score.id] = {
                            'home_score': score.home_score,
                            'away_score': score.away_score,
                            'home_team': score.home_team,
                            'away_team': score.away_team,
                            'sport': score.sport_title,
                            'completed': score.completed,
                            'last_update': score.last_update
                        }
                
                logger.info(f"Fetched {len(live_scores)} live scores for {sport_key}")
                return live_scores
                
        except Exception as e:
            logger.error(f"Failed to fetch live scores for {sport_key}: {e}")
            return {}
    
    def place_live_bet(self, user_id: int, request: PlaceLiveBetRequest) -> LiveBetResponse:
        """Place a live bet during a game with database persistence"""
        
        # Import required models at the top of the function
        from app.models.live_bet_models import LiveGameUpdate, GameStatus
        import random
        
        # Check if market is suspended
        if request.game_id in self.suspended_markets:
            return LiveBetResponse(
                success=False,
                error="Market temporarily suspended. Please try again in a moment."
            )
        
        # Get current game state or create one for test games
        game_state = self.live_games.get(request.game_id)
        if not game_state:
            # Try to find the game in cached markets and create a game state
            for market in self.cached_markets:
                if market.game_id == request.game_id:
                    game_state = LiveGameUpdate(
                        game_id=request.game_id,
                        status=market.game_status,
                        home_score=market.home_score,
                        away_score=market.away_score,
                        time_remaining=market.time_remaining or "",
                        timestamp=datetime.utcnow()
                    )
                    self.live_games[request.game_id] = game_state
                    
                    # Also populate odds cache
                    self.live_odds[request.game_id] = {
                        'moneyline': {
                            'home': market.moneyline_home,
                            'away': market.moneyline_away
                        },
                        'spread': {
                            'point': market.spread_line,
                            'home_odds': market.spread_home_odds,
                            'away_odds': market.spread_away_odds
                        } if market.spread_line else {},
                        'total': {
                            'point': market.total_line,
                            'over_odds': market.total_over_odds,
                            'under_odds': market.total_under_odds
                        } if market.total_line else {}
                    }
                    break
            
            if not game_state:
                return LiveBetResponse(
                    success=False,
                    error="Game not available for live betting - please refresh markets first"
                )
        
        # Check if game is still live
        if game_state.status in [GameStatus.FINAL, GameStatus.CANCELLED, GameStatus.POSTPONED]:
            return LiveBetResponse(
                success=False,
                error="Game has ended or is not available"
            )
        
        # Get current odds
        current_odds_data = self.live_odds.get(request.game_id)
        current_odds = request.odds  # Default to requested odds
        
        # Check for odds changes
        odds_changed = False
        if current_odds_data:
            # Compare with current market odds
            market_odds = self._get_market_odds(current_odds_data, request.bet_type, request.selection)
            if market_odds and abs(market_odds - request.odds) > 0.05:
                odds_changed = True
                current_odds = market_odds
                
                # Check if user accepts odds changes
                if not request.accept_odds_change:
                    return LiveBetResponse(
                        success=False,
                        error="Odds have changed",
                        odds_changed=True,
                        new_odds=current_odds
                    )
                
                # Check minimum acceptable odds
                if request.min_odds and current_odds < request.min_odds:
                    return LiveBetResponse(
                        success=False,
                        error=f"Current odds {current_odds} below minimum {request.min_odds}",
                        odds_changed=True,
                        new_odds=current_odds
                    )
        
        # Calculate potential win
        potential_win = self._calculate_potential_win(request.amount, current_odds)
        
        # Save to database
        try:
            db = SessionLocal()
            try:
                bet_id = str(uuid.uuid4())
                
                # Get real team names from cached markets or create reasonable defaults
                home_team, away_team, sport = self._get_game_details(request.game_id)
                
                # Create database record
                db_bet = LiveBetDB(
                    id=bet_id,
                    user_id=user_id,
                    game_id=request.game_id,
                    bet_type=request.bet_type,
                    selection=request.selection,
                    odds=current_odds,
                    amount=request.amount,
                    potential_win=potential_win,
                    status=BetStatus.LIVE.value,
                    placed_at=datetime.utcnow(),
                    game_time=f"{game_state.status.value} - {game_state.time_remaining}",
                    current_score=f"{game_state.home_score} - {game_state.away_score}",
                    cash_out_available=True,
                    cash_out_value=self._calculate_initial_cash_out(request.amount),
                    home_team=home_team,
                    away_team=away_team,
                    sport=sport,
                    commence_time=datetime.utcnow()
                )
                
                db.add(db_bet)
                db.commit()
                db.refresh(db_bet)
                
                # Create LiveBet model for response using the conversion function
                live_bet = self._db_bet_to_model(db_bet)
                
                # Generate initial cash out offer
                self._generate_cash_out_offer(bet_id)
                
                logger.info(f"Live bet placed: {bet_id} for user {user_id}")
                
                return LiveBetResponse(
                    success=True,
                    bet=live_bet,
                    odds_changed=odds_changed,
                    new_odds=current_odds if odds_changed else None
                )
                
            finally:
                db.close()
                
        except Exception as e:
            import traceback
            logger.error(f"Error placing live bet: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            return LiveBetResponse(
                success=False,
                error=f"Failed to place bet: {str(e)}"
            )
    
    def get_cash_out_offer(self, bet_id: str, user_id: int) -> Optional[CashOutOffer]:
        """Get current cash out offer for a bet from database"""
        
        try:
            db = SessionLocal()
            try:
                db_bet = db.query(LiveBetDB).filter(
                    and_(
                        LiveBetDB.id == bet_id,
                        LiveBetDB.user_id == user_id
                    )
                ).first()
                
                if not db_bet:
                    return None
                
                if db_bet.status != BetStatus.LIVE.value:
                    return CashOutOffer(
                        bet_id=bet_id,
                        original_amount=db_bet.amount,
                        original_potential_win=db_bet.potential_win,
                        current_cash_out_value=0,
                        profit_loss=0,
                        offer_expires_at=datetime.utcnow(),
                        is_available=False,
                        reason=f"Bet is {db_bet.status}"
                    )
                
                # Generate fresh cash out offer
                return self._generate_cash_out_offer(bet_id)
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting cash out offer: {e}")
            return None
    
    def execute_cash_out(self, bet_id: str, user_id: int, accept_amount: float) -> Dict[str, Any]:
        """Execute a cash out for a live bet in database"""
        
        try:
            db = SessionLocal()
            try:
                db_bet = db.query(LiveBetDB).filter(
                    and_(
                        LiveBetDB.id == bet_id,
                        LiveBetDB.user_id == user_id
                    )
                ).first()
                
                if not db_bet:
                    return {"success": False, "error": "Bet not found"}
                
                if db_bet.status != BetStatus.LIVE.value:
                    return {"success": False, "error": f"Bet is {db_bet.status}"}
                
                # Get current offer
                offer = self.get_cash_out_offer(bet_id, user_id)
                if not offer or not offer.is_available:
                    return {"success": False, "error": "Cash out not available"}
                
                # Verify amount matches current offer (within small tolerance for floating point)
                if abs(offer.current_cash_out_value - accept_amount) > 0.01:
                    return {
                        "success": False, 
                        "error": "Cash out value has changed",
                        "new_offer": offer.current_cash_out_value
                    }
                
                # Execute cash out
                db_bet.status = BetStatus.CASHED_OUT.value
                db_bet.cashed_out_at = datetime.utcnow()
                db_bet.cashed_out_amount = accept_amount
                db_bet.cash_out_available = False
                
                db.commit()
                
                logger.info(f"Live bet cashed out: {bet_id} for ${accept_amount}")
                
                return {
                    "success": True,
                    "cash_out_amount": accept_amount,
                    "profit_loss": accept_amount - db_bet.amount,
                    "message": f"Successfully cashed out for ${accept_amount:.2f}"
                }
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error executing cash out: {e}")
            return {"success": False, "error": "Failed to cash out"}
    
    def update_game_state(self, game_update: LiveGameUpdate):
        """Update game state and recalculate cash out values for database bets"""
        
        self.live_games[game_update.game_id] = game_update
        
        try:
            db = SessionLocal()
            try:
                # Update all active bets for this game in database
                active_bets = db.query(LiveBetDB).filter(
                    and_(
                        LiveBetDB.game_id == game_update.game_id,
                        LiveBetDB.status == LiveBetStatus.ACTIVE.value
                    )
                ).all()
                
                for db_bet in active_bets:
                    db_bet.current_game_status = game_update.status.value
                    db_bet.current_home_score = game_update.home_score
                    db_bet.current_away_score = game_update.away_score
                    
                    # Recalculate cash out value
                    if db_bet.cash_out_available:
                        # Convert to LiveBet model for calculation
                        live_bet = self._db_bet_to_model(db_bet)
                        db_bet.cash_out_value = self._calculate_cash_out_value(live_bet, game_update)
                    
                    # Check if game ended
                    if game_update.status == GameStatus.FINAL:
                        self._settle_db_bet(db_bet, game_update)
                
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error updating game state: {e}")
    
    def update_live_odds(self, odds_update: LiveOddsUpdate):
        """Update live odds for a game and database bets"""
        
        self.live_odds[odds_update.game_id] = odds_update
        
        # Update suspension status
        if odds_update.is_suspended:
            self.suspended_markets.add(odds_update.game_id)
        else:
            self.suspended_markets.discard(odds_update.game_id)
        
        try:
            db = SessionLocal()
            try:
                # Update current odds for active bets in database
                active_bets = db.query(LiveBetDB).filter(
                    and_(
                        LiveBetDB.game_id == odds_update.game_id,
                        LiveBetDB.status == LiveBetStatus.ACTIVE.value
                    )
                ).all()
                
                for db_bet in active_bets:
                    market_odds = self._get_market_odds(odds_update, db_bet.bet_type, db_bet.selection)
                    if market_odds:
                        db_bet.current_odds = market_odds
                        db_bet.current_potential_win = self._calculate_potential_win(db_bet.amount, market_odds)
                
                db.commit()
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error updating live odds: {e}")
    
    async def get_live_betting_markets(self, sport: Optional[str] = None) -> List[LiveBettingMarket]:
        """Get all available live betting markets from real sports data"""
        
        markets = []
        
        try:
            logger.info(f"Starting to fetch live betting markets, ODDS_API_KEY configured: {bool(settings.ODDS_API_KEY)}")
            # Get live games from The Odds API
            async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
                # Get upcoming games that could be live
                if sport:
                    # If a specific sport is requested, convert string to SportKey enum
                    sport_mapping = {
                        'americanfootball_nfl': SportKey.AMERICANFOOTBALL_NFL,
                        'basketball_nba': SportKey.BASKETBALL_NBA,
                        'baseball_mlb': SportKey.BASEBALL_MLB
                    }
                    sports_to_check = [sport_mapping.get(sport, SportKey.AMERICANFOOTBALL_NFL)]
                else:
                    sports_to_check = [SportKey.AMERICANFOOTBALL_NFL, SportKey.BASKETBALL_NBA, SportKey.BASEBALL_MLB]
                
                for sport_key in sports_to_check:
                    try:
                        logger.info(f"Fetching odds for sport: {sport_key}")
                        odds_data = await odds_service.get_odds(
                            sport=sport_key.value,
                            markets=[MarketKey.H2H.value, MarketKey.SPREADS.value, MarketKey.TOTALS.value],
                            regions=['us'],
                            odds_format=OddsFormat.AMERICAN
                        )
                        
                        games_data = odds_data if isinstance(odds_data, list) else odds_data.get('data', [])
                        logger.info(f"API returned {len(games_data)} games for {sport_key}")
                        
                        # Process each game to create live markets
                        for i, game in enumerate(games_data[:10]):  # Take first 10 games
                            logger.info(f"Processing game {i+1}: {game.home_team} vs {game.away_team}")
                            
                            try:
                                # Use the simpler market creation method that always works
                                market = await self._create_simple_live_market(game)
                                if market:
                                    logger.info(f"✓ Market created: {market.home_team} vs {market.away_team}")
                                    markets.append(market)
                                else:
                                    logger.warning(f"✗ Market creation returned None")
                            except Exception as e:
                                logger.error(f"✗ Error creating market: {e}")
                                continue
                                    
                    except Exception as e:
                        logger.error(f"Error fetching odds for {sport_key}: {e}")
                        continue
                        
        except Exception as e:
            logger.error(f"Error in main try block: {e}")
        
        # Cache the markets for bet placement
        self.cached_markets = markets
        
        logger.info(f"Total markets created from real API: {len(markets)}")
        logger.info(f"Returning {len(markets)} live markets")
        return markets
    
    def get_user_live_bets(self, user_id: int, include_settled: bool = False) -> List[LiveBet]:
        """Get all live bets for a user from database"""
        
        try:
            db = SessionLocal()
            try:
                query = db.query(LiveBetDB).filter(LiveBetDB.user_id == user_id)
                
                if not include_settled:
                    query = query.filter(
                        LiveBetDB.status.in_([BetStatus.LIVE.value])
                    )
                
                db_bets = query.order_by(desc(LiveBetDB.placed_at)).all()
                
                # Convert to LiveBet models and update with current game state
                user_bets = []
                for db_bet in db_bets:
                    live_bet = self._db_bet_to_model(db_bet)
                    
                    # Update with current game state if available
                    if db_bet.status == BetStatus.LIVE.value:
                        # Try to get current game state or create a consistent one
                        current_game_state = self.live_games.get(db_bet.game_id)
                        if not current_game_state:
                            # Create a consistent game state for this game
                            current_game_state = self._create_consistent_game_state(db_bet.game_id, db_bet.sport)
                            if current_game_state:
                                self.live_games[db_bet.game_id] = current_game_state
                        
                        if current_game_state:
                            live_bet.current_home_score = current_game_state.home_score
                            live_bet.current_away_score = current_game_state.away_score
                            live_bet.current_game_status = current_game_state.status
                            
                            # Recalculate cash out value based on current game state
                            live_bet.cash_out_value = self._calculate_updated_cash_out(db_bet, current_game_state)
                    
                    user_bets.append(live_bet)
                
                return user_bets
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error getting user live bets: {e}")
            return []
    
    def _db_bet_to_model(self, db_bet: LiveBetDB) -> LiveBet:
        """Convert database LiveBet to model LiveBet"""
        # Parse scores from current_score string format "7 - 7"
        try:
            current_score = getattr(db_bet, 'current_score', None)
            if current_score and " - " in current_score:
                home_score, away_score = current_score.split(" - ")
                home_score, away_score = int(home_score), int(away_score)
            else:
                home_score, away_score = 0, 0
        except Exception as e:
            logger.warning(f"Failed to parse current_score from db_bet: {e}")
            home_score, away_score = 0, 0
            
        # Parse game status from game_time string
        game_status = GameStatus.FIRST_PERIOD  # Default fallback
        game_time = getattr(db_bet, 'game_time', None)
        if game_time:
            if "inning" in game_time.lower():
                game_status = GameStatus.FIRST_INNING  # Will be improved later
            elif "quarter" in game_time.lower():
                game_status = GameStatus.FIRST_QUARTER
        
        # Get team names and sport information from database
        home_team = getattr(db_bet, 'home_team', None)
        away_team = getattr(db_bet, 'away_team', None)
        sport = getattr(db_bet, 'sport', None)
        
        # If database doesn't have team info, try to get from game details cache
        if not home_team or not away_team:
            home_team, away_team, sport = self._get_game_details(db_bet.game_id)
            # Final fallback if still not found
            if not home_team:
                home_team = "Home Team"
            if not away_team:
                away_team = "Away Team"
            if not sport:
                sport = "MLB"
        
        return LiveBet(
            id=db_bet.id,
            user_id=db_bet.user_id,
            game_id=db_bet.game_id,
            bet_type=db_bet.bet_type.value if hasattr(db_bet.bet_type, 'value') else str(db_bet.bet_type),
            selection=db_bet.selection,
            original_odds=db_bet.odds,
            current_odds=db_bet.odds,
            amount=db_bet.amount,
            potential_win=db_bet.potential_win,
            current_potential_win=db_bet.potential_win,
            status=LiveBetStatus.ACTIVE,  # Map database LIVE to model ACTIVE
            placed_at=db_bet.placed_at,
            settled_at=getattr(db_bet, 'settled_at', None),
            game_status_at_placement=game_status,
            current_game_status=game_status,
            home_score_at_placement=home_score,
            away_score_at_placement=away_score,
            current_home_score=home_score,
            current_away_score=away_score,
            cash_out_available=getattr(db_bet, 'cash_out_available', True),
            cash_out_value=getattr(db_bet, 'cash_out_value', None),
            cashed_out_at=getattr(db_bet, 'cashed_out_at', None),
            cashed_out_amount=getattr(db_bet, 'cash_out_amount', None),
            result_amount=getattr(db_bet, 'result_amount', None),
            home_team=home_team,
            away_team=away_team,
            sport=sport
        )
    
    def _settle_db_bet(self, db_bet: LiveBetDB, final_game_state: LiveGameUpdate):
        """Settle a database bet when game ends"""
        
        # Determine if bet won
        won = False
        if db_bet.bet_type == "moneyline":
            if db_bet.selection == "home" and final_game_state.home_score > final_game_state.away_score:
                won = True
            elif db_bet.selection == "away" and final_game_state.away_score > final_game_state.home_score:
                won = True
        
        # Update bet status in database
        db_bet.status = LiveBetStatus.SETTLED.value
        db_bet.settled_at = datetime.utcnow()
        db_bet.result_amount = db_bet.potential_win if won else 0
    
    # Include all the helper methods from the original service
    async def _create_simple_live_market(self, game) -> Optional[LiveBettingMarket]:
        """Create a live betting market from real API game data"""
        try:
            # Extract basic game info
            game_id = game.id
            home_team = game.home_team
            away_team = game.away_team
            
            # Handle commence_time - it might be a string or datetime object
            commence_time = game.commence_time
            logger.info(f"DEBUG: commence_time type: {type(commence_time)}, value: {commence_time}")
            
            if isinstance(commence_time, str):
                try:
                    # Parse ISO format string
                    if 'T' in commence_time:
                        # ISO format with T separator
                        if commence_time.endswith('Z'):
                            start_time = datetime.fromisoformat(commence_time.replace('Z', '+00:00'))
                        else:
                            start_time = datetime.fromisoformat(commence_time)
                    else:
                        # Try parsing as a different format
                        from dateutil import parser
                        start_time = parser.parse(commence_time)
                except Exception as e:
                    logger.error(f"Failed to parse commence_time string '{commence_time}': {e}")
                    # Use a default time for debugging
                    start_time = datetime.utcnow() + timedelta(hours=2)
            elif hasattr(commence_time, 'year'):
                # Already a datetime object
                start_time = commence_time
            else:
                logger.error(f"Unexpected commence_time type: {type(commence_time)}")
                # Use a default time
                start_time = datetime.utcnow() + timedelta(hours=2)
            
            # Get current time
            now = datetime.utcnow()
            
            # Calculate time difference (negative means future game)
            time_since_start = (now - start_time.replace(tzinfo=None)).total_seconds() / 3600
            
            # Show upcoming games (within 24 hours) and recently started games (within 4 hours)
            if time_since_start < -24 or time_since_start > 4:
                logger.debug(f"Skipping game {game_id}: outside time window (starts in {-time_since_start:.1f} hours)" if time_since_start < 0 else f"Skipping game {game_id}: too old (started {time_since_start:.1f} hours ago)")
                return None
            
            # Determine if game is likely live or upcoming
            is_live = 0 < time_since_start < 3.5  # Most games finish within 3.5 hours
            
            # Extract odds from bookmakers
            moneyline_odds, spread_odds, total_odds = {}, {}, {}
            bookmaker_name = ""
            
            if game.bookmakers:
                bookmaker = game.bookmakers[0]
                bookmaker_name = getattr(bookmaker, 'title', getattr(bookmaker, 'key', 'Unknown'))
                
                # Debug: log available markets
                available_markets = []
                for market in bookmaker.markets:
                    market_key = market.get('key') if isinstance(market, dict) else getattr(market, 'key', None)
                    available_markets.append(market_key)
                logger.info(f"Available markets for {home_team} vs {away_team}: {available_markets}")
                
                for market in bookmaker.markets:
                    market_key = market.get('key') if isinstance(market, dict) else getattr(market, 'key', None)
                    
                    if market_key == 'h2h':
                        # Moneyline odds
                        outcomes = market.get('outcomes') if isinstance(market, dict) else getattr(market, 'outcomes', [])
                        for outcome in outcomes:
                            name = outcome.get('name') if isinstance(outcome, dict) else getattr(outcome, 'name', '')
                            price = outcome.get('price') if isinstance(outcome, dict) else getattr(outcome, 'price', 0)
                            if name == home_team:
                                moneyline_odds['home'] = price
                            elif name == away_team:
                                moneyline_odds['away'] = price
                    
                    elif market_key == 'spreads':
                        # Spread odds
                        outcomes = market.get('outcomes') if isinstance(market, dict) else getattr(market, 'outcomes', [])
                        for outcome in outcomes:
                            name = outcome.get('name') if isinstance(outcome, dict) else getattr(outcome, 'name', '')
                            price = outcome.get('price') if isinstance(outcome, dict) else getattr(outcome, 'price', 0)
                            point = outcome.get('point') if isinstance(outcome, dict) else getattr(outcome, 'point', 0)
                            if name == home_team:
                                spread_odds['point'] = point
                                spread_odds['home_odds'] = price
                            elif name == away_team:
                                spread_odds['away_odds'] = price
                    
                    elif market_key == 'totals':
                        # Total odds
                        outcomes = market.get('outcomes') if isinstance(market, dict) else getattr(market, 'outcomes', [])
                        for outcome in outcomes:
                            name = outcome.get('name') if isinstance(outcome, dict) else getattr(outcome, 'name', '')
                            price = outcome.get('price') if isinstance(outcome, dict) else getattr(outcome, 'price', 0)
                            point = outcome.get('point') if isinstance(outcome, dict) else getattr(outcome, 'point', 0)
                            if name == 'Over':
                                total_odds['point'] = point
                                total_odds['over_odds'] = price
                            elif name == 'Under':
                                total_odds['under_odds'] = price
            
            # Simulate live scores if game is likely in progress
            home_score = 0
            away_score = 0
            quarter = "Pre-Game"
            time_remaining = "Starting Soon"
            
            if is_live:
                # Estimate game progress
                if time_since_start < 0.5:
                    quarter = "1st Quarter"
                    time_remaining = "12:00"
                elif time_since_start < 1:
                    quarter = "2nd Quarter"
                    time_remaining = "8:30"
                elif time_since_start < 1.5:
                    quarter = "Halftime"
                    time_remaining = ""
                elif time_since_start < 2:
                    quarter = "3rd Quarter"
                    time_remaining = "10:15"
                elif time_since_start < 2.5:
                    quarter = "4th Quarter"
                    time_remaining = "5:45"
                else:
                    quarter = "Final"
                    time_remaining = ""
                
                # Generate reasonable scores based on sport and time
                if "NBA" in str(game.sport_key).upper() or "basketball" in str(game.sport_key).lower():
                    home_score = int(time_since_start * 35)
                    away_score = int(time_since_start * 33)
                elif "NFL" in str(game.sport_key).upper() or "football" in str(game.sport_key).lower():
                    home_score = int(time_since_start * 8)
                    away_score = int(time_since_start * 7)
                elif "MLB" in str(game.sport_key).upper() or "baseball" in str(game.sport_key).lower():
                    home_score = int(time_since_start * 2.5)
                    away_score = int(time_since_start * 2)
                    quarter = f"Inning {min(int(time_since_start * 3) + 1, 9)}"
                    time_remaining = "Top" if int(time_since_start * 6) % 2 == 0 else "Bottom"
                else:
                    home_score = int(time_since_start * 1.5)
                    away_score = int(time_since_start * 1.2)
            
            # Map period to game status enum
            from app.models.live_bet_models import GameStatus
            game_status = GameStatus.PRE_GAME
            if is_live:
                if "baseball" in str(game.sport_key).lower():
                    # Map inning number to status
                    inning_num = quarter.replace("Inning ", "")
                    inning_map = {
                        "1": GameStatus.FIRST_INNING,
                        "2": GameStatus.SECOND_INNING,
                        "3": GameStatus.THIRD_INNING,
                        "4": GameStatus.FOURTH_INNING,
                        "5": GameStatus.FIFTH_INNING,
                        "6": GameStatus.SIXTH_INNING,
                        "7": GameStatus.SEVENTH_INNING,
                        "8": GameStatus.EIGHTH_INNING,
                        "9": GameStatus.NINTH_INNING,
                    }
                    game_status = inning_map.get(inning_num, GameStatus.FIRST_INNING)
                elif "basketball" in str(game.sport_key).lower():
                    # Map quarter to status
                    quarter_map = {
                        "Q1": GameStatus.FIRST_QUARTER,
                        "Q2": GameStatus.SECOND_QUARTER,
                        "Q3": GameStatus.THIRD_QUARTER,
                        "Q4": GameStatus.FOURTH_QUARTER,
                    }
                    game_status = quarter_map.get(quarter, GameStatus.FIRST_QUARTER)
                else:
                    # Default to first quarter for other sports
                    game_status = GameStatus.FIRST_QUARTER
            
            # Determine available markets
            markets_available = []
            if moneyline_odds:
                markets_available.append("moneyline")
            if spread_odds:
                markets_available.append("spread")
            if total_odds:
                markets_available.append("total")
            
            # Ensure at least one market is available
            if not markets_available:
                markets_available = ["moneyline"]
            
            # Create the live betting market with correct fields
            market = LiveBettingMarket(
                game_id=game_id,
                sport=str(game.sport_key),
                home_team=home_team,
                away_team=away_team,
                game_status=game_status,
                home_score=home_score,
                away_score=away_score,
                time_remaining=time_remaining,
                commence_time=start_time,
                markets_available=markets_available,
                moneyline_home=moneyline_odds.get('home') if moneyline_odds else None,
                moneyline_away=moneyline_odds.get('away') if moneyline_odds else None,
                spread_line=spread_odds.get('point') if spread_odds else None,
                spread_home_odds=spread_odds.get('home_odds') if spread_odds else None,
                spread_away_odds=spread_odds.get('away_odds') if spread_odds else None,
                total_line=total_odds.get('point') if total_odds else None,
                total_over_odds=total_odds.get('over_odds') if total_odds else None,
                total_under_odds=total_odds.get('under_odds') if total_odds else None,
                last_updated=datetime.utcnow()
            )
            
            logger.info(f"Created live market for: {home_team} vs {away_team} (Live: {is_live})")
            
            # Also populate live_games dict for bet placement
            if is_live:
                from app.models.live_bet_models import LiveGameUpdate
                self.live_games[game_id] = LiveGameUpdate(
                    game_id=game_id,
                    status=game_status,
                    home_score=home_score,
                    away_score=away_score,
                    time_remaining=time_remaining,
                    quarter=None,
                    period=None,
                    inning=int(quarter.replace("Inning ", "")) if "Inning" in quarter else None,
                    possession=None,
                    last_play=None,
                    timestamp=datetime.utcnow()
                )
                
                # Also store live odds for this game
                self.live_odds[game_id] = {
                    'moneyline': {'home': moneyline_odds.get('home'), 'away': moneyline_odds.get('away')},
                    'spread': spread_odds if spread_odds else {},
                    'total': total_odds if total_odds else {}
                }
            
            return market
            
        except Exception as e:
            logger.error(f"Error creating live market from game: {str(e)}")
            # Print detailed error for debugging
            from pydantic import ValidationError
            if isinstance(e, ValidationError):
                for error in e.errors():
                    field = ' -> '.join(str(loc) for loc in error.get('loc', ['unknown']))
                    logger.error(f"  Validation Error - Field: {field}, Error: {error.get('msg', 'unknown')}, Input: {error.get('input', 'N/A')}")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            return None    
    def _extract_odds_from_game(self, game, market_type: str) -> tuple:
        """Extract odds for a specific market type from a Game object"""
        bookmakers = game.bookmakers
        if not bookmakers:
            return {}, ""
        
        # Use first available bookmaker
        bookmaker = bookmakers[0]
        bookmaker_name = getattr(bookmaker, 'title', getattr(bookmaker, 'key', 'Unknown'))
        markets = bookmaker.markets
        
        for market in markets:
            # Check if market is a dict or has .key attribute  
            market_key = market.get('key') if isinstance(market, dict) else getattr(market, 'key', None)
            if market_key == market_type:
                outcomes = market.get('outcomes') if isinstance(market, dict) else getattr(market, 'outcomes', [])
                
                if market_type == 'h2h':
                    result = {}
                    for outcome in outcomes:
                        outcome_name = outcome.get('name') if isinstance(outcome, dict) else getattr(outcome, 'name', '')
                        outcome_price = outcome.get('price') if isinstance(outcome, dict) else getattr(outcome, 'price', 0)
                        if outcome_name == game.home_team:
                            result['home'] = outcome_price
                        elif outcome_name == game.away_team:
                            result['away'] = outcome_price
                    return result, bookmaker_name
                
                elif market_type == 'spreads':
                    result = {}
                    for outcome in outcomes:
                        outcome_name = outcome.get('name') if isinstance(outcome, dict) else getattr(outcome, 'name', '')
                        outcome_price = outcome.get('price') if isinstance(outcome, dict) else getattr(outcome, 'price', 0)
                        outcome_point = outcome.get('point') if isinstance(outcome, dict) else getattr(outcome, 'point', 0)
                        if outcome_name == game.home_team:
                            result['point'] = outcome_point
                            result['home_odds'] = outcome_price
                        elif outcome_name == game.away_team:
                            result['away_odds'] = outcome_price
                    return result, bookmaker_name
                
                elif market_type == 'totals':
                    result = {}
                    for outcome in outcomes:
                        outcome_name = outcome.get('name') if isinstance(outcome, dict) else getattr(outcome, 'name', '')
                        outcome_price = outcome.get('price') if isinstance(outcome, dict) else getattr(outcome, 'price', 0)
                        outcome_point = outcome.get('point') if isinstance(outcome, dict) else getattr(outcome, 'point', 0)
                        if outcome_name == 'Over':
                            result['point'] = outcome_point
                            result['over_odds'] = outcome_price
                        elif outcome_name == 'Under':
                            result['under_odds'] = outcome_price
                    return result, bookmaker_name
        
        return {}, ""
    
    def _get_game_details(self, game_id: str) -> tuple:
        """Get game details from cached markets"""
        # Try to get from recent markets cache
        logger.info(f"Looking for game {game_id} in {len(self.cached_markets)} cached markets")
        for market in self.cached_markets:
            if market.game_id == game_id:
                logger.info(f"Found game {game_id}: {market.home_team} vs {market.away_team}")
                return market.home_team, market.away_team, market.sport
        
        # Fallback to defaults
        logger.warning(f"Game {game_id} not found in cached markets, using defaults")
        return "Home Team", "Away Team", "unknown"
    
    def _get_market_odds(self, odds_data: dict, bet_type: str, selection: str) -> Optional[float]:
        """Extract specific odds from odds data"""
        if bet_type == "moneyline":
            moneyline = odds_data.get('moneyline', {})
            if isinstance(moneyline, dict):
                return moneyline.get(selection)
        elif bet_type == "spread":
            spread = odds_data.get('spread', {})
            if isinstance(spread, dict):
                if selection == "home":
                    return spread.get('home_odds')
                elif selection == "away":
                    return spread.get('away_odds')
        elif bet_type == "total":
            total = odds_data.get('total', {})
            if isinstance(total, dict):
                if selection == "over":
                    return total.get('over_odds')
                elif selection == "under":
                    return total.get('under_odds')
        return None
    
    def _calculate_potential_win(self, amount: float, odds: float) -> float:
        """Calculate potential win from American odds"""
        if odds > 0:
            return amount * (odds / 100)
        else:
            return amount * (100 / abs(odds))
    
    def _calculate_initial_cash_out(self, amount: float) -> float:
        """Calculate initial cash out value (usually slightly less than bet amount)"""
        return amount * 0.95  # 95% of original bet
    
    def _calculate_cash_out_value(self, bet: LiveBet, game_state: LiveGameUpdate) -> float:
        """Calculate dynamic cash out value based on game state"""
        
        base_value = bet.amount
        
        # Adjust based on score
        score_diff = game_state.home_score - game_state.away_score
        if bet.selection == "home":
            if score_diff > 0:
                base_value *= (1 + score_diff * 0.1)  # Increase value if winning
            else:
                base_value *= (1 + score_diff * 0.05)  # Decrease less if losing
        elif bet.selection == "away":
            if score_diff < 0:
                base_value *= (1 - score_diff * 0.1)  # Increase value if winning
            else:
                base_value *= (1 - score_diff * 0.05)  # Decrease less if losing
        
        # Adjust based on game progress
        if game_state.status in [GameStatus.FOURTH_QUARTER, GameStatus.SECOND_HALF]:
            base_value *= 1.1  # Increase value near end of game
        
        # Cap at potential win
        return min(base_value, bet.potential_win * 0.95)
    
    def _calculate_updated_cash_out(self, db_bet: LiveBetDB, game_state) -> float:
        """Calculate updated cash out value for a live bet"""
        live_bet = self._db_bet_to_model(db_bet)
        return self._calculate_cash_out_value(live_bet, game_state)
    
    def _create_consistent_game_state(self, game_id: str, sport: str, sport_key: str = None):
        """Disabled to prevent fake game data - only use real live data"""
        logger.info(f"Skipping fake game state creation for {game_id} to avoid mock data")
        return None
    
    def _generate_cash_out_offer(self, bet_id: str) -> CashOutOffer:
        """Generate a cash out offer for a bet"""
        
        try:
            db = SessionLocal()
            try:
                db_bet = db.query(LiveBetDB).filter(LiveBetDB.id == bet_id).first()
                if not db_bet:
                    return None
                
                game_state = self.live_games.get(db_bet.game_id)
                live_bet = self._db_bet_to_model(db_bet)
                cash_out_value = self._calculate_cash_out_value(live_bet, game_state) if game_state else db_bet.cash_out_value
                
                offer = CashOutOffer(
                    bet_id=bet_id,
                    original_amount=db_bet.amount,
                    original_potential_win=db_bet.potential_win,
                    current_cash_out_value=cash_out_value,
                    profit_loss=cash_out_value - db_bet.amount,
                    offer_expires_at=datetime.utcnow() + timedelta(seconds=30),
                    is_available=True
                )
                
                self.cash_out_offers[bet_id] = offer
                return offer
                
            finally:
                db.close()
                
        except Exception as e:
            logger.error(f"Error generating cash out offer: {e}")
            return None
    
    def _get_market_odds(self, odds_data: LiveOddsUpdate, bet_type: str, selection: str) -> Optional[float]:
        """Get current market odds for a specific bet"""
        
        if bet_type == "moneyline":
            if isinstance(odds_data, dict):
                return odds_data.get('home' if selection == "home" else 'away')
            else:
                return odds_data.home_odds if selection == "home" else odds_data.away_odds
        # Would handle spread and total odds
        return None
    

# Initialize service
live_betting_service_db = LiveBettingServiceDB()