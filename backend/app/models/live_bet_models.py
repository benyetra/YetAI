from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class LiveBetStatus(str, Enum):
    """Status for live bets"""
    ACTIVE = "active"  # Bet is live and game is in progress
    SUSPENDED = "suspended"  # Temporarily unavailable (timeout, review, etc)
    CASHED_OUT = "cashed_out"  # User cashed out
    SETTLED = "settled"  # Game ended, bet settled
    VOID = "void"  # Bet voided (game cancelled, etc)

class GameStatus(str, Enum):
    """Real-time game status"""
    PRE_GAME = "pre_game"
    FIRST_QUARTER = "1st_quarter"
    SECOND_QUARTER = "2nd_quarter"
    THIRD_QUARTER = "3rd_quarter"
    FOURTH_QUARTER = "4th_quarter"
    HALFTIME = "halftime"
    OVERTIME = "overtime"
    FINAL = "final"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    # For other sports
    FIRST_HALF = "1st_half"
    SECOND_HALF = "2nd_half"
    FIRST_PERIOD = "1st_period"
    SECOND_PERIOD = "2nd_period"
    THIRD_PERIOD = "3rd_period"
    FIRST_INNING = "1st_inning"
    SECOND_INNING = "2nd_inning"
    THIRD_INNING = "3rd_inning"
    FOURTH_INNING = "4th_inning"
    FIFTH_INNING = "5th_inning"
    SIXTH_INNING = "6th_inning"
    SEVENTH_INNING = "7th_inning"
    EIGHTH_INNING = "8th_inning"
    NINTH_INNING = "9th_inning"
    # Add more as needed

class LiveOddsUpdate(BaseModel):
    """Real-time odds update for live betting"""
    game_id: str
    bet_type: str  # moneyline, spread, total
    home_odds: float
    away_odds: float
    spread: Optional[float] = None
    total: Optional[float] = None
    timestamp: datetime
    is_suspended: bool = False
    suspension_reason: Optional[str] = None

class LiveGameUpdate(BaseModel):
    """Real-time game state update"""
    game_id: str
    status: GameStatus
    home_score: int
    away_score: int
    time_remaining: Optional[str] = None  # "12:34" format
    quarter: Optional[int] = None
    period: Optional[int] = None
    inning: Optional[int] = None
    possession: Optional[str] = None  # team with possession
    last_play: Optional[str] = None  # description of last play
    timestamp: datetime

class CashOutRequest(BaseModel):
    """Request to cash out a live bet"""
    bet_id: str
    accept_amount: Optional[float] = None  # If None, get current offer

class CashOutOffer(BaseModel):
    """Cash out offer for a live bet"""
    bet_id: str
    original_amount: float
    original_potential_win: float
    current_cash_out_value: float
    profit_loss: float  # positive if profit, negative if loss
    offer_expires_at: datetime
    is_available: bool
    reason: Optional[str] = None  # if not available

class LiveBet(BaseModel):
    """Enhanced bet model for live betting"""
    id: str
    user_id: int
    game_id: str
    bet_type: str
    selection: str
    original_odds: float
    current_odds: Optional[float] = None
    amount: float
    potential_win: float
    current_potential_win: Optional[float] = None
    status: LiveBetStatus
    placed_at: datetime
    game_status_at_placement: GameStatus
    current_game_status: Optional[GameStatus] = None
    home_score_at_placement: int = 0
    away_score_at_placement: int = 0
    current_home_score: Optional[int] = None
    current_away_score: Optional[int] = None
    cash_out_available: bool = False
    cash_out_value: Optional[float] = None
    cashed_out_at: Optional[datetime] = None
    cashed_out_amount: Optional[float] = None
    settled_at: Optional[datetime] = None
    result_amount: Optional[float] = None

class PlaceLiveBetRequest(BaseModel):
    """Request to place a live bet"""
    game_id: str
    bet_type: str  # moneyline, spread, total
    selection: str  # home, away, over, under
    odds: float
    amount: float = Field(gt=0, le=10000)
    accept_odds_change: bool = False  # Accept if odds change slightly
    min_odds: Optional[float] = None  # Minimum acceptable odds

class LiveBetResponse(BaseModel):
    """Response after placing a live bet"""
    success: bool
    bet: Optional[LiveBet] = None
    error: Optional[str] = None
    odds_changed: bool = False
    new_odds: Optional[float] = None

class LiveBettingStats(BaseModel):
    """Statistics for live betting"""
    total_live_bets: int
    active_live_bets: int
    total_cashed_out: int
    total_cash_out_profit: float
    total_cash_out_loss: float
    average_cash_out_percentage: float  # % of original potential win
    best_cash_out: Dict[str, Any]
    worst_cash_out: Dict[str, Any]

class LiveBettingMarket(BaseModel):
    """Live betting market for a game"""
    game_id: str
    sport: str
    home_team: str
    away_team: str
    game_status: GameStatus
    home_score: int
    away_score: int
    time_remaining: Optional[str] = None
    commence_time: Optional[datetime] = None
    markets_available: List[str]  # ["moneyline", "spread", "total"]
    moneyline_home: Optional[float] = None
    moneyline_away: Optional[float] = None
    spread_line: Optional[float] = None
    spread_home_odds: Optional[float] = None
    spread_away_odds: Optional[float] = None
    total_line: Optional[float] = None
    total_over_odds: Optional[float] = None
    total_under_odds: Optional[float] = None
    moneyline_bookmaker: Optional[str] = None
    spread_bookmaker: Optional[str] = None
    total_bookmaker: Optional[str] = None
    is_suspended: bool = False
    suspension_reason: Optional[str] = None
    last_updated: datetime

class CashOutHistory(BaseModel):
    """History of cash out transactions"""
    bet_id: str
    game_id: str
    original_bet_amount: float
    original_potential_win: float
    cash_out_amount: float
    profit_loss: float
    cash_out_percentage: float  # % of original potential win
    game_status_at_cash_out: GameStatus
    score_at_cash_out: str  # "HOME 14 - AWAY 10"
    cashed_out_at: datetime
    final_result: Optional[str] = None  # What would have happened
    would_have_won: Optional[bool] = None
    missed_profit: Optional[float] = None  # If would have won