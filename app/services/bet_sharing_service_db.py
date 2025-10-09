"""
Database-powered bet sharing service for persistent storage
"""

import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.core.database import SessionLocal
from app.models.database_models import User, Bet, ParlayBet, SharedBet
from app.models.bet_models import BetStatus

logger = logging.getLogger(__name__)


class BetSharingServiceDB:
    """Database-powered bet sharing functionality"""

    def __init__(self):
        pass

    async def create_shareable_link(self, user_id: int, bet_data: Dict) -> Dict:
        """Create a shareable link for a bet with database persistence"""
        try:
            db = SessionLocal()
            try:
                # Generate unique share ID
                share_id = str(uuid.uuid4())[:8]  # Short ID for easier sharing

                # Determine if this is a regular bet or parlay
                bet_id = bet_data.get("id")
                parlay_id = None

                # Check if this is a parlay bet
                if bet_data.get("bet_type") == "parlay" or bet_data.get("legs"):
                    parlay_id = bet_id
                    bet_id = None

                # Create shareable bet data (remove sensitive info)
                shareable_data = {
                    "id": share_id,
                    "bet_id": bet_id,
                    "parlay_id": parlay_id,
                    "user_id": user_id,
                    "bet_type": bet_data.get("bet_type"),
                    "selection": bet_data.get("selection"),
                    "odds": bet_data.get("odds") or bet_data.get("total_odds"),
                    "amount": bet_data.get("amount"),
                    "potential_win": bet_data.get("potential_win"),
                    "status": bet_data.get("status"),
                    "placed_at": bet_data.get("placed_at"),
                    "result_amount": bet_data.get("result_amount"),
                    "home_team": bet_data.get("home_team"),
                    "away_team": bet_data.get("away_team"),
                    "sport": bet_data.get("sport"),
                    "commence_time": bet_data.get("commence_time"),
                    "legs": bet_data.get(
                        "legs", []
                    ),  # Include parlay legs if available
                    "leg_count": bet_data.get("leg_count")
                    or len(bet_data.get("legs", [])),
                    "shared_at": datetime.utcnow().isoformat(),
                    "expires_at": (
                        datetime.utcnow() + timedelta(days=30)
                    ).isoformat(),  # Links expire in 30 days
                    "views": 0,
                    "is_public": True,
                }

                # Create shared bet record
                shared_bet = SharedBet(
                    id=share_id,
                    user_id=user_id,
                    bet_id=bet_id,
                    parlay_id=parlay_id,
                    bet_data=shareable_data,
                    created_at=datetime.utcnow(),
                    expires_at=datetime.utcnow() + timedelta(days=30),
                    views=0,
                    is_public=True,
                )

                db.add(shared_bet)
                db.commit()

                logger.info(
                    f"Created shareable link: {share_id} for bet {bet_data.get('id')} by user {user_id}"
                )

                return {
                    "success": True,
                    "share_id": share_id,
                    "share_url": f"/share/bet/{share_id}",
                    "expires_at": shared_bet.expires_at.isoformat(),
                    "message": "Shareable link created successfully",
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error creating shareable link: {e}")
            return {"success": False, "error": str(e)}

    async def get_shared_bet(
        self, share_id: str, viewer_ip: Optional[str] = None
    ) -> Dict:
        """Get shared bet data from database"""
        try:
            db = SessionLocal()
            try:
                shared_bet = (
                    db.query(SharedBet).filter(SharedBet.id == share_id).first()
                )

                if not shared_bet:
                    return {"success": False, "error": "Shared bet not found"}

                # Check if link has expired
                if datetime.utcnow() > shared_bet.expires_at:
                    return {"success": False, "error": "Shared link has expired"}

                # Increment view count (in production, would track unique views)
                shared_bet.views += 1
                db.commit()

                return {
                    "success": True,
                    "shared_bet": shared_bet.bet_data,
                    "message": "Shared bet retrieved successfully",
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error retrieving shared bet {share_id}: {e}")
            return {"success": False, "error": str(e)}

    async def get_user_shared_bets(self, user_id: int) -> Dict:
        """Get all shared bets created by a user from database"""
        try:
            db = SessionLocal()
            try:
                shared_bets = (
                    db.query(SharedBet)
                    .filter(SharedBet.user_id == user_id)
                    .order_by(SharedBet.created_at.desc())
                    .all()
                )

                user_shared_bets = []
                for shared_bet in shared_bets:
                    # Check if still active (not expired)
                    is_active = datetime.utcnow() <= shared_bet.expires_at

                    bet_data = shared_bet.bet_data
                    user_shared_bets.append(
                        {
                            "share_id": shared_bet.id,
                            "bet_id": shared_bet.bet_id,
                            "parlay_id": shared_bet.parlay_id,
                            "bet_type": bet_data.get("bet_type"),
                            "selection": bet_data.get("selection"),
                            "amount": bet_data.get("amount"),
                            "shared_at": shared_bet.created_at.isoformat(),
                            "expires_at": shared_bet.expires_at.isoformat(),
                            "views": shared_bet.views,
                            "is_active": is_active,
                        }
                    )

                return {
                    "success": True,
                    "shared_bets": user_shared_bets,
                    "total": len(user_shared_bets),
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error retrieving user shared bets for user {user_id}: {e}")
            return {"success": False, "error": str(e)}

    async def delete_shared_bet(self, user_id: int, share_id: str) -> Dict:
        """Delete a shared bet link from database"""
        try:
            db = SessionLocal()
            try:
                shared_bet = (
                    db.query(SharedBet)
                    .filter(
                        and_(SharedBet.id == share_id, SharedBet.user_id == user_id)
                    )
                    .first()
                )

                if not shared_bet:
                    return {
                        "success": False,
                        "error": "Shared bet not found or unauthorized",
                    }

                # Remove the shared bet
                db.delete(shared_bet)
                db.commit()

                logger.info(f"Deleted shared bet: {share_id} by user {user_id}")

                return {"success": True, "message": "Shared bet deleted successfully"}

            finally:
                db.close()

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
                        if leg.get("bet_type"):
                            leg_text += f" ({leg['bet_type']})"
                        if leg.get("odds"):
                            odds = int(leg["odds"])
                            formatted_odds = f"+{odds}" if odds > 0 else str(odds)
                            leg_text += f" {formatted_odds}"
                        leg_descriptions.append(leg_text)

                    bet_description = f"{len(legs)}-Leg Parlay:\\n" + "\\n".join(
                        leg_descriptions
                    )
                else:
                    bet_description = f"{bet_data.get('leg_count', 'Multi')}-Leg Parlay"
            # Handle regular bets
            elif bet_data.get("home_team") and bet_data.get("away_team"):
                game_info = f"{bet_data['away_team']} @ {bet_data['home_team']}"
                if bet_data["bet_type"] == "moneyline":
                    team = (
                        bet_data["home_team"]
                        if bet_data["selection"] == "home"
                        else bet_data["away_team"]
                    )
                    bet_description = f"{team} to Win ({game_info})"
                elif bet_data["bet_type"] == "spread":
                    team = (
                        bet_data["home_team"]
                        if bet_data["selection"] == "home"
                        else bet_data["away_team"]
                    )
                    bet_description = f"{team} Spread ({game_info})"
                elif bet_data["bet_type"] == "total":
                    bet_description = f"{bet_data['selection'].upper()} ({game_info})"
                else:
                    bet_description = f"{bet_data['bet_type'].upper()} - {bet_data['selection'].upper()}"
            else:
                bet_description = (
                    f"{bet_data['bet_type'].upper()} - {bet_data['selection'].upper()}"
                )

            # Get status emoji
            status_emojis = {"won": "🏆", "lost": "😤", "pending": "⏰", "live": "🔴"}
            emoji = status_emojis.get(bet_data.get("status", "pending"), "🎲")

            # Format odds
            odds = bet_data.get("odds") or bet_data.get("total_odds", 0)
            formatted_odds = f"+{int(odds)}" if odds > 0 else str(int(odds))

            # Create share text
            status_text = (
                "placed"
                if bet_data.get("status") == "pending"
                else bet_data.get("status", "placed")
            )
            share_text = f"{emoji} Just {status_text} a bet on {bet_description}!\\n\\n"
            share_text += f"💰 Bet: ${bet_data.get('amount', 0):.2f}\\n"
            share_text += f"📊 Odds: {formatted_odds}\\n"
            share_text += (
                f"🎯 Potential Win: ${bet_data.get('potential_win', 0):.2f}\\n\\n"
            )
            share_text += "#SportsBetting #YetAI"

            return share_text

        except Exception as e:
            logger.error(f"Error formatting bet for sharing: {e}")
            return "Check out my sports bet! 🎲 #SportsBetting #YetAI"

    async def get_bet_for_sharing(
        self, user_id: int, bet_id: str, is_parlay: bool = False
    ) -> Dict:
        """Get bet or parlay data for sharing"""
        try:
            db = SessionLocal()
            try:
                if is_parlay:
                    # Get parlay bet
                    parlay = (
                        db.query(ParlayBet)
                        .filter(
                            and_(ParlayBet.id == bet_id, ParlayBet.user_id == user_id)
                        )
                        .first()
                    )

                    if not parlay:
                        return {"success": False, "error": "Parlay not found"}

                    # Get legs
                    legs = db.query(Bet).filter(Bet.parlay_id == bet_id).all()

                    bet_data = {
                        "id": parlay.id,
                        "bet_type": "parlay",
                        "amount": parlay.amount,
                        "total_odds": parlay.total_odds,
                        "potential_win": parlay.potential_win,
                        "status": parlay.status,
                        "placed_at": parlay.placed_at.isoformat(),
                        "leg_count": parlay.leg_count,
                        "legs": [
                            {
                                "selection": leg.selection,
                                "bet_type": leg.bet_type,
                                "odds": leg.odds,
                                "status": leg.status,
                            }
                            for leg in legs
                        ],
                    }
                else:
                    # Get regular bet
                    bet = (
                        db.query(Bet)
                        .filter(
                            and_(
                                Bet.id == bet_id,
                                Bet.user_id == user_id,
                                Bet.parlay_id.is_(None),  # Not a parlay leg
                            )
                        )
                        .first()
                    )

                    if not bet:
                        return {"success": False, "error": "Bet not found"}

                    bet_data = {
                        "id": bet.id,
                        "bet_type": bet.bet_type,
                        "selection": bet.selection,
                        "odds": bet.odds,
                        "amount": bet.amount,
                        "potential_win": bet.potential_win,
                        "status": bet.status,
                        "placed_at": bet.placed_at.isoformat(),
                        "home_team": bet.home_team,
                        "away_team": bet.away_team,
                        "sport": bet.sport,
                        "commence_time": (
                            bet.commence_time.isoformat() if bet.commence_time else None
                        ),
                    }

                return {"success": True, "bet_data": bet_data}

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting bet for sharing: {e}")
            return {"success": False, "error": str(e)}

    async def cleanup_expired_shares(self) -> Dict:
        """Clean up expired shared bet links"""
        try:
            db = SessionLocal()
            try:
                expired_count = (
                    db.query(SharedBet)
                    .filter(SharedBet.expires_at < datetime.utcnow())
                    .count()
                )

                # Delete expired shares
                db.query(SharedBet).filter(
                    SharedBet.expires_at < datetime.utcnow()
                ).delete()

                db.commit()

                logger.info(f"Cleaned up {expired_count} expired shared bet links")

                return {
                    "success": True,
                    "deleted_count": expired_count,
                    "message": f"Cleaned up {expired_count} expired links",
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error cleaning up expired shares: {e}")
            return {"success": False, "error": str(e)}


# Initialize service
bet_sharing_service_db = BetSharingServiceDB()
