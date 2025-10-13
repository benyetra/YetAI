"""
Database-powered service for managing admin-created YetAI Bets
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.core.database import SessionLocal
from app.models.database_models import User, YetAIBet, SubscriptionTier, BetType
from app.models.bet_models import (
    CreateYetAIBetRequest,
    CreateParlayBetRequest,
    UpdateYetAIBetRequest,
    BetStatus,
    YetAIBetType,
)

logger = logging.getLogger(__name__)


class YetAIBetsServiceDB:
    """Database-powered admin-created best bets for the YetAI Bets page"""

    def __init__(self):
        # Initialize with sample bets if none exist
        self._create_sample_bets_if_needed()

    async def create_bet(
        self, bet_request: CreateYetAIBetRequest, admin_user_id: int
    ) -> Dict:
        """Create a new YetAI Bet with database persistence"""
        try:
            db = SessionLocal()
            try:
                bet_id = str(uuid.uuid4())

                # Debug: Log the incoming bet request data
                logger.info(
                    f"Creating YetAI Bet with data: sport={bet_request.sport}, game={bet_request.game}, game_time='{bet_request.game_time}'"
                )

                # Parse game_time to datetime if it's provided
                game_commence_time = None
                if (
                    hasattr(bet_request, "game_time")
                    and bet_request.game_time
                    and bet_request.game_time != "TBD"
                ):
                    try:
                        # Handle different formats that might come from the frontend
                        from dateutil import parser
                        import re

                        game_time_str = bet_request.game_time.strip()
                        logger.info(f"Attempting to parse game_time: '{game_time_str}'")

                        # Clean up the format - handle "@" symbol and EDT/EST
                        if "@" in game_time_str:
                            game_time_str = game_time_str.replace("@", "")

                        # Try to parse with dateutil
                        game_commence_time = parser.parse(game_time_str)
                        logger.info(
                            f"Successfully parsed game_time '{bet_request.game_time}' to datetime: {game_commence_time}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Could not parse game_time '{bet_request.game_time}': {e}"
                        )
                        game_commence_time = None

                # Map user-friendly bet types to database enum values
                bet_type_mapping = {
                    "total (over/under)": "total",
                    "total": "total",
                    "over/under": "total",
                    "spread": "spread",
                    "point spread": "spread",
                    "moneyline": "moneyline",
                    "money line": "moneyline",
                    "parlay": "parlay",
                    "prop": "prop",
                    "proposition": "prop",
                }

                # Normalize bet type to enum value
                normalized_bet_type = bet_type_mapping.get(
                    bet_request.bet_type.lower(), bet_request.bet_type.lower()
                )
                logger.info(
                    f"Mapped bet_type '{bet_request.bet_type}' to '{normalized_bet_type}'"
                )

                # Parse odds correctly to preserve sign
                odds_value = bet_request.odds
                if isinstance(odds_value, str):
                    if odds_value.startswith("+"):
                        odds_value = float(odds_value.replace("+", ""))
                    elif odds_value.startswith("-"):
                        odds_value = -float(odds_value.replace("-", ""))
                    else:
                        odds_value = float(odds_value)
                else:
                    odds_value = float(odds_value)

                new_bet = YetAIBet(
                    id=bet_id,
                    sport=bet_request.sport,
                    title=bet_request.game,
                    description=bet_request.reasoning,
                    bet_type=normalized_bet_type,
                    selection=bet_request.pick,
                    odds=odds_value,
                    confidence=float(bet_request.confidence),
                    tier_requirement=(
                        SubscriptionTier.PRO
                        if bet_request.is_premium
                        else SubscriptionTier.FREE
                    ),
                    status="pending",
                    created_at=datetime.utcnow(),
                    commence_time=game_commence_time,
                )

                db.add(new_bet)
                db.commit()
                db.refresh(new_bet)

                logger.info(f"Created YetAI Bet: {bet_id} by admin {admin_user_id}")

                return {
                    "success": True,
                    "bet_id": bet_id,
                    "message": "YetAI Bet created successfully",
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error creating YetAI Bet: {e}")
            return {"success": False, "error": "Failed to create bet"}

    async def create_parlay(
        self, parlay_request: CreateParlayBetRequest, admin_user_id: int
    ) -> Dict:
        """Create a new YetAI Parlay Bet with database persistence"""
        try:
            db = SessionLocal()
            try:
                parlay_id = str(uuid.uuid4())

                # Create main parlay entry with legs stored as JSON
                parlay_bet = YetAIBet(
                    id=parlay_id,
                    sport="Multi-Sport",
                    title=parlay_request.name,
                    description=parlay_request.reasoning,
                    bet_type="parlay",
                    selection=f"{len(parlay_request.legs)}-Team Parlay",
                    odds=float(
                        parlay_request.total_odds.replace("+", "").replace("-", "")
                        if isinstance(parlay_request.total_odds, str)
                        else parlay_request.total_odds
                    ),
                    confidence=float(parlay_request.confidence),
                    tier_requirement=(
                        SubscriptionTier.PRO
                        if parlay_request.is_premium
                        else SubscriptionTier.FREE
                    ),
                    status="pending",
                    created_at=datetime.utcnow(),
                    parlay_legs=[leg.dict() for leg in parlay_request.legs],
                )

                db.add(parlay_bet)
                db.commit()
                db.refresh(parlay_bet)

                logger.info(
                    f"Created YetAI Parlay: {parlay_id} with {len(parlay_request.legs)} legs by admin {admin_user_id}"
                )

                return {
                    "success": True,
                    "bet_id": parlay_id,
                    "message": "YetAI Parlay created successfully",
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error creating YetAI Parlay: {e}")
            return {"success": False, "error": "Failed to create parlay"}

    async def get_active_bets(self, user_tier: str = "free") -> List[Dict]:
        """Get active YetAI Bets based on user tier from database"""
        try:
            db = SessionLocal()
            try:
                query = db.query(YetAIBet).filter(YetAIBet.status == "pending")

                # For free users, only show non-premium bets
                if user_tier == "free":
                    query = query.filter(
                        YetAIBet.tier_requirement == SubscriptionTier.FREE
                    )

                # Sort by confidence (highest first)
                active_bets = query.order_by(desc(YetAIBet.confidence)).all()

                return [self._yetai_bet_to_dict(bet) for bet in active_bets]

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting active bets: {e}")
            return []

    async def get_all_bets(self, include_settled: bool = True) -> List[Dict]:
        """Get all YetAI Bets for admin view from database"""
        try:
            db = SessionLocal()
            try:
                query = db.query(YetAIBet)

                if not include_settled:
                    query = query.filter(YetAIBet.status == "pending")

                # Sort by created_at (newest first)
                all_bets = query.order_by(desc(YetAIBet.created_at)).all()

                return [self._yetai_bet_to_dict(bet) for bet in all_bets]

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting all bets: {e}")
            return []

    async def update_bet(
        self, bet_id: str, update_request: UpdateYetAIBetRequest, admin_user_id: int
    ) -> Dict:
        """Update a YetAI Bet (settle, update status, etc.) in database"""
        try:
            db = SessionLocal()
            try:
                bet = db.query(YetAIBet).filter(YetAIBet.id == bet_id).first()

                if not bet:
                    return {"success": False, "error": "Bet not found"}

                if update_request.status:
                    bet.status = update_request.status
                    if update_request.status in ["won", "lost", "pushed"]:
                        bet.settled_at = datetime.utcnow()

                if update_request.result:
                    bet.result = update_request.result

                db.commit()

                logger.info(f"Updated YetAI Bet: {bet_id} by admin {admin_user_id}")

                return {"success": True, "message": "Bet updated successfully"}

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error updating bet: {e}")
            return {"success": False, "error": "Failed to update bet"}

    async def delete_bet(self, bet_id: str, admin_user_id: int) -> Dict:
        """Delete a YetAI Bet from database and associated bet history"""
        try:
            db = SessionLocal()
            try:
                bet = db.query(YetAIBet).filter(YetAIBet.id == bet_id).first()

                if not bet:
                    return {"success": False, "error": "Bet not found"}

                # Also delete any associated bet history records
                from app.models.database_models import BetHistory

                history_deleted = (
                    db.query(BetHistory).filter(BetHistory.bet_id == bet_id).delete()
                )

                db.delete(bet)
                db.commit()

                logger.info(
                    f"Deleted YetAI Bet: {bet_id} (and {history_deleted} history records) by admin {admin_user_id}"
                )

                return {
                    "success": True,
                    "message": "Bet deleted successfully",
                    "history_records_deleted": history_deleted,
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error deleting bet: {e}")
            return {"success": False, "error": "Failed to delete bet"}

    async def get_performance_stats(self) -> Dict:
        """Calculate performance statistics for YetAI Bets from database"""
        try:
            db = SessionLocal()
            try:
                all_bets = db.query(YetAIBet).all()

                if not all_bets:
                    return {"total_bets": 0, "win_rate": 0, "pending_bets": 0}

                settled_bets = [
                    bet for bet in all_bets if bet.status in ["won", "lost"]
                ]
                won_bets = [bet for bet in settled_bets if bet.status == "won"]
                pending_bets = [bet for bet in all_bets if bet.status == "pending"]

                win_rate = (
                    (len(won_bets) / len(settled_bets) * 100) if settled_bets else 0
                )

                return {
                    "total_bets": len(all_bets),
                    "settled_bets": len(settled_bets),
                    "won_bets": len(won_bets),
                    "pending_bets": len(pending_bets),
                    "win_rate": round(win_rate, 1),
                }

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error calculating performance stats: {e}")
            return {"total_bets": 0, "win_rate": 0, "pending_bets": 0}

    def _yetai_bet_to_dict(self, bet: YetAIBet) -> Dict:
        """Convert YetAIBet model to dictionary"""
        # Format game time as MM/DD/YYYY @H:MMPM EST
        game_time_formatted = "TBD"
        if bet.commence_time:
            try:
                formatted_date = bet.commence_time.strftime("%m/%d/%Y")
                formatted_time = bet.commence_time.strftime("%I:%M %p EDT")
                game_time_formatted = f"{formatted_date} @{formatted_time}"
                logger.debug(
                    f"Formatted game time: {game_time_formatted} from {bet.commence_time}"
                )
            except Exception as e:
                logger.warning(f"Error formatting game time {bet.commence_time}: {e}")
                game_time_formatted = bet.commence_time.isoformat()

        # Clean up pick display by removing redundant bet type prefix
        clean_pick = bet.selection
        if bet.bet_type.lower() == "spread" and clean_pick.startswith("Spread "):
            clean_pick = clean_pick[7:]  # Remove "Spread " prefix
        elif bet.bet_type.lower() == "moneyline" and clean_pick.startswith(
            "Moneyline "
        ):
            clean_pick = clean_pick[10:]  # Remove "Moneyline " prefix
        elif bet.bet_type.lower() == "total" and clean_pick.startswith("Total "):
            clean_pick = clean_pick[6:]  # Remove "Total " prefix

        bet_dict = {
            "id": bet.id,
            "sport": bet.sport,
            "game": bet.title,
            "bet_type": bet.bet_type,
            "pick": clean_pick,
            "odds": f"+{int(bet.odds)}" if bet.odds > 0 else str(int(bet.odds)),
            "confidence": int(bet.confidence),
            "reasoning": bet.description,
            "is_premium": bet.tier_requirement != SubscriptionTier.FREE,
            "game_time": game_time_formatted,
            "bet_category": (
                "parlay"
                if hasattr(bet, "parlay_legs") and bet.parlay_legs
                else "straight"
            ),
            "status": bet.status,
            "created_at": bet.created_at.isoformat() if bet.created_at else None,
            "settled_at": bet.settled_at.isoformat() if bet.settled_at else None,
            "created_by_admin": 1,  # Default admin user
            "result": bet.result,
        }

        # Include parlay legs if they exist
        if bet.parlay_legs:
            bet_dict["parlay_legs"] = bet.parlay_legs

        return bet_dict

    def _create_sample_bets_if_needed(self):
        """Create some sample YetAI Bets for demonstration if none exist"""
        try:
            db = SessionLocal()
            try:
                # Check if any bets already exist
                existing_bets = db.query(YetAIBet).first()
                if existing_bets:
                    return  # Already have bets, don't create samples

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
                        "is_premium": False,
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
                        "is_premium": True,
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
                        "is_premium": True,
                    },
                    {
                        "sport": "NHL",
                        "game": "Rangers vs Bruins",
                        "bet_type": "Spread",
                        "pick": "Rangers +1.5",
                        "odds": "-180",
                        "confidence": 84,
                        "reasoning": "Rangers excellent in back-to-back games. Bruins on 4-game road trip, fatigue factor. Shesterkin expected to start.",
                        "game_time": "7:00 PM EST",
                        "is_premium": True,
                    },
                ]

                for bet_data in sample_bets:
                    bet_id = str(uuid.uuid4())

                    bet = YetAIBet(
                        id=bet_id,
                        sport=bet_data["sport"],
                        title=bet_data["game"],
                        description=bet_data["reasoning"],
                        bet_type=bet_data["bet_type"].lower(),
                        selection=bet_data["pick"],
                        odds=float(
                            bet_data["odds"].replace("-", "")
                            if bet_data["odds"].startswith("-")
                            else bet_data["odds"]
                        ),
                        confidence=float(bet_data["confidence"]),
                        tier_requirement=(
                            SubscriptionTier.PRO
                            if bet_data["is_premium"]
                            else SubscriptionTier.FREE
                        ),
                        status="pending",
                        created_at=datetime.utcnow(),
                    )

                    db.add(bet)

                db.commit()
                logger.info("Sample YetAI Bets created successfully in database")

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error creating sample bets: {e}")

    def _evaluate_yetai_bet_outcome(
        self, bet: YetAIBet, home_score: int, away_score: int
    ) -> tuple[str, str]:
        """
        Evaluate YetAI bet outcome based on bet type and scores
        Returns: (status, result_description)
        """
        bet_type = bet.bet_type
        selection = bet.selection.lower()

        try:
            if bet_type == BetType.MONEYLINE:
                # Check if selection is home or away team
                if home_score == away_score:
                    return "pushed", "Game tied - bet pushed"

                # Check which team won
                home_won = home_score > away_score
                if bet.home_team.lower() in selection:
                    if home_won:
                        return (
                            "won",
                            f"Won: {bet.home_team} won ({home_score}-{away_score})",
                        )
                    else:
                        return (
                            "lost",
                            f"Lost: {bet.home_team} lost ({home_score}-{away_score})",
                        )
                elif bet.away_team.lower() in selection:
                    if not home_won:
                        return (
                            "won",
                            f"Won: {bet.away_team} won ({away_score}-{home_score})",
                        )
                    else:
                        return (
                            "lost",
                            f"Lost: {bet.away_team} lost ({away_score}-{home_score})",
                        )

            elif bet_type == BetType.SPREAD:
                # Parse spread from selection (e.g., "Team Name -7.5" or "Team Name +3.5")
                import re

                spread_match = re.search(r"([+-]?\d+\.?\d*)", selection)
                if not spread_match:
                    return "pending_manual_review", "Could not parse spread value"

                spread = float(spread_match.group(1))

                # Determine which team and apply spread
                if bet.home_team.lower() in selection:
                    adjusted_home = home_score + spread
                    if adjusted_home > away_score:
                        return (
                            "won",
                            f"Won: {bet.home_team} {spread:+.1f} covered ({adjusted_home:.1f} vs {away_score})",
                        )
                    elif adjusted_home == away_score:
                        return "pushed", f"Push: {bet.home_team} {spread:+.1f} tied"
                    else:
                        return (
                            "lost",
                            f"Lost: {bet.home_team} {spread:+.1f} didn't cover ({adjusted_home:.1f} vs {away_score})",
                        )
                elif bet.away_team.lower() in selection:
                    adjusted_away = away_score + spread
                    if adjusted_away > home_score:
                        return (
                            "won",
                            f"Won: {bet.away_team} {spread:+.1f} covered ({adjusted_away:.1f} vs {home_score})",
                        )
                    elif adjusted_away == home_score:
                        return "pushed", f"Push: {bet.away_team} {spread:+.1f} tied"
                    else:
                        return (
                            "lost",
                            f"Lost: {bet.away_team} {spread:+.1f} didn't cover ({adjusted_away:.1f} vs {home_score})",
                        )

            elif bet_type == BetType.TOTAL:
                # Parse total from selection (e.g., "Over 220.5" or "Under 45.5")
                import re

                total_match = re.search(r"(\d+\.?\d*)", selection)
                if not total_match:
                    return "pending_manual_review", "Could not parse total value"

                line = float(total_match.group(1))
                total_score = home_score + away_score
                is_over = "over" in selection

                if total_score == line:
                    return "pushed", f"Push: Total exactly {line}"
                elif (is_over and total_score > line) or (
                    not is_over and total_score < line
                ):
                    direction = "Over" if is_over else "Under"
                    return "won", f"Won: {direction} {line} (total: {total_score})"
                else:
                    direction = "Over" if is_over else "Under"
                    return "lost", f"Lost: {direction} {line} (total: {total_score})"

            elif bet_type == BetType.PARLAY:
                # Parlay evaluation is complex - would need to check all legs
                return (
                    "pending_manual_review",
                    "Parlay evaluation requires manual review",
                )

            else:
                return "pending_manual_review", f"Unknown bet type: {bet_type}"

        except Exception as e:
            logger.error(f"Error evaluating YetAI bet {bet.id[:8]}: {e}")
            return "pending_manual_review", f"Evaluation error: {str(e)}"

    async def verify_pending_yetai_bets(self) -> Dict:
        """
        Verify all pending YetAI bets and settle completed games
        Similar to unified bet verification but for yetai_bets table
        """
        from app.services.optimized_odds_api_service import (
            get_optimized_odds_api_service,
        )
        from app.core.config import settings

        logger.info("🎯 Starting YetAI bets verification...")
        db = SessionLocal()

        try:
            # Get all pending YetAI bets
            pending_bets = db.query(YetAIBet).filter(YetAIBet.status == "pending").all()

            logger.info(f"Found {len(pending_bets)} pending YetAI bets to verify")

            if not pending_bets:
                return {"success": True, "verified": 0, "settled": 0}

            # Group bets by sport for efficient API calls
            bets_by_sport = {}
            for bet in pending_bets:
                sport = bet.sport.lower() if bet.sport else "unknown"
                if sport not in bets_by_sport:
                    bets_by_sport[sport] = []
                bets_by_sport[sport].append(bet)

            total_settled = 0
            odds_service = get_optimized_odds_api_service(settings.ODDS_API_KEY)

            for sport, sport_bets in bets_by_sport.items():
                if sport == "unknown":
                    continue

                try:
                    # Normalize sport name for API
                    sport_mapping = {
                        "mlb": "baseball_mlb",
                        "nfl": "americanfootball_nfl",
                        "nba": "basketball_nba",
                        "nhl": "icehockey_nhl",
                        "ncaa football": "americanfootball_ncaaf",
                    }
                    normalized_sport = sport_mapping.get(sport.lower(), sport.lower())

                    logger.info(
                        f"Verifying {len(sport_bets)} {sport.upper()} YetAI bets..."
                    )

                    # Get completed games for this sport
                    completed_games = await odds_service.get_scores_optimized(
                        normalized_sport, include_completed=True
                    )

                    logger.info(
                        f"Retrieved {len(completed_games)} game results for {sport}"
                    )

                    # Verify each bet
                    for bet in sport_bets:
                        # Find the game in completed games
                        game_found = False
                        for game in completed_games:
                            if not game.get("completed"):
                                continue

                            # Match by team names in game title
                            if bet.home_team in game.get(
                                "home_team", ""
                            ) and bet.away_team in game.get("away_team", ""):
                                game_found = True

                                # Get scores from the game
                                home_score = game.get("scores", [{}])[0].get("score", 0)
                                away_score = (
                                    game.get("scores", [{}])[1].get("score", 0)
                                    if len(game.get("scores", [])) > 1
                                    else 0
                                )

                                # Evaluate bet outcome
                                result_status, result_description = (
                                    self._evaluate_yetai_bet_outcome(
                                        bet, home_score, away_score
                                    )
                                )

                                # Update bet with results
                                # Status should be the actual outcome (won/lost/pushed) for frontend display
                                bet.status = result_status
                                bet.settled_at = datetime.utcnow()
                                bet.result = result_description
                                total_settled += 1

                                logger.info(
                                    f"Settled YetAI bet {bet.id[:8]}: {bet.title} - {result_status}"
                                )
                                break

                        if not game_found:
                            logger.debug(f"Game not yet completed for bet {bet.id[:8]}")

                except Exception as e:
                    logger.error(f"Error verifying {sport} YetAI bets: {e}")
                    continue

            db.commit()
            logger.info(f"✅ YetAI verification complete: {total_settled} bets settled")

            return {
                "success": True,
                "verified": len(pending_bets),
                "settled": total_settled,
            }

        except Exception as e:
            logger.error(f"Error in YetAI bet verification: {e}")
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()


# Service instance
yetai_bets_service_db = YetAIBetsServiceDB()
