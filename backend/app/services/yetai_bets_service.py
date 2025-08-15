# app/services/yetai_bets_service.py
"""Service for managing admin-created YetAI Bets"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional
from app.models.bet_models import (
    YetAIBet, 
    CreateYetAIBetRequest, 
    CreateParlayBetRequest,
    UpdateYetAIBetRequest,
    BetStatus,
    YetAIBetType
)
import logging

logger = logging.getLogger(__name__)

class YetAIBetsService:
    """Handle admin-created best bets for the YetAI Bets page"""
    
    def __init__(self):
        # In-memory storage for YetAI Bets (replace with database in production)
        self.yetai_bets = {}
        self.create_sample_bets()
    
    async def create_bet(self, bet_request: CreateYetAIBetRequest, admin_user_id: int) -> Dict:
        """Create a new YetAI Bet"""
        try:
            bet_id = str(uuid.uuid4())
            
            new_bet = YetAIBet(
                id=bet_id,
                sport=bet_request.sport,
                game=bet_request.game,
                bet_type=bet_request.bet_type,
                pick=bet_request.pick,
                odds=bet_request.odds,
                confidence=bet_request.confidence,
                reasoning=bet_request.reasoning,
                is_premium=bet_request.is_premium,
                game_time=bet_request.game_time,
                bet_category=bet_request.bet_category,
                created_at=datetime.utcnow(),
                created_by_admin=admin_user_id
            )
            
            self.yetai_bets[bet_id] = new_bet.dict()
            
            logger.info(f"Created YetAI Bet: {bet_id} by admin {admin_user_id}")
            
            return {
                "success": True,
                "bet_id": bet_id,
                "message": "YetAI Bet created successfully"
            }
            
        except Exception as e:
            logger.error(f"Error creating YetAI Bet: {e}")
            return {"success": False, "error": "Failed to create bet"}
    
    async def create_parlay(self, parlay_request: CreateParlayBetRequest, admin_user_id: int) -> Dict:
        """Create a new YetAI Parlay Bet"""
        try:
            parlay_id = str(uuid.uuid4())
            
            # Create main parlay entry
            parlay_bet = YetAIBet(
                id=parlay_id,
                sport="Multi-Sport",
                game=parlay_request.name,
                bet_type="Parlay",
                pick=f"{len(parlay_request.legs)}-Team Parlay",
                odds=parlay_request.total_odds,
                confidence=parlay_request.confidence,
                reasoning=parlay_request.reasoning,
                is_premium=parlay_request.is_premium,
                game_time="Various",
                bet_category=YetAIBetType.PARLAY,
                created_at=datetime.utcnow(),
                created_by_admin=admin_user_id
            )
            
            # Store parlay with legs
            self.yetai_bets[parlay_id] = {
                **parlay_bet.dict(),
                "parlay_legs": [leg.dict() for leg in parlay_request.legs]
            }
            
            logger.info(f"Created YetAI Parlay: {parlay_id} with {len(parlay_request.legs)} legs by admin {admin_user_id}")
            
            return {
                "success": True,
                "bet_id": parlay_id,
                "message": "YetAI Parlay created successfully"
            }
            
        except Exception as e:
            logger.error(f"Error creating YetAI Parlay: {e}")
            return {"success": False, "error": "Failed to create parlay"}
    
    async def get_active_bets(self, user_tier: str = "free") -> List[Dict]:
        """Get active YetAI Bets based on user tier"""
        try:
            active_bets = []
            
            for bet_data in self.yetai_bets.values():
                # Only return pending bets for the main page
                if bet_data["status"] == "pending":
                    # For free users, only show non-premium bets
                    if user_tier == "free" and bet_data["is_premium"]:
                        continue
                    active_bets.append(bet_data)
            
            # Sort by confidence (highest first)
            active_bets.sort(key=lambda x: x["confidence"], reverse=True)
            
            return active_bets
            
        except Exception as e:
            logger.error(f"Error getting active bets: {e}")
            return []
    
    async def get_all_bets(self, include_settled: bool = True) -> List[Dict]:
        """Get all YetAI Bets for admin view"""
        try:
            all_bets = list(self.yetai_bets.values())
            
            if not include_settled:
                all_bets = [bet for bet in all_bets if bet["status"] == "pending"]
            
            # Sort by created_at (newest first)
            all_bets.sort(key=lambda x: x["created_at"], reverse=True)
            
            return all_bets
            
        except Exception as e:
            logger.error(f"Error getting all bets: {e}")
            return []
    
    async def update_bet(self, bet_id: str, update_request: UpdateYetAIBetRequest, admin_user_id: int) -> Dict:
        """Update a YetAI Bet (settle, update status, etc.)"""
        try:
            if bet_id not in self.yetai_bets:
                return {"success": False, "error": "Bet not found"}
            
            bet = self.yetai_bets[bet_id]
            
            if update_request.status:
                bet["status"] = update_request.status
                if update_request.status in ["won", "lost", "pushed"]:
                    bet["settled_at"] = datetime.utcnow().isoformat()
            
            if update_request.result:
                bet["result"] = update_request.result
            
            logger.info(f"Updated YetAI Bet: {bet_id} by admin {admin_user_id}")
            
            return {
                "success": True,
                "message": "Bet updated successfully"
            }
            
        except Exception as e:
            logger.error(f"Error updating bet: {e}")
            return {"success": False, "error": "Failed to update bet"}
    
    async def delete_bet(self, bet_id: str, admin_user_id: int) -> Dict:
        """Delete a YetAI Bet"""
        try:
            if bet_id not in self.yetai_bets:
                return {"success": False, "error": "Bet not found"}
            
            del self.yetai_bets[bet_id]
            
            logger.info(f"Deleted YetAI Bet: {bet_id} by admin {admin_user_id}")
            
            return {
                "success": True,
                "message": "Bet deleted successfully"
            }
            
        except Exception as e:
            logger.error(f"Error deleting bet: {e}")
            return {"success": False, "error": "Failed to delete bet"}
    
    async def get_performance_stats(self) -> Dict:
        """Calculate performance statistics for YetAI Bets"""
        try:
            all_bets = list(self.yetai_bets.values())
            
            if not all_bets:
                return {
                    "total_bets": 0,
                    "win_rate": 0,
                    "pending_bets": 0
                }
            
            settled_bets = [bet for bet in all_bets if bet["status"] in ["won", "lost"]]
            won_bets = [bet for bet in settled_bets if bet["status"] == "won"]
            pending_bets = [bet for bet in all_bets if bet["status"] == "pending"]
            
            win_rate = (len(won_bets) / len(settled_bets) * 100) if settled_bets else 0
            
            return {
                "total_bets": len(all_bets),
                "settled_bets": len(settled_bets),
                "won_bets": len(won_bets),
                "pending_bets": len(pending_bets),
                "win_rate": round(win_rate, 1)
            }
            
        except Exception as e:
            logger.error(f"Error calculating performance stats: {e}")
            return {"total_bets": 0, "win_rate": 0, "pending_bets": 0}
    
    def create_sample_bets(self):
        """Create some sample YetAI Bets for demonstration"""
        try:
            sample_bets = [
                {
                    "sport": "NFL",
                    "game": "Chiefs vs Bills",
                    "bet_type": "Spread",
                    "pick": "Chiefs -3.5",
                    "odds": "-110",
                    "confidence": 92,
                    "reasoning": "Chiefs have excellent road record vs top defenses. Buffalo missing key defensive players. Weather favors KC running game.",
                    "game_time": "8:20 PM EST",
                    "is_premium": False
                },
                {
                    "sport": "NBA",
                    "game": "Lakers vs Warriors",
                    "bet_type": "Total",
                    "pick": "Over 228.5",
                    "odds": "-105",
                    "confidence": 87,
                    "reasoning": "Both teams ranking in top 5 for pace. Lakers missing defensive anchor, Warriors at home average 118 PPG.",
                    "game_time": "10:30 PM EST",
                    "is_premium": True
                },
                {
                    "sport": "MLB",
                    "game": "Dodgers vs Padres",
                    "bet_type": "Moneyline",
                    "pick": "Dodgers ML",
                    "odds": "-135",
                    "confidence": 89,
                    "reasoning": "Pitcher matchup heavily favors LAD. Padres bullpen fatigued from extra innings yesterday. Wind blowing out favors Dodgers power.",
                    "game_time": "9:40 PM EST",
                    "is_premium": True
                },
                {
                    "sport": "NHL",
                    "game": "Rangers vs Bruins",
                    "bet_type": "Puck Line",
                    "pick": "Rangers +1.5",
                    "odds": "-180",
                    "confidence": 84,
                    "reasoning": "Rangers excellent in back-to-back games. Bruins on 4-game road trip, fatigue factor. Shesterkin expected to start.",
                    "game_time": "7:00 PM EST",
                    "is_premium": True
                }
            ]
            
            for bet_data in sample_bets:
                bet_id = str(uuid.uuid4())
                
                bet = YetAIBet(
                    id=bet_id,
                    sport=bet_data["sport"],
                    game=bet_data["game"],
                    bet_type=bet_data["bet_type"],
                    pick=bet_data["pick"],
                    odds=bet_data["odds"],
                    confidence=bet_data["confidence"],
                    reasoning=bet_data["reasoning"],
                    is_premium=bet_data["is_premium"],
                    game_time=bet_data["game_time"],
                    bet_category=YetAIBetType.STRAIGHT,
                    created_at=datetime.utcnow(),
                    created_by_admin=1  # Default admin user
                )
                
                self.yetai_bets[bet_id] = bet.dict()
            
            logger.info("Sample YetAI Bets created successfully")
            
        except Exception as e:
            logger.error(f"Error creating sample bets: {e}")

# Service instance
yetai_bets_service = YetAIBetsService()