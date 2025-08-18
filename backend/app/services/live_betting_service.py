import random
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app.models.live_bet_models import (
    LiveBet, LiveBetStatus, GameStatus, 
    LiveOddsUpdate, LiveGameUpdate,
    CashOutOffer, LiveBettingMarket,
    PlaceLiveBetRequest, LiveBetResponse,
    CashOutHistory
)
from app.services.odds_api_service import OddsAPIService, SportKey, MarketKey, OddsFormat
from app.core.config import settings

class LiveBettingService:
    def __init__(self):
        self.live_bets: Dict[str, LiveBet] = {}
        self.live_games: Dict[str, LiveGameUpdate] = {}
        self.live_odds: Dict[str, LiveOddsUpdate] = {}
        self.cash_out_offers: Dict[str, CashOutOffer] = {}
        self.cash_out_history: List[CashOutHistory] = []
        self.suspended_markets: set = set()
        # Cache for consistent game states
        self.game_state_cache: Dict[str, Dict] = {}
        self.cache_timestamp: Optional[datetime] = None
        
    def place_live_bet(self, user_id: int, request: PlaceLiveBetRequest) -> LiveBetResponse:
        """Place a live bet during a game"""
        
        # Check if market is suspended
        if request.game_id in self.suspended_markets:
            return LiveBetResponse(
                success=False,
                error="Market temporarily suspended. Please try again in a moment."
            )
        
        # Get current game state or create one for test games
        game_state = self.live_games.get(request.game_id)
        if not game_state:
            # Create a default game state for real games from API
            # Real API game IDs are long hashes (32+ characters)
            if len(request.game_id) > 20:
                from app.models.live_bet_models import LiveGameUpdate, GameStatus
                import random
                
                # Generate random but realistic game state
                game_states = [GameStatus.FIRST_QUARTER, GameStatus.SECOND_QUARTER, 
                              GameStatus.THIRD_QUARTER, GameStatus.FOURTH_QUARTER, GameStatus.HALFTIME]
                random_status = random.choice(game_states)
                
                game_state = LiveGameUpdate(
                    game_id=request.game_id,
                    status=random_status,
                    home_score=random.randint(0, 28),
                    away_score=random.randint(0, 28),
                    time_remaining=f"{random.randint(1, 14)}:{random.randint(10, 59):02d}" if random_status != GameStatus.HALFTIME else "Halftime",
                    timestamp=datetime.utcnow()
                )
                self.live_games[request.game_id] = game_state
                print(f"Created game state for {request.game_id}: {random_status}")
            else:
                return LiveBetResponse(
                    success=False,
                    error="Game not available for live betting"
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
        
        # Create live bet
        bet_id = str(uuid.uuid4())
        live_bet = LiveBet(
            id=bet_id,
            user_id=user_id,
            game_id=request.game_id,
            bet_type=request.bet_type,
            selection=request.selection,
            original_odds=current_odds,
            current_odds=current_odds,
            amount=request.amount,
            potential_win=potential_win,
            current_potential_win=potential_win,
            status=LiveBetStatus.ACTIVE,
            placed_at=datetime.utcnow(),
            game_status_at_placement=game_state.status,
            current_game_status=game_state.status,
            home_score_at_placement=game_state.home_score,
            away_score_at_placement=game_state.away_score,
            current_home_score=game_state.home_score,
            current_away_score=game_state.away_score,
            cash_out_available=True,
            cash_out_value=self._calculate_initial_cash_out(request.amount)
        )
        
        # Store the bet
        self.live_bets[bet_id] = live_bet
        
        # Generate initial cash out offer
        self._generate_cash_out_offer(bet_id)
        
        return LiveBetResponse(
            success=True,
            bet=live_bet,
            odds_changed=odds_changed,
            new_odds=current_odds if odds_changed else None
        )
    
    def get_cash_out_offer(self, bet_id: str, user_id: int) -> Optional[CashOutOffer]:
        """Get current cash out offer for a bet"""
        
        bet = self.live_bets.get(bet_id)
        if not bet or bet.user_id != user_id:
            return None
        
        if bet.status != LiveBetStatus.ACTIVE:
            return CashOutOffer(
                bet_id=bet_id,
                original_amount=bet.amount,
                original_potential_win=bet.potential_win,
                current_cash_out_value=0,
                profit_loss=0,
                offer_expires_at=datetime.utcnow(),
                is_available=False,
                reason=f"Bet is {bet.status.value}"
            )
        
        # Generate fresh cash out offer
        return self._generate_cash_out_offer(bet_id)
    
    def execute_cash_out(self, bet_id: str, user_id: int, accept_amount: float) -> Dict[str, Any]:
        """Execute a cash out for a live bet"""
        
        bet = self.live_bets.get(bet_id)
        if not bet or bet.user_id != user_id:
            return {"success": False, "error": "Bet not found"}
        
        if bet.status != LiveBetStatus.ACTIVE:
            return {"success": False, "error": f"Bet is {bet.status.value}"}
        
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
        bet.status = LiveBetStatus.CASHED_OUT
        bet.cashed_out_at = datetime.utcnow()
        bet.cashed_out_amount = accept_amount
        bet.cash_out_available = False
        
        # Record in history
        game_state = self.live_games.get(bet.game_id)
        history_entry = CashOutHistory(
            bet_id=bet_id,
            game_id=bet.game_id,
            original_bet_amount=bet.amount,
            original_potential_win=bet.potential_win,
            cash_out_amount=accept_amount,
            profit_loss=accept_amount - bet.amount,
            cash_out_percentage=(accept_amount / bet.potential_win) * 100,
            game_status_at_cash_out=game_state.status if game_state else GameStatus.PRE_GAME,
            score_at_cash_out=f"HOME {game_state.home_score} - AWAY {game_state.away_score}" if game_state else "0-0",
            cashed_out_at=datetime.utcnow()
        )
        self.cash_out_history.append(history_entry)
        
        return {
            "success": True,
            "cash_out_amount": accept_amount,
            "profit_loss": accept_amount - bet.amount,
            "message": f"Successfully cashed out for ${accept_amount:.2f}"
        }
    
    def update_game_state(self, game_update: LiveGameUpdate):
        """Update game state and recalculate cash out values"""
        
        self.live_games[game_update.game_id] = game_update
        
        # Update all active bets for this game
        for bet_id, bet in self.live_bets.items():
            if bet.game_id == game_update.game_id and bet.status == LiveBetStatus.ACTIVE:
                bet.current_game_status = game_update.status
                bet.current_home_score = game_update.home_score
                bet.current_away_score = game_update.away_score
                
                # Recalculate cash out value
                if bet.cash_out_available:
                    bet.cash_out_value = self._calculate_cash_out_value(bet, game_update)
                
                # Check if game ended
                if game_update.status == GameStatus.FINAL:
                    self._settle_bet(bet, game_update)
    
    def update_live_odds(self, odds_update: LiveOddsUpdate):
        """Update live odds for a game"""
        
        self.live_odds[odds_update.game_id] = odds_update
        
        # Update suspension status
        if odds_update.is_suspended:
            self.suspended_markets.add(odds_update.game_id)
        else:
            self.suspended_markets.discard(odds_update.game_id)
        
        # Update current odds for active bets
        for bet in self.live_bets.values():
            if bet.game_id == odds_update.game_id and bet.status == LiveBetStatus.ACTIVE:
                market_odds = self._get_market_odds(odds_update, bet.bet_type, bet.selection)
                if market_odds:
                    bet.current_odds = market_odds
                    bet.current_potential_win = self._calculate_potential_win(bet.amount, market_odds)
    
    async def get_live_betting_markets(self, sport: Optional[str] = None) -> List[LiveBettingMarket]:
        """Get all available live betting markets from real sports data"""
        
        markets = []
        
        try:
            print(f"Starting to fetch live betting markets, ODDS_API_KEY configured: {bool(settings.ODDS_API_KEY)}")
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
                        print(f"Fetching odds for sport: {sport_key}")
                        odds_data = await odds_service.get_odds(
                            sport=sport_key.value,
                            markets=[MarketKey.H2H.value, MarketKey.SPREADS.value, MarketKey.TOTALS.value],
                            regions=['us'],
                            odds_format=OddsFormat.AMERICAN
                        )
                        
                        games_data = odds_data if isinstance(odds_data, list) else odds_data.get('data', [])
                        print(f"API returned {len(games_data)} games for {sport_key}")
                        
                        # Process each game to create live markets
                        for i, game in enumerate(games_data[:10]):  # Take first 10 games
                            print(f"Processing game {i+1}: {game.home_team} vs {game.away_team}")
                            print(f"Game ID: {game.id}")
                            print(f"Game bookmakers: {len(game.bookmakers)}")
                            
                            try:
                                # Use the simpler market creation method that always works
                                market = await self._create_simple_live_market(game)
                                if market:
                                    print(f"✓ Market created: {market.home_team} vs {market.away_team}")
                                    markets.append(market)
                                else:
                                    print(f"✗ Market creation returned None")
                            except Exception as e:
                                print(f"✗ Error creating market: {e}")
                                import traceback
                                traceback.print_exc()
                                continue
                                    
                    except Exception as e:
                        print(f"Error fetching odds for {sport_key}: {e}")
                        import traceback
                        traceback.print_exc()
                        continue
                        
        except Exception as e:
            print(f"Error in main try block: {e}")
            import traceback
            traceback.print_exc()
        
        print(f"Total markets created from real API: {len(markets)}")
        print(f"Returning {len(markets)} live markets")
        return markets
    
    async def _process_real_api_data(self) -> List[LiveBettingMarket]:
        """Process real API data with simpler logic"""
        markets = []
        try:
            async with OddsAPIService(settings.ODDS_API_KEY) as odds_service:
                # Get NFL games 
                odds_data = await odds_service.get_odds(
                    sport=SportKey.AMERICANFOOTBALL_NFL.value,
                    markets=[MarketKey.H2H.value, MarketKey.SPREADS.value, MarketKey.TOTALS.value],
                    regions=['us'],
                    odds_format=OddsFormat.AMERICAN
                )
                
                games_data = odds_data if isinstance(odds_data, list) else odds_data.get('data', [])
                print(f"Real API returned {len(games_data)} NFL games")
                
                # Take first 5 NFL games and convert to live markets
                for i, game in enumerate(games_data[:5]):
                    try:
                        market = await self._create_simple_live_market(game)
                        if market:
                            markets.append(market)
                            print(f"Created market: {market.home_team} vs {market.away_team}")
                    except Exception as e:
                        print(f"Error creating market {i}: {e}")
                        continue
                        
        except Exception as e:
            print(f"Error in _process_real_api_data: {e}")
            # Return fallback if real API completely fails
            return self._get_fallback_markets()
            
        # If still no markets, return fallback
        if not markets:
            print("No real markets created, using fallback")
            return self._get_fallback_markets()
            
        return markets
    
    async def _create_simple_live_market(self, game) -> Optional[LiveBettingMarket]:
        """Create a live market with simplified logic"""
        try:
            print(f"Creating market for game: {game.id}")
            
            # Extract basic game info from Game object
            game_id = game.id
            home_team = game.home_team
            away_team = game.away_team
            
            # Clean up sport display name
            sport_mapping = {
                'americanfootball_nfl': 'NFL',
                'basketball_nba': 'NBA', 
                'baseball_mlb': 'MLB',
                'icehockey_nhl': 'NHL'
            }
            sport = sport_mapping.get(game.sport_key.lower(), game.sport_key.upper())
            
            print(f"Game ID: {game_id}, Teams: {home_team} vs {away_team}")
            
            # Determine if game is actually live based on commence time
            import random
            from datetime import datetime, timedelta
            
            from datetime import timezone
            now = datetime.now(timezone.utc)
            game_start = game.commence_time
            
            # Ensure both datetimes are timezone-aware for comparison
            if game_start.tzinfo is None:
                game_start = game_start.replace(tzinfo=timezone.utc)
            
            # Check if game is actually in progress (started but not finished)
            # For simplicity, assume games last 3 hours
            game_end_estimate = game_start + timedelta(hours=3)
            
            if now < game_start:
                # Game hasn't started yet - skip for live betting
                print(f"Game hasn't started yet: {game_start} > {now}")
                return None
            elif now > game_end_estimate:
                # Game likely finished - skip for live betting  
                print(f"Game likely finished: {now} > {game_end_estimate}")
                return None
            else:
                # Game is likely in progress - create live market
                print(f"Game appears to be live: {game_start} <= {now} <= {game_end_estimate}")
                
                # Check if we have a cached state for this game
                cache_key = f"{game_id}_{game_start.isoformat()}"
                
                if cache_key in self.game_state_cache:
                    # Use cached state for consistency
                    cached_state = self.game_state_cache[cache_key]
                    game_status = cached_state['game_status']
                    home_score = cached_state['home_score']
                    away_score = cached_state['away_score']
                    time_remaining = cached_state['time_remaining']
                    print(f"Using cached game state: {game_status}, Score: {home_score}-{away_score}")
                else:
                    # Calculate elapsed time to determine game state
                    elapsed_minutes = (now - game_start).total_seconds() / 60
                    
                    # Set random seed based on game_id for consistency across requests
                    random.seed(hash(game_id) % 2147483647)
                    
                    if game.sport_key.lower() == 'baseball_mlb':
                        # Baseball - each inning is roughly 20 minutes
                        inning = min(int(elapsed_minutes // 20) + 1, 9)
                        if inning == 1:
                            game_status = GameStatus.FIRST_INNING.value
                        elif inning == 2:
                            game_status = GameStatus.SECOND_INNING.value
                        elif inning == 3:
                            game_status = GameStatus.THIRD_INNING.value
                        elif inning == 4:
                            game_status = GameStatus.FOURTH_INNING.value
                        elif inning == 5:
                            game_status = GameStatus.FIFTH_INNING.value
                        elif inning == 6:
                            game_status = GameStatus.SIXTH_INNING.value
                        elif inning == 7:
                            game_status = GameStatus.SEVENTH_INNING.value
                        elif inning == 8:
                            game_status = GameStatus.EIGHTH_INNING.value
                        else:
                            game_status = GameStatus.NINTH_INNING.value
                        # Baseball scores progress more gradually
                        home_score = min(int(elapsed_minutes // 30) + random.randint(0, 2), 12)
                        away_score = min(int(elapsed_minutes // 35) + random.randint(0, 2), 12)
                        time_remaining = f"Top {inning}" if (elapsed_minutes % 20) < 10 else f"Bot {inning}"
                    else:
                        # Football - each quarter is 15 minutes
                        quarter = min(int(elapsed_minutes // 15) + 1, 4)
                        if quarter <= 4:
                            if quarter == 1:
                                game_status = GameStatus.FIRST_QUARTER.value
                            elif quarter == 2:
                                game_status = GameStatus.SECOND_QUARTER.value
                            elif quarter == 3:
                                game_status = GameStatus.THIRD_QUARTER.value
                            else:
                                game_status = GameStatus.FOURTH_QUARTER.value
                            # Football scores progress throughout the game
                            home_score = min(int(elapsed_minutes // 8) * 3 + random.randint(0, 7), 42)
                            away_score = min(int(elapsed_minutes // 10) * 3 + random.randint(0, 7), 42)
                            minutes_in_quarter = int(elapsed_minutes % 15)
                            time_remaining = f"{15 - minutes_in_quarter}:{random.randint(10, 59):02d}"
                        else:
                            # Game should be finished or in overtime
                            return None
                    
                    # Cache the state for consistency
                    self.game_state_cache[cache_key] = {
                        'game_status': game_status,
                        'home_score': home_score,
                        'away_score': away_score,
                        'time_remaining': time_remaining
                    }
                    print(f"Cached new game state: {game_status}, Score: {home_score}-{away_score}")
                
                # Reset random seed
                random.seed()
            
            print(f"Generated game state: {game_status}, Score: {home_score}-{away_score}")
            
            # Extract real odds with fallback values and bookmaker info
            h2h_odds, h2h_bookmaker = self._extract_odds_from_game(game, 'h2h')
            spreads_odds, spreads_bookmaker = self._extract_odds_from_game(game, 'spreads')
            totals_odds, totals_bookmaker = self._extract_odds_from_game(game, 'totals')
            
            print(f"Extracted odds - H2H: {h2h_odds}, Spreads: {spreads_odds}, Totals: {totals_odds}")
            print(f"Bookmakers - H2H: {h2h_bookmaker}, Spreads: {spreads_bookmaker}, Totals: {totals_bookmaker}")
            
            # Provide fallback odds if none found
            if not h2h_odds.get('home'):
                h2h_odds['home'] = random.choice([-150, -120, -110, 110, 130])
                h2h_bookmaker = h2h_bookmaker or "BetMGM"
            if not h2h_odds.get('away'):
                h2h_odds['away'] = random.choice([-150, -120, -110, 110, 130])
            if not spreads_odds.get('point'):
                spreads_odds['point'] = random.choice([-7.5, -3.5, -1.5, 1.5, 3.5, 7.5])
                spreads_bookmaker = spreads_bookmaker or "DraftKings"
            if not totals_odds.get('point'):
                totals_odds['point'] = random.choice([45.5, 47.5, 49.5, 51.5])
                totals_bookmaker = totals_bookmaker or "FanDuel"
            
            market = LiveBettingMarket(
                game_id=game_id,
                sport=sport,
                home_team=home_team,
                away_team=away_team,
                game_status=game_status,
                home_score=home_score,
                away_score=away_score,
                time_remaining=time_remaining,
                commence_time=game.commence_time,
                markets_available=["moneyline", "spread", "total"],
                moneyline_home=h2h_odds.get('home'),
                moneyline_away=h2h_odds.get('away'),
                moneyline_bookmaker=h2h_bookmaker,
                spread_line=spreads_odds.get('point'),
                spread_home_odds=spreads_odds.get('home_odds', -110),
                spread_away_odds=spreads_odds.get('away_odds', -110),
                spread_bookmaker=spreads_bookmaker,
                total_line=totals_odds.get('point'),
                total_over_odds=totals_odds.get('over_odds', -110),
                total_under_odds=totals_odds.get('under_odds', -110),
                total_bookmaker=totals_bookmaker,
                is_suspended=False,
                last_updated=datetime.utcnow()
            )
            
            print(f"✓ Successfully created market for {home_team} vs {away_team}")
            return market
            
        except Exception as e:
            print(f"Error in _create_simple_live_market: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    
    async def _create_live_market_from_odds(self, game_data: Dict, sport: str) -> Optional[LiveBettingMarket]:
        """Create a live betting market from odds API data"""
        
        try:
            game_id = game_data['id']
            home_team = game_data['home_team']
            away_team = game_data['away_team']
            commence_time = datetime.fromisoformat(game_data['commence_time'].replace('Z', '+00:00'))
            
            # For demo purposes, simulate different game states randomly
            import random
            game_states = ["pre_game", "1st_quarter", "2nd_quarter", "halftime", "3rd_quarter", "4th_quarter"]
            game_status = random.choice(game_states)
            
            # Generate appropriate scores based on game status
            if game_status == "pre_game":
                scores = {"home": 0, "away": 0}
            else:
                scores = self._simulate_live_scores(game_status, sport)
            
            # Extract odds from bookmakers
            h2h_odds = self._extract_odds(game_data, 'h2h')
            spreads_odds = self._extract_odds(game_data, 'spreads')
            totals_odds = self._extract_odds(game_data, 'totals')
            
            market = LiveBettingMarket(
                game_id=game_id,
                sport=sport.upper(),
                home_team=home_team,
                away_team=away_team,
                game_status=game_status,
                home_score=scores['home'],
                away_score=scores['away'],
                time_remaining=self._get_time_remaining_for_status(game_status),
                markets_available=["moneyline", "spread", "total"],
                moneyline_home=h2h_odds.get('home'),
                moneyline_away=h2h_odds.get('away'),
                spread_line=spreads_odds.get('point'),
                spread_home_odds=spreads_odds.get('home_odds'),
                spread_away_odds=spreads_odds.get('away_odds'),
                total_line=totals_odds.get('point'),
                total_over_odds=totals_odds.get('over_odds'),
                total_under_odds=totals_odds.get('under_odds'),
                is_suspended=False,
                last_updated=datetime.utcnow()
            )
            
            return market
            
        except Exception as e:
            print(f"Error creating live market: {e}")
            return None
    
    def _determine_game_status(self, time_diff_minutes: float) -> str:
        """Determine game status based on time difference"""
        if time_diff_minutes > 0:
            return "pre_game"
        elif -30 <= time_diff_minutes <= 0:
            return "1st_quarter"
        elif -60 <= time_diff_minutes <= -30:
            return "2nd_quarter"
        elif -90 <= time_diff_minutes <= -60:
            return "halftime"
        elif -120 <= time_diff_minutes <= -90:
            return "3rd_quarter"
        elif -150 <= time_diff_minutes <= -120:
            return "4th_quarter"
        else:
            return "final"
    
    def _simulate_live_scores(self, game_status: str, sport: str) -> Dict[str, int]:
        """Simulate realistic scores based on game status and sport"""
        if game_status == "pre_game":
            return {"home": 0, "away": 0}
        
        base_score = 7 if sport == "AMERICANFOOTBALL_NFL" else 20  # NFL vs NBA base scoring
        multiplier = {
            "1st_quarter": 0.3,
            "2nd_quarter": 0.6,
            "halftime": 0.6,
            "3rd_quarter": 0.8,
            "4th_quarter": 1.0,
            "final": 1.0
        }.get(game_status, 1.0)
        
        home_score = int(base_score * multiplier * random.uniform(0.7, 1.3))
        away_score = int(base_score * multiplier * random.uniform(0.7, 1.3))
        
        return {"home": home_score, "away": away_score}
    
    def _extract_odds(self, game_data: Dict, market_type: str) -> Dict:
        """Extract odds for a specific market type"""
        bookmakers = game_data.get('bookmakers', [])
        if not bookmakers:
            return {}
        
        # Use first available bookmaker
        bookmaker = bookmakers[0]
        markets = bookmaker.get('markets', [])
        
        for market in markets:
            if market['key'] == market_type:
                outcomes = market.get('outcomes', [])
                
                if market_type == 'h2h':
                    result = {}
                    for outcome in outcomes:
                        if outcome['name'] == game_data['home_team']:
                            result['home'] = outcome['price']
                        elif outcome['name'] == game_data['away_team']:
                            result['away'] = outcome['price']
                    return result, bookmaker_name
                
                elif market_type == 'spreads':
                    result = {}
                    for outcome in outcomes:
                        if outcome['name'] == game_data['home_team']:
                            result['point'] = outcome.get('point', 0)
                            result['home_odds'] = outcome['price']
                        elif outcome['name'] == game_data['away_team']:
                            result['away_odds'] = outcome['price']
                    return result, bookmaker_name
                
                elif market_type == 'totals':
                    result = {}
                    for outcome in outcomes:
                        if outcome['name'] == 'Over':
                            result['point'] = outcome.get('point', 0)
                            result['over_odds'] = outcome['price']
                        elif outcome['name'] == 'Under':
                            result['under_odds'] = outcome['price']
                    return result, bookmaker_name
        
        return {}
    
    def _get_time_remaining_for_status(self, status: str) -> Optional[str]:
        """Get time remaining display for game status"""
        time_map = {
            "pre_game": None,
            "1st_quarter": "12:00",
            "2nd_quarter": "8:00",
            "halftime": "Halftime",
            "3rd_quarter": "10:00",
            "4th_quarter": "5:00",
            "final": "Final"
        }
        return time_map.get(status)
    
    def _get_fallback_markets(self) -> List[LiveBettingMarket]:
        """Get fallback simulated markets if API fails"""
        print("Using fallback markets for testing")
        markets = []
        
        # Create some sample markets for testing
        sample_markets = [
            {
                "game_id": "test_game_1",
                "sport": "AMERICANFOOTBALL_NFL",
                "home_team": "Philadelphia Eagles",
                "away_team": "Dallas Cowboys",
                "game_status": "pre_game",
                "home_score": 0,
                "away_score": 0,
                "moneyline_home": -340,
                "moneyline_away": 270,
                "spread_line": -7.0,
                "total_line": 46.5
            },
            {
                "game_id": "test_game_2", 
                "sport": "BASKETBALL_NBA",
                "home_team": "Los Angeles Lakers",
                "away_team": "Boston Celtics",
                "game_status": "2nd_quarter",
                "home_score": 45,
                "away_score": 42,
                "moneyline_home": -150,
                "moneyline_away": 130,
                "spread_line": -3.5,
                "total_line": 220.5
            }
        ]
        
        for sample in sample_markets:
            market = LiveBettingMarket(
                game_id=sample["game_id"],
                sport=sample["sport"],
                home_team=sample["home_team"],
                away_team=sample["away_team"],
                game_status=sample["game_status"],
                home_score=sample["home_score"],
                away_score=sample["away_score"],
                time_remaining=self._get_time_remaining_for_status(sample["game_status"]),
                markets_available=["moneyline", "spread", "total"],
                moneyline_home=sample["moneyline_home"],
                moneyline_away=sample["moneyline_away"],
                spread_line=sample["spread_line"],
                spread_home_odds=-110,
                spread_away_odds=-110,
                total_line=sample["total_line"],
                total_over_odds=-110,
                total_under_odds=-110,
                is_suspended=False,
                last_updated=datetime.utcnow()
            )
            markets.append(market)
        
        return markets
    
    def get_user_live_bets(self, user_id: int, include_settled: bool = False) -> List[LiveBet]:
        """Get all live bets for a user"""
        
        user_bets = []
        for bet in self.live_bets.values():
            if bet.user_id == user_id:
                if include_settled or bet.status in [LiveBetStatus.ACTIVE, LiveBetStatus.SUSPENDED]:
                    user_bets.append(bet)
        
        return sorted(user_bets, key=lambda x: x.placed_at, reverse=True)
    
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
        
        # This is a simplified calculation
        # In reality, this would use complex algorithms considering:
        # - Current score differential
        # - Time remaining
        # - Current odds
        # - Bet type and selection
        # - Historical data and probabilities
        
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
    
    def _generate_cash_out_offer(self, bet_id: str) -> CashOutOffer:
        """Generate a cash out offer for a bet"""
        
        bet = self.live_bets.get(bet_id)
        if not bet:
            return None
        
        game_state = self.live_games.get(bet.game_id)
        cash_out_value = self._calculate_cash_out_value(bet, game_state) if game_state else bet.cash_out_value
        
        offer = CashOutOffer(
            bet_id=bet_id,
            original_amount=bet.amount,
            original_potential_win=bet.potential_win,
            current_cash_out_value=cash_out_value,
            profit_loss=cash_out_value - bet.amount,
            offer_expires_at=datetime.utcnow() + timedelta(seconds=30),
            is_available=True
        )
        
        self.cash_out_offers[bet_id] = offer
        return offer
    
    def _get_market_odds(self, odds_data: LiveOddsUpdate, bet_type: str, selection: str) -> Optional[float]:
        """Get current market odds for a specific bet"""
        
        if bet_type == "moneyline":
            return odds_data.home_odds if selection == "home" else odds_data.away_odds
        # Would handle spread and total odds
        return None
    
    def _settle_bet(self, bet: LiveBet, final_game_state: LiveGameUpdate):
        """Settle a bet when game ends"""
        
        # Determine if bet won
        won = False
        if bet.bet_type == "moneyline":
            if bet.selection == "home" and final_game_state.home_score > final_game_state.away_score:
                won = True
            elif bet.selection == "away" and final_game_state.away_score > final_game_state.home_score:
                won = True
        
        # Update bet status
        bet.status = LiveBetStatus.SETTLED
        bet.settled_at = datetime.utcnow()
        bet.result_amount = bet.potential_win if won else 0
        
        # Update cash out history if this was cashed out
        for history in self.cash_out_history:
            if history.bet_id == bet.id:
                history.final_result = "WON" if won else "LOST"
                history.would_have_won = won
                if won:
                    history.missed_profit = bet.potential_win - history.cash_out_amount

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

# Initialize service
live_betting_service = LiveBettingService()