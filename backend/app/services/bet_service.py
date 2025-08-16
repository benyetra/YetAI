import uuid
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging
from app.models.bet_models import *

logger = logging.getLogger(__name__)

class BetService:
    """Handle bet placement, tracking, and settlement"""
    
    def __init__(self):
        # In-memory storage (replace with database in production)
        self.bets = {}
        self.user_bets = {}  # user_id -> list of bet_ids
        self.parlay_bets = {}
        self.bet_limits = {
            "daily": 5000,
            "weekly": 20000,
            "single_bet": 10000
        }
        
    async def place_bet(self, user_id: int, bet_data: PlaceBetRequest) -> Dict:
        """Place a single bet"""
        try:
            # Validate bet limits
            if not await self._check_bet_limits(user_id, bet_data.amount):
                return {"success": False, "error": "Bet exceeds limits"}
            
            # Generate bet ID
            bet_id = str(uuid.uuid4())
            
            # Calculate potential winnings
            potential_win = self._calculate_potential_win(
                bet_data.amount, 
                bet_data.odds
            )
            
            # Create bet record
            bet = BetResponse(
                id=bet_id,
                user_id=user_id,
                game_id=bet_data.game_id,
                bet_type=bet_data.bet_type,
                selection=bet_data.selection,
                odds=bet_data.odds,
                amount=bet_data.amount,
                potential_win=potential_win,
                status=BetStatus.PENDING,
                placed_at=datetime.utcnow(),
                settled_at=None,
                result_amount=None,
                parlay_id=None
            )
            
            # Store bet
            self.bets[bet_id] = bet.dict()
            
            # Track user bets
            if user_id not in self.user_bets:
                self.user_bets[user_id] = []
            self.user_bets[user_id].append(bet_id)
            
            logger.info(f"Bet placed: {bet_id} for user {user_id}")
            
            return {
                "success": True,
                "bet": bet.dict(),
                "message": "Bet placed successfully"
            }
            
        except Exception as e:
            logger.error(f"Error placing bet: {e}")
            return {"success": False, "error": str(e)}
    
    async def place_parlay(self, user_id: int, parlay_data: PlaceParlayRequest) -> Dict:
        """Place a parlay bet with multiple legs"""
        try:
            if len(parlay_data.legs) < 2:
                return {"success": False, "error": "Parlay must have at least 2 legs"}
            
            if len(parlay_data.legs) > 10:
                return {"success": False, "error": "Maximum 10 legs allowed in parlay"}
            
            # Check bet limits
            if not await self._check_bet_limits(user_id, parlay_data.amount):
                return {"success": False, "error": "Bet exceeds limits"}
            
            # Calculate parlay odds
            total_odds = 1.0
            for leg in parlay_data.legs:
                decimal_odds = self._american_to_decimal(leg.odds)
                total_odds *= decimal_odds
            
            # Convert back to American odds
            parlay_odds = self._decimal_to_american(total_odds)
            potential_win = (total_odds - 1) * parlay_data.amount
            
            # Generate parlay ID
            parlay_id = str(uuid.uuid4())
            
            # Create main parlay bet
            parlay_bet = BetResponse(
                id=parlay_id,
                user_id=user_id,
                game_id=None,
                bet_type=BetType.PARLAY,
                selection=f"Parlay ({len(parlay_data.legs)} legs)",
                odds=parlay_odds,
                amount=parlay_data.amount,
                potential_win=potential_win,
                status=BetStatus.PENDING,
                placed_at=datetime.utcnow(),
                settled_at=None,
                result_amount=None,
                parlay_id=None
            )
            
            # Store main parlay
            self.bets[parlay_id] = parlay_bet.dict()
            self.parlay_bets[parlay_id] = {"legs": [], "status": "pending"}
            
            # Create individual leg bets
            for leg in parlay_data.legs:
                leg_id = str(uuid.uuid4())
                leg_bet = BetResponse(
                    id=leg_id,
                    user_id=user_id,
                    game_id=leg.game_id,
                    bet_type=leg.bet_type,
                    selection=leg.selection,
                    odds=leg.odds,
                    amount=0,  # Individual legs don't have separate amounts
                    potential_win=0,
                    status=BetStatus.PENDING,
                    placed_at=datetime.utcnow(),
                    settled_at=None,
                    result_amount=None,
                    parlay_id=parlay_id
                )
                
                self.bets[leg_id] = leg_bet.dict()
                self.parlay_bets[parlay_id]["legs"].append(leg_id)
            
            # Track user bets
            if user_id not in self.user_bets:
                self.user_bets[user_id] = []
            self.user_bets[user_id].append(parlay_id)
            
            return {
                "success": True,
                "parlay": parlay_bet.dict(),
                "legs": [self.bets[leg_id] for leg_id in self.parlay_bets[parlay_id]["legs"]],
                "message": f"Parlay placed with {len(parlay_data.legs)} legs"
            }
            
        except Exception as e:
            logger.error(f"Error placing parlay: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_bet_history(self, user_id: int, query: BetHistoryQuery) -> Dict:
        """Get user's bet history with filtering"""
        try:
            if user_id not in self.user_bets:
                return {"success": True, "bets": [], "total": 0}
            
            user_bet_ids = self.user_bets[user_id]
            filtered_bets = []
            
            for bet_id in user_bet_ids:
                bet = self.bets.get(bet_id)
                if not bet:
                    continue
                
                # Apply filters
                if query.status and bet["status"] != query.status:
                    continue
                if query.bet_type and bet["bet_type"] != query.bet_type:
                    continue
                if query.start_date and datetime.fromisoformat(bet["placed_at"].replace('Z', '+00:00')) < query.start_date:
                    continue
                if query.end_date and datetime.fromisoformat(bet["placed_at"].replace('Z', '+00:00')) > query.end_date:
                    continue
                
                filtered_bets.append(bet)
            
            # Sort by date (newest first)
            filtered_bets.sort(key=lambda x: x["placed_at"], reverse=True)
            
            # Apply pagination
            start = query.offset
            end = start + query.limit
            paginated_bets = filtered_bets[start:end]
            
            return {
                "success": True,
                "bets": paginated_bets,
                "total": len(filtered_bets),
                "offset": query.offset,
                "limit": query.limit
            }
            
        except Exception as e:
            logger.error(f"Error fetching bet history: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_bet_stats(self, user_id: int) -> Dict:
        """Get comprehensive betting statistics for a user"""
        try:
            if user_id not in self.user_bets:
                return {
                    "success": True,
                    "stats": BetStats(
                        total_bets=0,
                        total_wagered=0,
                        total_won=0,
                        total_lost=0,
                        net_profit=0,
                        win_rate=0,
                        average_bet=0,
                        average_odds=0,
                        best_win=0,
                        worst_loss=0,
                        current_streak=0,
                        longest_win_streak=0,
                        longest_loss_streak=0
                    ).dict()
                }
            
            user_bet_ids = self.user_bets[user_id]
            
            # Calculate statistics
            total_bets = 0
            total_wagered = 0
            total_won = 0
            total_lost = 0
            wins = 0
            losses = 0
            best_win = 0
            worst_loss = 0
            odds_sum = 0
            current_streak = 0
            longest_win_streak = 0
            longest_loss_streak = 0
            temp_streak = 0
            last_result = None
            
            for bet_id in user_bet_ids:
                bet = self.bets.get(bet_id)
                if not bet or bet.get("parlay_id"):  # Skip parlay legs
                    continue
                
                total_bets += 1
                total_wagered += bet["amount"]
                odds_sum += bet["odds"]
                
                if bet["status"] == BetStatus.WON:
                    wins += 1
                    win_amount = bet.get("result_amount", bet["potential_win"])
                    total_won += win_amount
                    best_win = max(best_win, win_amount)
                    
                    if last_result == "win":
                        temp_streak += 1
                    else:
                        temp_streak = 1
                    last_result = "win"
                    longest_win_streak = max(longest_win_streak, temp_streak)
                    current_streak = temp_streak if last_result == "win" else -current_streak
                    
                elif bet["status"] == BetStatus.LOST:
                    losses += 1
                    loss_amount = bet["amount"]
                    total_lost += loss_amount
                    worst_loss = max(worst_loss, loss_amount)
                    
                    if last_result == "loss":
                        temp_streak += 1
                    else:
                        temp_streak = 1
                    last_result = "loss"
                    longest_loss_streak = max(longest_loss_streak, temp_streak)
                    current_streak = -temp_streak if last_result == "loss" else current_streak
            
            win_rate = (wins / total_bets * 100) if total_bets > 0 else 0
            average_bet = total_wagered / total_bets if total_bets > 0 else 0
            average_odds = odds_sum / total_bets if total_bets > 0 else 0
            net_profit = total_won - total_lost
            
            stats = BetStats(
                total_bets=total_bets,
                total_wagered=round(total_wagered, 2),
                total_won=round(total_won, 2),
                total_lost=round(total_lost, 2),
                net_profit=round(net_profit, 2),
                win_rate=round(win_rate, 2),
                average_bet=round(average_bet, 2),
                average_odds=round(average_odds, 2),
                best_win=round(best_win, 2),
                worst_loss=round(worst_loss, 2),
                current_streak=current_streak,
                longest_win_streak=longest_win_streak,
                longest_loss_streak=longest_loss_streak
            )
            
            return {"success": True, "stats": stats.dict()}
            
        except Exception as e:
            logger.error(f"Error calculating stats: {e}")
            return {"success": False, "error": str(e)}
    
    async def cancel_bet(self, user_id: int, bet_id: str) -> Dict:
        """Cancel a pending bet"""
        try:
            bet = self.bets.get(bet_id)
            
            if not bet:
                return {"success": False, "error": "Bet not found"}
            
            if bet["user_id"] != user_id:
                return {"success": False, "error": "Unauthorized"}
            
            if bet["status"] != BetStatus.PENDING:
                return {"success": False, "error": "Can only cancel pending bets"}
            
            # Check if game has started (would need real game data)
            # For now, allow cancellation if placed within last 5 minutes
            placed_at = bet["placed_at"]
            if isinstance(placed_at, str):
                placed_at = datetime.fromisoformat(placed_at.replace('Z', '+00:00'))
            
            time_since_placed = datetime.utcnow() - placed_at.replace(tzinfo=None)
            if time_since_placed > timedelta(minutes=5):
                return {"success": False, "error": "Cancellation window has passed"}
            
            bet["status"] = BetStatus.CANCELLED
            bet["settled_at"] = datetime.utcnow().isoformat()
            
            return {"success": True, "message": "Bet cancelled successfully"}
            
        except Exception as e:
            logger.error(f"Error cancelling bet: {e}")
            return {"success": False, "error": str(e)}
    
    async def simulate_bet_results(self, user_id: int) -> Dict:
        """Simulate some bet results for demo purposes"""
        try:
            if user_id not in self.user_bets:
                return {"success": False, "error": "No bets found"}
            
            import random
            
            results_set = 0
            for bet_id in self.user_bets[user_id]:
                bet = self.bets.get(bet_id)
                if not bet or bet["status"] != BetStatus.PENDING:
                    continue
                
                # Randomly set some results (70% win rate for demo)
                if random.random() < 0.7:
                    bet["status"] = BetStatus.WON
                    bet["result_amount"] = bet["potential_win"]
                else:
                    bet["status"] = BetStatus.LOST
                    bet["result_amount"] = 0
                
                bet["settled_at"] = datetime.utcnow().isoformat()
                results_set += 1
                
                if results_set >= 5:  # Only set results for a few bets
                    break
            
            return {
                "success": True,
                "message": f"Simulated results for {results_set} bets"
            }
            
        except Exception as e:
            logger.error(f"Error simulating results: {e}")
            return {"success": False, "error": str(e)}
    
    def _calculate_potential_win(self, amount: float, odds: float) -> float:
        """Calculate potential winnings from American odds"""
        if odds > 0:
            return amount * (odds / 100)
        else:
            return amount * (100 / abs(odds))
    
    def _american_to_decimal(self, odds: float) -> float:
        """Convert American odds to decimal"""
        if odds > 0:
            return (odds / 100) + 1
        else:
            return (100 / abs(odds)) + 1
    
    def _decimal_to_american(self, odds: float) -> int:
        """Convert decimal odds to American"""
        if odds >= 2:
            return round((odds - 1) * 100)
        else:
            return round(-100 / (odds - 1))
    
    async def _check_bet_limits(self, user_id: int, amount: float) -> bool:
        """Check if bet amount is within user limits"""
        if amount > self.bet_limits["single_bet"]:
            return False
        
        # Check daily limit
        today_total = await self._get_period_total(user_id, timedelta(days=1))
        if today_total + amount > self.bet_limits["daily"]:
            return False
        
        # Check weekly limit
        week_total = await self._get_period_total(user_id, timedelta(days=7))
        if week_total + amount > self.bet_limits["weekly"]:
            return False
        
        return True
    
    async def get_user_parlays(self, user_id: int, status: Optional[str] = None, limit: int = 50) -> Dict:
        """Get user's parlay bets"""
        try:
            if user_id not in self.user_bets:
                return {"success": True, "parlays": [], "total": 0}
            
            user_bet_ids = self.user_bets[user_id]
            parlay_list = []
            
            # Get parlay bets (those with bet_type = PARLAY)
            for bet_id in user_bet_ids:
                bet = self.bets.get(bet_id)
                if not bet or bet.get("bet_type") != BetType.PARLAY:
                    continue
                
                # Apply status filter if provided
                if status and bet.get("status") != status:
                    continue
                
                # Get parlay details including legs
                parlay_id = bet_id
                parlay_info = self.parlay_bets.get(parlay_id, {})
                
                # Get leg details
                legs = []
                if "legs" in parlay_info:
                    for leg_id in parlay_info["legs"]:
                        leg_bet = self.bets.get(leg_id)
                        if leg_bet:
                            legs.append(leg_bet)
                
                parlay_data = {
                    "id": bet_id,
                    "user_id": bet["user_id"],
                    "amount": bet["amount"],
                    "potential_win": bet["potential_win"],
                    "status": bet["status"],
                    "placed_at": bet["placed_at"],
                    "settled_at": bet.get("settled_at"),
                    "result_amount": bet.get("result_amount"),
                    "legs": legs,
                    "leg_count": len(legs),
                    "total_odds": bet.get("odds", 0)
                }
                
                parlay_list.append(parlay_data)
            
            # Sort by date (newest first)
            parlay_list.sort(key=lambda x: x["placed_at"], reverse=True)
            
            # Apply limit
            if limit:
                parlay_list = parlay_list[:limit]
            
            return {
                "success": True,
                "parlays": parlay_list,
                "total": len(parlay_list)
            }
            
        except Exception as e:
            logger.error(f"Error fetching user parlays: {e}")
            return {"success": False, "error": str(e)}

    async def get_parlay_by_id(self, user_id: int, parlay_id: str) -> Dict:
        """Get specific parlay details by ID"""
        try:
            # Check if parlay exists and belongs to user
            bet = self.bets.get(parlay_id)
            if not bet:
                return {"success": False, "error": "Parlay not found"}
            
            if bet["user_id"] != user_id:
                return {"success": False, "error": "Unauthorized"}
            
            if bet["bet_type"] != BetType.PARLAY.value:
                return {"success": False, "error": "Not a parlay bet"}
            
            # Get parlay legs
            legs = []
            parlay_info = self.parlay_bets.get(parlay_id, {})
            if "legs" in parlay_info:
                for leg_id in parlay_info["legs"]:
                    leg_bet = self.bets.get(leg_id)
                    if leg_bet:
                        legs.append({
                            "id": leg_id,
                            "game_id": leg_bet.get("game_id"),
                            "bet_type": leg_bet["bet_type"],
                            "selection": leg_bet["selection"],
                            "odds": leg_bet["odds"],
                            "status": leg_bet["status"]
                        })
            
            parlay_data = {
                "id": parlay_id,
                "amount": bet["amount"],
                "potential_win": bet["potential_win"],
                "status": bet["status"],
                "placed_at": bet["placed_at"],
                "settled_at": bet.get("settled_at"),
                "result_amount": bet.get("result_amount"),
                "legs": legs,
                "leg_count": len(legs),
                "total_odds": bet.get("odds", 0)
            }
            
            return {"success": True, "parlay": parlay_data}
            
        except Exception as e:
            logger.error(f"Error fetching parlay {parlay_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def _get_period_total(self, user_id: int, period: timedelta) -> float:
        """Get total bet amount for a period"""
        if user_id not in self.user_bets:
            return 0
        
        cutoff = datetime.utcnow() - period
        total = 0
        
        for bet_id in self.user_bets[user_id]:
            bet = self.bets.get(bet_id)
            if not bet:
                continue
                
            placed_at = bet["placed_at"]
            if isinstance(placed_at, str):
                placed_at = datetime.fromisoformat(placed_at.replace('Z', '+00:00'))
            
            if placed_at.replace(tzinfo=None) > cutoff:
                total += bet["amount"]
        
        return total

# Initialize service
bet_service = BetService()