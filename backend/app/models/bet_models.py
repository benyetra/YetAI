from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class BetType(str, Enum):
    MONEYLINE = "moneyline"
    SPREAD = "spread"
    TOTAL = "total"
    PARLAY = "parlay"

class BetStatus(str, Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    PUSHED = "pushed"
    CANCELLED = "cancelled"
    LIVE = "live"

class PlaceBetRequest(BaseModel):
    game_id: str
    bet_type: BetType
    selection: str
    odds: float
    amount: float = Field(gt=0, le=10000)
    # Optional game details for better bet history display
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    sport: Optional[str] = None
    commence_time: Optional[datetime] = None

class ParlayLeg(BaseModel):
    game_id: str
    bet_type: BetType
    selection: str
    odds: float
    
class PlaceParlayRequest(BaseModel):
    legs: List[ParlayLeg]
    amount: float = Field(gt=0, le=10000)

class BetResponse(BaseModel):
    id: str
    user_id: int
    game_id: Optional[str]
    bet_type: BetType
    selection: str
    odds: float
    amount: float
    potential_win: float
    status: BetStatus
    placed_at: datetime
    settled_at: Optional[datetime]
    result_amount: Optional[float]
    parlay_id: Optional[str]
    # Additional game details for better display
    home_team: Optional[str] = None
    away_team: Optional[str] = None
    sport: Optional[str] = None
    commence_time: Optional[datetime] = None

class BetHistoryQuery(BaseModel):
    status: Optional[BetStatus] = None
    bet_type: Optional[BetType] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(default=50, le=100)
    offset: int = Field(default=0, ge=0)

class BetStats(BaseModel):
    total_bets: int
    total_wagered: float
    total_won: float
    total_lost: float
    net_profit: float
    win_rate: float
    average_bet: float
    average_odds: float
    best_win: float
    worst_loss: float
    current_streak: int
    longest_win_streak: int
    longest_loss_streak: int

# YetAI Bets Models for Admin-Created Best Bets
class YetAIBetType(str, Enum):
    STRAIGHT = "straight"
    PARLAY = "parlay"

class CreateYetAIBetRequest(BaseModel):
    sport: str
    game: str
    bet_type: str  # e.g., "Spread", "Moneyline", "Total", "Puck Line" 
    pick: str      # e.g., "Chiefs -3.5", "Over 228.5"
    odds: str      # e.g., "-110", "+150"
    confidence: int = Field(ge=50, le=100)
    reasoning: str
    game_time: str
    is_premium: bool = True
    bet_category: YetAIBetType = YetAIBetType.STRAIGHT
    
class CreateParlayBetRequest(BaseModel):
    name: str  # e.g., "3-Team NFL Parlay"
    legs: List[CreateYetAIBetRequest]
    total_odds: str  # e.g., "+650"
    confidence: int = Field(ge=50, le=100)
    reasoning: str
    is_premium: bool = True

class YetAIBet(BaseModel):
    id: str
    sport: str
    game: str
    bet_type: str
    pick: str
    odds: str
    confidence: int
    reasoning: str
    status: BetStatus = BetStatus.PENDING
    is_premium: bool
    game_time: str
    created_at: datetime
    settled_at: Optional[datetime] = None
    result: Optional[str] = None
    bet_category: YetAIBetType
    created_by_admin: int  # admin user ID
    
class UpdateYetAIBetRequest(BaseModel):
    status: Optional[BetStatus] = None
    result: Optional[str] = None
    
class YetAIBetResponse(BaseModel):
    bets: List[YetAIBet]
    total_count: int
    performance_stats: Dict[str, Any]