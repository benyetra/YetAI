import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging
from app.models.bet_models import *

logger = logging.getLogger(__name__)

class BetSharingService:
    """Handle bet sharing functionality"""
    
    def __init__(self):
        # In-memory storage for shared bets (replace with database in production)
        self.shared_bets = {}
        
    async def create_shareable_link(self, user_id: int, bet_data: Dict) -> Dict:
        """Create a shareable link for a bet"""
        try:
            # Generate unique share ID
            share_id = str(uuid.uuid4())[:8]  # Short ID for easier sharing
            
            # Create shareable bet data (remove sensitive info)
            shareable_data = {
                "id": share_id,
                "bet_id": bet_data.get("id"),
                "user_id": user_id,
                "bet_type": bet_data.get("bet_type"),
                "selection": bet_data.get("selection"),
                "odds": bet_data.get("odds"),
                "amount": bet_data.get("amount"),
                "potential_win": bet_data.get("potential_win"),
                "status": bet_data.get("status"),
                "placed_at": bet_data.get("placed_at"),
                "result_amount": bet_data.get("result_amount"),
                "home_team": bet_data.get("home_team"),
                "away_team": bet_data.get("away_team"),
                "sport": bet_data.get("sport"),
                "commence_time": bet_data.get("commence_time"),
                "legs": bet_data.get("legs", []),  # Include parlay legs if available
                "leg_count": len(bet_data.get("legs", [])) if bet_data.get("legs") else None,
                "shared_at": datetime.utcnow().isoformat(),
                "expires_at": (datetime.utcnow() + timedelta(days=30)).isoformat(),  # Links expire in 30 days
                "views": 0,
                "is_public": True
            }
            
            # Store the shareable bet
            self.shared_bets[share_id] = shareable_data
            
            logger.info(f"Created shareable link: {share_id} for bet {bet_data.get('id')} by user {user_id}")
            
            return {
                "success": True,
                "share_id": share_id,
                "share_url": f"/share/bet/{share_id}",
                "expires_at": shareable_data["expires_at"],
                "message": "Shareable link created successfully"
            }
            
        except Exception as e:
            logger.error(f"Error creating shareable link: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_shared_bet(self, share_id: str, viewer_ip: Optional[str] = None) -> Dict:
        """Get shared bet data"""
        try:
            shared_bet = self.shared_bets.get(share_id)
            
            if not shared_bet:
                return {"success": False, "error": "Shared bet not found"}
            
            # Check if link has expired
            expires_at = datetime.fromisoformat(shared_bet["expires_at"].replace('Z', '+00:00'))
            if datetime.utcnow() > expires_at.replace(tzinfo=None):
                return {"success": False, "error": "Shared link has expired"}
            
            # Increment view count (in production, would track unique views)
            shared_bet["views"] += 1
            
            return {
                "success": True,
                "shared_bet": shared_bet,
                "message": "Shared bet retrieved successfully"
            }
            
        except Exception as e:
            logger.error(f"Error retrieving shared bet {share_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_user_shared_bets(self, user_id: int) -> Dict:
        """Get all shared bets created by a user"""
        try:
            user_shared_bets = []
            
            for share_id, bet_data in self.shared_bets.items():
                if bet_data["user_id"] == user_id:
                    # Check if still active (not expired)
                    expires_at = datetime.fromisoformat(bet_data["expires_at"].replace('Z', '+00:00'))
                    is_active = datetime.utcnow() <= expires_at.replace(tzinfo=None)
                    
                    user_shared_bets.append({
                        "share_id": share_id,
                        "bet_id": bet_data["bet_id"],
                        "bet_type": bet_data["bet_type"],
                        "selection": bet_data["selection"],
                        "amount": bet_data["amount"],
                        "shared_at": bet_data["shared_at"],
                        "expires_at": bet_data["expires_at"],
                        "views": bet_data["views"],
                        "is_active": is_active
                    })
            
            # Sort by shared_at date (newest first)
            user_shared_bets.sort(key=lambda x: x["shared_at"], reverse=True)
            
            return {
                "success": True,
                "shared_bets": user_shared_bets,
                "total": len(user_shared_bets)
            }
            
        except Exception as e:
            logger.error(f"Error retrieving user shared bets for user {user_id}: {e}")
            return {"success": False, "error": str(e)}
    
    async def delete_shared_bet(self, user_id: int, share_id: str) -> Dict:
        """Delete a shared bet link"""
        try:
            shared_bet = self.shared_bets.get(share_id)
            
            if not shared_bet:
                return {"success": False, "error": "Shared bet not found"}
            
            if shared_bet["user_id"] != user_id:
                return {"success": False, "error": "Unauthorized to delete this shared bet"}
            
            # Remove the shared bet
            del self.shared_bets[share_id]
            
            logger.info(f"Deleted shared bet: {share_id} by user {user_id}")
            
            return {
                "success": True,
                "message": "Shared bet deleted successfully"
            }
            
        except Exception as e:
            logger.error(f"Error deleting shared bet {share_id}: {e}")
            return {"success": False, "error": str(e)}
    
    def format_bet_for_sharing(self, bet_data: Dict) -> str:
        """Format bet data for social media sharing"""
        try:
            # Handle parlay bets with legs
            if bet_data.get("bet_type") == "parlay" and bet_data.get("legs"):
                legs = bet_data.get("legs", [])
                if legs:
                    leg_descriptions = []
                    for i, leg in enumerate(legs):
                        leg_text = f"{i + 1}. {leg.get('selection', '').upper()}"
                        if leg.get('bet_type'):
                            leg_text += f" ({leg['bet_type']})"
                        if leg.get('odds'):
                            odds = int(leg['odds'])
                            formatted_odds = f"+{odds}" if odds > 0 else str(odds)
                            leg_text += f" {formatted_odds}"
                        leg_descriptions.append(leg_text)
                    
                    bet_description = f"{len(legs)}-Leg Parlay:\n" + "\n".join(leg_descriptions)
                else:
                    bet_description = f"{bet_data.get('leg_count', 'Multi')}-Leg Parlay"
            # Handle regular bets
            elif bet_data.get("home_team") and bet_data.get("away_team"):
                game_info = f"{bet_data['away_team']} @ {bet_data['home_team']}"
                if bet_data["bet_type"] == "moneyline":
                    team = bet_data["home_team"] if bet_data["selection"] == "home" else bet_data["away_team"]
                    bet_description = f"{team} to Win ({game_info})"
                elif bet_data["bet_type"] == "spread":
                    team = bet_data["home_team"] if bet_data["selection"] == "home" else bet_data["away_team"]
                    bet_description = f"{team} Spread ({game_info})"
                elif bet_data["bet_type"] == "total":
                    bet_description = f"{bet_data['selection'].upper()} ({game_info})"
                else:
                    bet_description = f"{bet_data['bet_type'].upper()} - {bet_data['selection'].upper()}"
            else:
                bet_description = f"{bet_data['bet_type'].upper()} - {bet_data['selection'].upper()}"
            
            # Get status emoji
            status_emojis = {
                "won": "🏆",
                "lost": "😤", 
                "pending": "⏰",
                "live": "🔴"
            }
            emoji = status_emojis.get(bet_data.get("status", "pending"), "🎲")
            
            # Format odds
            odds = bet_data.get("odds", 0)
            formatted_odds = f"+{int(odds)}" if odds > 0 else str(int(odds))
            
            # Create share text
            status_text = "placed" if bet_data.get("status") == "pending" else bet_data.get("status", "placed")
            share_text = f"{emoji} Just {status_text} a bet on {bet_description}!\n\n"
            share_text += f"💰 Bet: ${bet_data.get('amount', 0):.2f}\n"
            share_text += f"📊 Odds: {formatted_odds}\n"
            share_text += f"🎯 Potential Win: ${bet_data.get('potential_win', 0):.2f}\n\n"
            share_text += "#SportsBetting #YetAI"
            
            return share_text
            
        except Exception as e:
            logger.error(f"Error formatting bet for sharing: {e}")
            return "Check out my sports bet! 🎲 #SportsBetting #YetAI"

# Initialize service
bet_sharing_service = BetSharingService()