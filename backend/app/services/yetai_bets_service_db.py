"""
Database-powered service for managing admin-created YetAI Bets
"""

import re
import uuid
from datetime import date, datetime, timedelta
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
from app.services.yetai_bets_demo import is_demo_yetai_bet
from app.services.yetai_bets_display import subscriber_game_label

logger = logging.getLogger(__name__)

# Bets the scheduler should try to settle (subscriber-facing unsettled rows).
YETAI_UNSETTLED_STATUSES = ("pending", "active")
MLB_PROP_EVENT_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def game_date_for_yetai_bet(bet: YetAIBet) -> date:
    """Best-effort game date for prop/stat lookups."""
    if bet.commence_time:
        return bet.commence_time.date()
    factors = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    event_id = str(factors.get("event_id") or "")
    match = MLB_PROP_EVENT_DATE_RE.search(event_id)
    if match:
        return date.fromisoformat(match.group(1))
    if bet.created_at:
        return bet.created_at.date()
    return datetime.utcnow().date()


def yetai_bet_is_stale(bet: YetAIBet, cutoff: datetime) -> bool:
    if bet.commence_time is not None:
        return bet.commence_time < cutoff
    if bet.created_at is not None:
        return bet.created_at < cutoff
    return False


YETAI_RESULT_MAX_LEN = 50  # legacy DB column until migration widens to Text


def clamp_yetai_result(text: str, max_len: int = YETAI_RESULT_MAX_LEN) -> str:
    """Fit settlement notes into yetai_bets.result (varchar(50) pre-migration)."""
    value = (text or "").strip()
    if len(value) <= max_len:
        return value
    return value[: max_len - 3] + "..."


class YetAIBetsServiceDB:
    """Database-powered admin-created best bets for the YetAI Bets page"""

    def __init__(self):
        pass

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

                # Parse commence_time (ISO format) to datetime
                game_commence_time = None
                if hasattr(bet_request, "commence_time") and bet_request.commence_time:
                    try:
                        from dateutil import parser

                        game_commence_time = parser.isoparse(bet_request.commence_time)
                        logger.info(f"Parsed commence_time: {game_commence_time}")
                    except Exception as e:
                        logger.error(f"Could not parse commence_time: {e}")
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
                    "player props": "prop",
                    "player prop": "prop",
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

                # Use provided game data directly (no parsing needed)
                game_id = bet_request.game_id
                home_team = bet_request.home_team
                away_team = bet_request.away_team

                logger.info(
                    f"Using provided game data: game_id={game_id}, {away_team} @ {home_team}"
                )

                new_bet = YetAIBet(
                    id=bet_id,
                    game_id=game_id,
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
                    home_team=home_team,
                    away_team=away_team,
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

                # Find the earliest game time from all legs for the parlay
                earliest_game_time = None
                earliest_commence_time = None
                for leg in parlay_request.legs:
                    if hasattr(leg, "commence_time") and leg.commence_time:
                        try:
                            from dateutil import parser

                            leg_commence = parser.isoparse(leg.commence_time)
                            if (
                                earliest_commence_time is None
                                or leg_commence < earliest_commence_time
                            ):
                                earliest_commence_time = leg_commence
                                earliest_game_time = (
                                    leg.game_time if hasattr(leg, "game_time") else None
                                )
                        except Exception as e:
                            logger.warning(f"Could not parse leg commence_time: {e}")
                            continue

                # Use the earliest time found, or default to "TBD"
                parlay_game_time = earliest_game_time if earliest_game_time else "TBD"

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
                    game_time=parlay_game_time,
                    commence_time=earliest_commence_time,
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

    # Tier rank: higher rank = higher access level
    TIER_RANK = {
        SubscriptionTier.FREE: 0,
        SubscriptionTier.PRO: 1,
        SubscriptionTier.ELITE: 2,
    }

    # Statuses that are safe to display to subscribers
    SUBSCRIBER_VISIBLE_STATUSES = {"active", "pending", "won", "lost", "pushed"}
    YETAI_LIVE_STATUSES = ("active", "pending")
    YETAI_HISTORY_STATUSES = ("won", "lost", "pushed")

    def _allowed_tiers_for_user(self, user_tier: str) -> List[SubscriptionTier]:
        try:
            tier_enum = SubscriptionTier(user_tier.lower())
        except (ValueError, AttributeError):
            tier_enum = SubscriptionTier.FREE
        user_rank = self.TIER_RANK[tier_enum]
        return [t for t, r in self.TIER_RANK.items() if r <= user_rank]

    def _query_yetai_bets_for_user(
        self,
        user_tier: str,
        db: Session,
        statuses: tuple[str, ...],
        *,
        since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[YetAIBet]:
        allowed_tiers = self._allowed_tiers_for_user(user_tier)
        query = (
            db.query(YetAIBet)
            .filter(YetAIBet.status.in_(statuses))
            .filter(YetAIBet.tier_requirement.in_(allowed_tiers))
        )
        if since is not None:
            query = query.filter(
                or_(
                    YetAIBet.settled_at >= since,
                    and_(YetAIBet.settled_at.is_(None), YetAIBet.created_at >= since),
                )
            )
        query = query.order_by(desc(YetAIBet.settled_at), desc(YetAIBet.created_at))
        if limit is not None:
            query = query.limit(limit)
        rows = query.all()
        return [bet for bet in rows if not is_demo_yetai_bet(bet)]

    @staticmethod
    def _american_odds_units_profit(odds: float) -> float:
        if odds > 0:
            return odds / 100.0
        if odds < 0:
            return 100.0 / abs(odds)
        return 0.0

    def compute_history_stats(
        self, bets: List[Dict], period_days: int
    ) -> Dict[str, float | int]:
        won = [b for b in bets if b.get("status") == "won"]
        lost = [b for b in bets if b.get("status") == "lost"]
        pushed = [b for b in bets if b.get("status") == "pushed"]
        graded = len(won) + len(lost)
        units = 0.0
        for bet in bets:
            status = bet.get("status")
            try:
                odds_val = float(bet.get("odds", 0))
            except (TypeError, ValueError):
                odds_val = 0.0
            if status == "won":
                units += self._american_odds_units_profit(odds_val)
            elif status == "lost":
                units -= 1.0
        win_rate = round((len(won) / graded) * 100, 1) if graded else 0.0
        return {
            "period_days": period_days,
            "total": len(bets),
            "won": len(won),
            "lost": len(lost),
            "pushed": len(pushed),
            "win_rate": win_rate,
            "units": round(units, 2),
        }

    def get_yetai_bets_for_user(self, user_tier: str, db: Session) -> List[Dict]:
        """Return open YetAI picks (active/pending) for the subscriber tier."""
        rows = self._query_yetai_bets_for_user(user_tier, db, self.YETAI_LIVE_STATUSES)
        return [self._yetai_bet_to_dict(bet) for bet in rows]

    def get_yetai_bets_history_for_user(
        self,
        user_tier: str,
        db: Session,
        *,
        days: int = 90,
        limit: int = 100,
    ) -> tuple[List[Dict], Dict[str, float | int]]:
        """Settled promoted picks (won/lost/pushed) with aggregate track record."""
        since = datetime.utcnow() - timedelta(days=max(days, 1))
        rows = self._query_yetai_bets_for_user(
            user_tier,
            db,
            self.YETAI_HISTORY_STATUSES,
            since=since,
            limit=limit,
        )
        bets = [self._yetai_bet_to_dict(bet) for bet in rows]
        stats = self.compute_history_stats(bets, period_days=days)
        return bets, stats

    async def get_active_bets(self, user_tier: str = "free") -> List[Dict]:
        """Get active YetAI Bets based on user tier from database

        Returns bets that are:
        - Status "pending" or "active" (not yet settled, not pending_approval/rejected/expired)
        - Have a commence_time in the future OR within last 4 hours (to show in-progress games)
        - Tier-gated: FREE sees FREE only, PRO sees FREE+PRO, ELITE sees all
        """
        try:
            db = SessionLocal()
            try:
                from datetime import datetime, timedelta

                # Show bets that are in an active subscriber-visible status and either:
                # 1. Game hasn't started yet, OR
                # 2. Game started within last 4 hours (still in progress)
                cutoff_time = datetime.utcnow() - timedelta(hours=4)

                # Normalise to enum; fall back to FREE for unknown values
                try:
                    tier_enum = SubscriptionTier(user_tier.lower())
                except (ValueError, AttributeError):
                    tier_enum = SubscriptionTier.FREE

                user_rank = self.TIER_RANK[tier_enum]
                allowed_tiers = [t for t, r in self.TIER_RANK.items() if r <= user_rank]

                query = (
                    db.query(YetAIBet)
                    .filter(YetAIBet.status.in_({"active", "pending"}))
                    .filter(
                        (YetAIBet.commence_time >= cutoff_time)
                        | (YetAIBet.commence_time == None)
                    )
                    .filter(YetAIBet.tier_requirement.in_(allowed_tiers))
                )

                # Sort by confidence (highest first)
                active_bets = query.order_by(desc(YetAIBet.confidence)).all()
                visible = [bet for bet in active_bets if not is_demo_yetai_bet(bet)]

                return [self._yetai_bet_to_dict(bet) for bet in visible]

            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error getting active bets: {e}")
            return []

    async def get_all_bets(
        self, include_settled: bool = True, include_stale_pending: bool = False
    ) -> List[Dict]:
        """Get all YetAI Bets for admin view from database.

        By default, pending bets whose game started more than 24 hours ago are
        hidden — they are considered stale and need verification/manual review.
        Set include_stale_pending=True for admin views that need everything.
        """
        try:
            db = SessionLocal()
            try:
                from datetime import datetime, timedelta

                query = db.query(YetAIBet)

                if not include_settled:
                    query = query.filter(YetAIBet.status == "pending")

                if not include_stale_pending:
                    stale_cutoff = datetime.utcnow() - timedelta(hours=24)
                    # Exclude pending bets where either:
                    #  - commence_time is set and >24h ago, OR
                    #  - commence_time is null and created_at is >24h ago
                    #    (covers legacy/seeded rows that never had a game time)
                    query = query.filter(
                        ~(
                            (YetAIBet.status == "pending")
                            & (
                                (
                                    (YetAIBet.commence_time != None)
                                    & (YetAIBet.commence_time < stale_cutoff)
                                )
                                | (
                                    (YetAIBet.commence_time == None)
                                    & (YetAIBet.created_at < stale_cutoff)
                                )
                            )
                        )
                    )

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
            "game": subscriber_game_label(bet),
            "game_id": bet.game_id,  # Odds API event ID for verification
            "home_team": bet.home_team,  # Required for bet placement
            "away_team": bet.away_team,  # Required for bet placement
            "commence_time": (
                bet.commence_time.isoformat() if bet.commence_time else None
            ),  # ISO format for API
            "bet_type": bet.bet_type,
            "pick": clean_pick,
            "odds": f"+{int(bet.odds)}" if bet.odds > 0 else str(int(bet.odds)),
            "confidence": int(bet.confidence),
            "reasoning": bet.reasoning or bet.description,
            "is_premium": bet.tier_requirement != SubscriptionTier.FREE,
            "game_time": game_time_formatted,  # Display format for UI
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

    def _expire_stale_pending_approval(self, db: Session) -> int:
        """Drop admin-queue picks that are past game day or >24h old without commence_time."""
        now = datetime.utcnow()
        stale_cutoff = now - timedelta(hours=24)
        rows = db.query(YetAIBet).filter(YetAIBet.status == "pending_approval").all()
        expired = []
        for row in rows:
            if row.commence_time is not None and row.commence_time <= now:
                expired.append(row)
            elif (
                row.commence_time is None
                and row.created_at
                and row.created_at <= stale_cutoff
            ):
                expired.append(row)
        for row in expired:
            row.status = "expired"
        return len(expired)

    async def verify_pending_yetai_bets(self) -> Dict:
        """
        Verify unsettled YetAI bets (pending + active) and settle when possible.

        - Game-linked bets: ``games`` row with FINAL status + score evaluation.
        - MLB props: MLB Stats API via PlayerPropVerificationService.
        - Stale rows (>24h, still unsettled): pending_manual_review (hidden from subscribers).
        """
        from app.models.database_models import Game, GameStatus
        from app.services.player_prop_verification_service import (
            PlayerPropVerificationService,
        )

        logger.info("🎯 Starting YetAI bets verification...")
        db = SessionLocal()
        prop_service = PlayerPropVerificationService(db)

        try:
            expired_approval = self._expire_stale_pending_approval(db)
            if expired_approval:
                logger.info(
                    "Expired %s stale pending_approval YetAI picks", expired_approval
                )

            unsettled = (
                db.query(YetAIBet)
                .filter(YetAIBet.status.in_(YETAI_UNSETTLED_STATUSES))
                .all()
            )
            logger.info(
                "Found %s unsettled YetAI bets (statuses %s)",
                len(unsettled),
                YETAI_UNSETTLED_STATUSES,
            )

            if not unsettled:
                if expired_approval:
                    db.commit()
                return {
                    "success": True,
                    "verified": 0,
                    "settled": 0,
                    "expired": 0,
                    "expired_pending_approval": expired_approval,
                }

            total_settled = 0
            total_expired = 0
            stale_cutoff = datetime.utcnow() - timedelta(hours=24)

            for bet in unsettled:
                if bet.status not in YETAI_UNSETTLED_STATUSES:
                    continue

                settled = False

                if bet.bet_type == BetType.PROP and (bet.sport or "").upper() == "MLB":
                    game_day = game_date_for_yetai_bet(bet)
                    outcome = prop_service.verify_yetai_mlb_prop(bet, game_day)
                    if outcome:
                        result_status, result_description = outcome
                        bet.status = result_status
                        bet.settled_at = datetime.utcnow()
                        bet.result = clamp_yetai_result(result_description)
                        total_settled += 1
                        settled = True
                        logger.info(
                            "Settled YetAI MLB prop %s via stats API: %s",
                            bet.id[:8],
                            result_status,
                        )

                elif bet.game_id:
                    game = db.query(Game).filter(Game.id == bet.game_id).first()
                    if game and game.status == GameStatus.FINAL:
                        result_status, result_description = (
                            self._evaluate_yetai_bet_outcome(
                                bet, game.home_score, game.away_score
                            )
                        )
                        if result_status in (
                            "won",
                            "lost",
                            "pushed",
                            "pending_manual_review",
                        ):
                            bet.status = result_status
                            bet.settled_at = datetime.utcnow()
                            bet.result = clamp_yetai_result(result_description)
                            if result_status != "pending_manual_review":
                                total_settled += 1
                            settled = True
                            logger.info(
                                "Settled YetAI bet %s via games DB: %s",
                                bet.id[:8],
                                result_status,
                            )

                if settled:
                    continue

                if yetai_bet_is_stale(bet, stale_cutoff):
                    bet.status = "expired"
                    bet.settled_at = datetime.utcnow()
                    if not bet.result:
                        bet.result = clamp_yetai_result("Unsettled >24h, no result")
                    total_expired += 1
                    logger.info(
                        "Auto-expired stale YetAI bet %s: %s",
                        bet.id[:8],
                        bet.title,
                    )

            db.commit()
            logger.info(
                "✅ YetAI verification complete: %s settled, %s expired/manual",
                total_settled,
                total_expired,
            )

            return {
                "success": True,
                "verified": len(unsettled),
                "settled": total_settled,
                "expired": total_expired,
                "expired_pending_approval": expired_approval,
            }

        except Exception as e:
            logger.error(f"Error in YetAI bet verification: {e}", exc_info=True)
            db.rollback()
            return {"success": False, "error": str(e)}
        finally:
            db.close()


# Service instance
yetai_bets_service_db = YetAIBetsServiceDB()
