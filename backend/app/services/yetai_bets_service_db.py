"""
Database-powered service for managing admin-created YetAI Bets
"""

import re
import uuid
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple
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


def coerce_subscription_tier(user_tier: object) -> str:
    """Normalize JWT/ORM tier values to lowercase tier slug (free/pro/elite)."""
    if isinstance(user_tier, SubscriptionTier):
        return user_tier.value
    if user_tier is None:
        return "free"
    text = str(user_tier).strip()
    if not text:
        return "free"
    if text.startswith("SubscriptionTier."):
        return text.rsplit(".", 1)[-1].lower()
    return text.lower()


def _utc_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize naive UTC datetimes with Z so browsers parse correctly."""
    if dt is None:
        return None
    iso = dt.isoformat()
    if iso.endswith("Z") or "+" in iso[-6:]:
        return iso
    return f"{iso}Z"


# Admin UI sport label → (Odds API sport_key, games.sport_title)
_ADMIN_SPORT_TO_GAME_META: dict[str, tuple[str, str]] = {
    "NFL": ("americanfootball_nfl", "NFL"),
    "NBA": ("basketball_nba", "NBA"),
    "WNBA": ("basketball_wnba", "WNBA"),
    "MLB": ("baseball_mlb", "MLB"),
    "NHL": ("icehockey_nhl", "NHL"),
    "NCAA Football": ("americanfootball_ncaaf", "NCAA Football"),
    "NCAA Basketball": ("basketball_ncaab", "NCAA Basketball"),
    "Soccer": ("soccer_epl", "Soccer"),
    "Tennis": ("tennis_atp", "Tennis"),
}

# Bets the scheduler should try to settle (subscriber-facing unsettled rows).
YETAI_UNSETTLED_STATUSES = ("pending", "active")
PROP_EVENT_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _ensure_game_row_for_yetai_bet(
    db: Session,
    *,
    game_id: Optional[str],
    sport: str,
    home_team: str,
    away_team: str,
    commence_time: Optional[datetime],
) -> Optional[str]:
    """Insert a games row when admin picks use Odds API ids not yet synced."""
    if not game_id:
        return None

    from app.models.database_models import Game, GameStatus

    if db.query(Game).filter(Game.id == game_id).first():
        return game_id

    sport_key, sport_title = _ADMIN_SPORT_TO_GAME_META.get(
        sport, (sport.lower().replace(" ", "_"), sport)
    )
    commence = commence_time or datetime.utcnow()
    db.add(
        Game(
            id=game_id,
            sport_key=sport_key,
            sport_title=sport_title,
            home_team=home_team,
            away_team=away_team,
            commence_time=commence,
            status=GameStatus.SCHEDULED,
            last_update=datetime.utcnow(),
        )
    )
    db.flush()
    logger.info(
        "Created games row for admin YetAI bet %s (%s @ %s)",
        game_id,
        away_team,
        home_team,
    )
    return game_id


# Backwards-compatible alias
MLB_PROP_EVENT_DATE_RE = PROP_EVENT_DATE_RE

# How long after inferred game day a pick stays on the live board without commence_time.
YETAI_LIVE_POST_GAME_BUFFER = timedelta(hours=8)


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _yetai_anchor_game_day(bet: YetAIBet) -> date:
    """Best-effort calendar day for slate vs tipoff (projection date can trail game day)."""
    game_day = game_date_for_yetai_bet(bet)
    created_day = bet.created_at.date() if bet.created_at else game_day
    return max(game_day, created_day)


def game_date_for_yetai_bet(bet: YetAIBet) -> date:
    """Best-effort game date for prop/stat lookups."""
    if bet.commence_time:
        return _naive_utc(bet.commence_time).date()
    factors = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    event_id = str(factors.get("event_id") or "")
    match = PROP_EVENT_DATE_RE.search(event_id)
    if match:
        return date.fromisoformat(match.group(1))
    if bet.created_at:
        return bet.created_at.date()
    return datetime.utcnow().date()


AUTO_GRADE_HOLD_KEY = "auto_grade_hold"


def yetai_auto_grade_held(bet: YetAIBet) -> bool:
    """True when auto-settlement must stay off (e.g. after admin reopen)."""
    factors = getattr(bet, "prediction_factors", None)
    if not isinstance(factors, dict):
        return False
    return bool(factors.get(AUTO_GRADE_HOLD_KEY))


def set_yetai_auto_grade_hold(bet: YetAIBet, *, held: bool = True) -> None:
    factors = (
        dict(bet.prediction_factors) if isinstance(bet.prediction_factors, dict) else {}
    )
    if held:
        factors[AUTO_GRADE_HOLD_KEY] = True
    else:
        factors.pop(AUTO_GRADE_HOLD_KEY, None)
    bet.prediction_factors = factors


def _prop_without_tipoff(bet: YetAIBet) -> bool:
    if bet.commence_time is not None:
        return False
    bt = bet.bet_type
    if isinstance(bt, BetType):
        return bt == BetType.PROP
    return str(bt or "").lower() == "prop"


def yetai_bet_is_stale(bet: YetAIBet, cutoff: datetime) -> bool:
    """True when a pick should leave the live board and be expired if still unsettled."""
    now = datetime.utcnow()
    tipoff = _naive_utc(bet.commence_time)
    if tipoff is not None:
        return tipoff + timedelta(hours=8) < now

    anchor = _yetai_anchor_game_day(bet)
    game_deadline = datetime.combine(anchor, time.max) + timedelta(hours=36)
    if now > game_deadline:
        return True

    if bet.created_at is not None:
        return bet.created_at < cutoff
    return False


def yetai_bet_subscriber_live_visible(
    bet: YetAIBet, *, now: Optional[datetime] = None
) -> bool:
    """Whether an active/pending pick belongs on the subscriber live board."""
    now = now or datetime.utcnow()
    status = (bet.status or "").lower()
    if status not in ("active", "pending"):
        return False
    if is_demo_yetai_bet(bet):
        return False

    tipoff = _naive_utc(bet.commence_time)
    if tipoff is not None:
        return tipoff - timedelta(hours=12) <= now <= tipoff + timedelta(hours=8)

    anchor = _yetai_anchor_game_day(bet)
    visibility_end = datetime.combine(anchor, time.max) + timedelta(hours=36)
    return now <= visibility_end


def yetai_pick_gradeable(bet: YetAIBet, *, now: Optional[datetime] = None) -> bool:
    """True when the game window has likely finished and auto-grading is safe."""
    if yetai_auto_grade_held(bet):
        return False

    now = now or datetime.utcnow()
    tipoff = _naive_utc(bet.commence_time)
    if tipoff is not None:
        return now >= tipoff + timedelta(hours=3)

    anchor = _yetai_anchor_game_day(bet)
    # Auto-pick props without tipoff often use projection slate date; game is next day.
    if _prop_without_tipoff(bet):
        anchor = anchor + timedelta(days=1)
    return now >= datetime.combine(anchor, time.max) + timedelta(hours=6)


def yetai_bet_visible_as_live(bet: YetAIBet, *, now: Optional[datetime] = None) -> bool:
    """Subscriber live list: hide picks after game window without waiting for settlement."""
    now = now or datetime.utcnow()
    in_progress_window = timedelta(hours=4)

    if bet.commence_time is not None:
        return bet.commence_time >= now - in_progress_window

    game_day = game_date_for_yetai_bet(bet)
    visibility_deadline = (
        datetime.combine(game_day, time.max) + YETAI_LIVE_POST_GAME_BUFFER
    )
    return now <= visibility_deadline


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

    @staticmethod
    def _is_prop_bet(bet: YetAIBet) -> bool:
        value = getattr(bet, "bet_type", None)
        if value == BetType.PROP:
            return True
        return str(value).lower() == "prop"

    @staticmethod
    def _is_mlb_sport(value: Optional[str]) -> bool:
        blob = (value or "").strip().lower()
        return "mlb" in blob or "baseball" in blob

    @staticmethod
    def _is_nba_sport(value: Optional[str]) -> bool:
        blob = (value or "").strip().lower()
        return "nba" in blob and "wnba" not in blob

    @staticmethod
    def _is_nhl_sport(value: Optional[str]) -> bool:
        blob = (value or "").strip().lower()
        return "nhl" in blob or "hockey" in blob or "icehockey" in blob

    @staticmethod
    def _is_parlay_bet(bet: YetAIBet) -> bool:
        if getattr(bet, "bet_type", None) == BetType.PARLAY:
            return True
        legs = getattr(bet, "parlay_legs", None)
        return isinstance(legs, list) and len(legs) >= 2

    @staticmethod
    def _is_spread_bet(bet: YetAIBet) -> bool:
        value = getattr(bet, "bet_type", None)
        if value == BetType.SPREAD:
            return True
        return str(value).lower() == "spread"

    def _is_retryable_error_loss(self, bet: YetAIBet) -> bool:
        """Permit regrading for legacy rows marked lost due to evaluation errors."""
        if (bet.status or "").lower() != "lost":
            return False
        if not self._is_prop_bet(bet):
            return False
        if not (self._is_mlb_sport(bet.sport) or self._is_nba_sport(bet.sport)):
            return False
        reason = (bet.result or "").strip().lower()
        return reason.startswith("evaluation")

    def _is_retryable_nba_prop_regrade(self, bet: YetAIBet) -> bool:
        """Re-run NBA prop grading after box-score parser fixes (recent settlements)."""
        if not self._is_prop_bet(bet) or not self._is_nba_sport(bet.sport):
            return False
        if (bet.status or "").lower() not in ("won", "lost"):
            return False
        if not bet.settled_at:
            return False
        return bet.settled_at >= datetime.utcnow() - timedelta(days=7)

    def _retry_historical_error_losses(self, db: Session, *, limit: int = 50) -> int:
        """
        Best-effort self-healing for legacy props marked lost due to evaluation errors.
        Runs during read paths so stale rows can correct even if scheduler misses them.
        """
        from app.services.player_prop_verification_service import (
            PlayerPropVerificationService,
        )

        rows = (
            db.query(YetAIBet)
            .filter(YetAIBet.status == "lost")
            .filter(YetAIBet.result.ilike("Evaluation%"))
            .order_by(desc(YetAIBet.settled_at), desc(YetAIBet.created_at))
            .limit(max(1, limit))
            .all()
        )
        if not rows:
            return 0

        prop_service = PlayerPropVerificationService(db)
        updated = 0
        for bet in rows:
            if not self._is_retryable_error_loss(bet):
                continue

            game_day = game_date_for_yetai_bet(bet)
            outcome = prop_service.verify_yetai_mlb_prop(bet, game_day)
            if not outcome:
                continue

            result_status, result_description = outcome
            if result_status not in {"won", "lost", "pushed"}:
                continue

            if (
                bet.status == result_status
                and (bet.result or "").strip() == (result_description or "").strip()
            ):
                continue

            bet.status = result_status
            bet.settled_at = datetime.utcnow()
            bet.result = clamp_yetai_result(result_description)
            updated += 1

        if updated:
            db.commit()
            logger.info("Regraded %s historical YetAI error-loss picks", updated)

        return updated

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
                    "puck line": "spread",
                }

                # Normalize bet type to enum value
                normalized_bet_type = bet_type_mapping.get(
                    bet_request.bet_type.lower(), bet_request.bet_type.lower()
                )
                valid_bet_types = {member.value for member in BetType}
                if normalized_bet_type not in valid_bet_types:
                    return {
                        "success": False,
                        "error": (
                            f"Unsupported bet type '{bet_request.bet_type}'. "
                            f"Use one of: spread, moneyline, total, prop."
                        ),
                    }
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

                game_id = _ensure_game_row_for_yetai_bet(
                    db,
                    game_id=game_id,
                    sport=bet_request.sport,
                    home_team=home_team,
                    away_team=away_team,
                    commence_time=game_commence_time,
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
            logger.error(f"Error creating YetAI Bet: {e}", exc_info=True)
            detail = str(e).strip() or type(e).__name__
            if "foreign key" in detail.lower():
                detail = (
                    f"{detail} (game_id must exist in games table; "
                    "sync was attempted automatically)"
                )
            return {"success": False, "error": f"Failed to create bet: {detail}"}

    async def create_parlay(
        self, parlay_request: CreateParlayBetRequest, admin_user_id: int
    ) -> Dict:
        """Create a new YetAI Parlay Bet with database persistence"""
        try:
            db = SessionLocal()
            try:
                parlay_id = str(uuid.uuid4())

                earliest_commence_time = None
                for leg in parlay_request.legs:
                    if leg.commence_time:
                        try:
                            from dateutil import parser

                            leg_commence = parser.isoparse(leg.commence_time)
                            if (
                                earliest_commence_time is None
                                or leg_commence < earliest_commence_time
                            ):
                                earliest_commence_time = leg_commence
                        except Exception as e:
                            logger.warning(f"Could not parse leg commence_time: {e}")

                odds_value = parlay_request.total_odds
                if isinstance(odds_value, str):
                    if odds_value.startswith("+"):
                        odds_value = float(odds_value.replace("+", ""))
                    elif odds_value.startswith("-"):
                        odds_value = -float(odds_value.replace("-", ""))
                    else:
                        odds_value = float(odds_value)
                else:
                    odds_value = float(odds_value)

                parlay_bet = YetAIBet(
                    id=parlay_id,
                    sport="Multi-Sport",
                    title=parlay_request.name,
                    description=parlay_request.reasoning,
                    bet_type=BetType.PARLAY,
                    selection=f"{len(parlay_request.legs)}-Team Parlay",
                    odds=odds_value,
                    confidence=float(parlay_request.confidence),
                    tier_requirement=(
                        SubscriptionTier.PRO
                        if parlay_request.is_premium
                        else SubscriptionTier.FREE
                    ),
                    status="pending",
                    created_at=datetime.utcnow(),
                    parlay_legs=[
                        leg.model_dump(mode="json") for leg in parlay_request.legs
                    ],
                    commence_time=earliest_commence_time,
                    reasoning=parlay_request.reasoning,
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
            logger.error(f"Error creating YetAI Parlay: {e}", exc_info=True)
            detail = str(e).strip() or type(e).__name__
            return {"success": False, "error": f"Failed to create parlay: {detail}"}

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

    def _allowed_tiers_for_user(self, user_tier: object) -> List[SubscriptionTier]:
        tier_slug = coerce_subscription_tier(user_tier)
        try:
            tier_enum = SubscriptionTier(tier_slug)
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
        order_by: str = "settled",
    ) -> List[YetAIBet]:
        allowed_tiers = self._allowed_tiers_for_user(user_tier)
        query = (
            db.query(YetAIBet)
            .filter(YetAIBet.status.in_(statuses))
            .filter(YetAIBet.tier_requirement.in_(allowed_tiers))
        )
        if since is not None:
            query = query.filter(YetAIBet.created_at >= since)
        if order_by == "created":
            query = query.order_by(desc(YetAIBet.created_at))
        else:
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

    def _linked_unified_bets_for_yetai_pick(self, db: Session, yetai: YetAIBet) -> List:
        """Find placed-bet rows tied to a YetAI pick (yetai_bet_id or legacy UUID ids)."""
        from app.models.simple_unified_bet_model import SimpleUnifiedBet

        return (
            db.query(SimpleUnifiedBet)
            .filter(
                or_(
                    SimpleUnifiedBet.yetai_bet_id == yetai.id,
                    SimpleUnifiedBet.game_id == yetai.id,
                    SimpleUnifiedBet.odds_api_event_id == yetai.id,
                    SimpleUnifiedBet.odds_api_event_id == f"yetai-pick-{yetai.id}",
                )
            )
            .all()
        )

    def _repair_unified_for_evaluation_yetai_picks(self, db: Session) -> int:
        """Regrade linked placed bets for YetAI picks stuck on evaluation errors."""
        import asyncio

        from app.models.simple_unified_bet_model import BetStatus as UnifiedBetStatus
        from app.services.player_prop_verification_service import (
            PlayerPropVerificationService,
        )

        rows = (
            db.query(YetAIBet)
            .filter(YetAIBet.status == "lost")
            .filter(YetAIBet.result.ilike("Evaluation%"))
            .limit(50)
            .all()
        )
        if not rows:
            return 0

        prop_service = PlayerPropVerificationService(db)
        updated = 0

        for yetai in rows:
            if not self._is_retryable_error_loss(yetai):
                continue

            for unified in self._linked_unified_bets_for_yetai_pick(db, yetai):
                if unified.status != UnifiedBetStatus.LOST:
                    continue
                if not self._is_prop_bet(yetai):
                    continue

                prop_result = asyncio.run(prop_service.verify_single_prop(unified))
                if not prop_result or prop_result.get("status") != UnifiedBetStatus.WON:
                    continue

                unified.status = UnifiedBetStatus.WON
                unified.result_amount = prop_result.get("result_amount", 0.0)
                unified.reasoning = prop_result.get("reasoning")
                unified.settled_at = datetime.utcnow()
                if not unified.yetai_bet_id:
                    unified.yetai_bet_id = yetai.id
                updated += 1

            game_day = game_date_for_yetai_bet(yetai)
            outcome = prop_service.verify_yetai_mlb_prop(yetai, game_day)
            if outcome:
                result_status, result_description = outcome
                if result_status in {"won", "lost", "pushed"}:
                    yetai.status = result_status
                    yetai.settled_at = datetime.utcnow()
                    yetai.result = clamp_yetai_result(result_description)
                    updated += 1

        if updated:
            db.commit()
            logger.info(
                "Regraded %s linked unified/YetAI rows after evaluation errors", updated
            )

        return updated

    def sync_unified_from_yetai_pick(
        self, db: Session, yetai: YetAIBet, unified_bet
    ) -> bool:
        """Mirror a graded YetAI pick onto the user's linked placed bet row."""
        from app.models.simple_unified_bet_model import BetStatus as UnifiedBetStatus

        yetai_status = (yetai.status or "").lower()
        if yetai_status not in {"won", "lost", "pushed"}:
            return False

        target = UnifiedBetStatus(yetai_status)
        if unified_bet.status == target:
            return False

        # Authoritative YetAI grading should not be overwritten by a winning placed row.
        if (
            unified_bet.status == UnifiedBetStatus.WON
            and target == UnifiedBetStatus.LOST
        ):
            return False

        unified_bet.status = target
        unified_bet.settled_at = yetai.settled_at or datetime.utcnow()
        note = (yetai.result or "").strip()
        unified_bet.reasoning = note or f"Graded from YetAI pick ({yetai_status})"

        if target == UnifiedBetStatus.WON:
            unified_bet.result_amount = unified_bet.amount + unified_bet.potential_win
        elif target == UnifiedBetStatus.PUSHED:
            unified_bet.result_amount = unified_bet.amount
        else:
            unified_bet.result_amount = 0.0

        if not unified_bet.yetai_bet_id:
            unified_bet.yetai_bet_id = yetai.id

        return True

    def sync_linked_unified_for_user(self, db: Session, user_id: int) -> int:
        """Align placed bets with their linked YetAI pick outcomes for one user."""
        from app.models.simple_unified_bet_model import SimpleUnifiedBet
        from app.services.player_prop_verification_service import (
            PlayerPropVerificationService,
        )

        rows = (
            db.query(SimpleUnifiedBet)
            .filter(SimpleUnifiedBet.user_id == user_id)
            .filter(SimpleUnifiedBet.parent_bet_id.is_(None))
            .order_by(desc(SimpleUnifiedBet.placed_at))
            .limit(200)
            .all()
        )
        if not rows:
            return 0

        prop_service = PlayerPropVerificationService(db)
        updated = 0
        for unified in rows:
            yetai = prop_service._resolve_yetai_pick(unified)
            if not yetai:
                continue
            if self.sync_unified_from_yetai_pick(db, yetai, unified):
                updated += 1

        if updated:
            db.commit()
            logger.info(
                "Synced %s placed bet(s) from YetAI picks for user %s", updated, user_id
            )

        return updated

    def sync_yetai_from_unified_bet(self, db: Session, unified_bet) -> bool:
        """Mirror graded placed-bet outcomes onto the linked YetAI pick row."""
        from app.models.simple_unified_bet_model import BetStatus as UnifiedBetStatus
        from app.services.player_prop_verification_service import (
            PlayerPropVerificationService,
        )

        if unified_bet.status not in (
            UnifiedBetStatus.WON,
            UnifiedBetStatus.LOST,
            UnifiedBetStatus.PUSHED,
        ):
            return False

        prop_service = PlayerPropVerificationService(db)
        yetai = None
        yetai_id = getattr(unified_bet, "yetai_bet_id", None)
        if yetai_id:
            yetai = db.query(YetAIBet).filter(YetAIBet.id == yetai_id).first()
        if not yetai:
            yetai = prop_service._resolve_yetai_pick(unified_bet)
        if not yetai:
            return False

        unified_reason = (getattr(unified_bet, "reasoning", None) or "").strip().lower()
        yetai_reason = (yetai.result or "").strip().lower()
        if yetai_reason.startswith("evaluation") or unified_reason.startswith(
            "evaluation"
        ):
            return False

        target = unified_bet.status.value
        if yetai.status == "won" and target == "lost":
            return False
        if yetai.status == target and yetai.settled_at is not None:
            return False
        if yetai_auto_grade_held(yetai):
            return False

        yetai.status = target
        yetai.settled_at = unified_bet.settled_at or datetime.utcnow()
        note = (getattr(unified_bet, "reasoning", None) or "").strip()
        yetai.result = clamp_yetai_result(note or f"Graded from placed bet ({target})")
        return True

    def sync_yetai_picks_from_linked_unified_bets(self, db: Session) -> int:
        """Backfill yetai_bets rows from settled simple_unified_bets with yetai_bet_id."""
        from app.models.simple_unified_bet_model import (
            SimpleUnifiedBet,
            BetStatus as UnifiedBetStatus,
        )

        linked = (
            db.query(SimpleUnifiedBet)
            .filter(SimpleUnifiedBet.yetai_bet_id.isnot(None))
            .filter(
                SimpleUnifiedBet.status.in_(
                    [
                        UnifiedBetStatus.WON,
                        UnifiedBetStatus.LOST,
                        UnifiedBetStatus.PUSHED,
                    ]
                )
            )
            .all()
        )
        updated = 0
        for unified in linked:
            if self.sync_yetai_from_unified_bet(db, unified):
                updated += 1
        if updated:
            db.commit()
            logger.info("Synced %s YetAI pick(s) from linked placed bets", updated)
        return updated

    def get_yetai_bets_for_user(self, user_tier: object, db: Session) -> List[Dict]:
        """Return open YetAI picks (active/pending) for the subscriber tier."""
        tier_slug = coerce_subscription_tier(user_tier)
        rows = self._query_yetai_bets_for_user(tier_slug, db, self.YETAI_LIVE_STATUSES)
        live_rows = [bet for bet in rows if yetai_bet_subscriber_live_visible(bet)]
        return [self._yetai_bet_to_dict(bet) for bet in live_rows]

    def get_yetai_bets_history_for_user(
        self,
        user_tier: str,
        db: Session,
        *,
        days: int = 90,
        limit: int = 100,
    ) -> tuple[List[Dict], Dict[str, float | int]]:
        """Promoted picks in the window (newest first), with stats for settled only."""
        self._repair_unified_for_evaluation_yetai_picks(db)
        self._retry_historical_error_losses(db)
        self.sync_yetai_picks_from_linked_unified_bets(db)
        since = datetime.utcnow() - timedelta(days=max(days, 1))
        rows = self._query_yetai_bets_for_user(
            user_tier,
            db,
            tuple(self.SUBSCRIBER_VISIBLE_STATUSES),
            since=since,
            limit=limit,
            order_by="created",
        )
        bets = [self._yetai_bet_to_dict(bet) for bet in rows]
        settled = [b for b in bets if b.get("status") in self.YETAI_HISTORY_STATUSES]
        stats = self.compute_history_stats(settled, period_days=days)
        stats["returned"] = len(bets)
        stats["settled"] = len(settled)
        return bets, stats

    async def get_active_bets(self, user_tier: object = "free") -> List[Dict]:
        """Get active YetAI Bets based on user tier from database

        Returns bets that are:
        - Status "pending" or "active" (not yet settled, not pending_approval/rejected/expired)
        - Tier-gated: FREE sees FREE only, PRO sees FREE+PRO, ELITE sees all

        Stale unsettled rows are removed by verify_pending_yetai_bets (status -> expired).
        """
        try:
            db = SessionLocal()
            try:
                tier_slug = coerce_subscription_tier(user_tier)
                try:
                    tier_enum = SubscriptionTier(tier_slug)
                except (ValueError, AttributeError):
                    tier_enum = SubscriptionTier.FREE

                user_rank = self.TIER_RANK[tier_enum]
                allowed_tiers = [t for t, r in self.TIER_RANK.items() if r <= user_rank]

                query = (
                    db.query(YetAIBet)
                    .filter(YetAIBet.status.in_({"active", "pending"}))
                    .filter(YetAIBet.tier_requirement.in_(allowed_tiers))
                )

                active_bets = query.order_by(desc(YetAIBet.confidence)).all()
                visible = [
                    bet
                    for bet in active_bets
                    if not is_demo_yetai_bet(bet)
                    and yetai_bet_subscriber_live_visible(bet)
                ]

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
            "commence_time": _utc_iso(bet.commence_time),
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
            "created_at": _utc_iso(bet.created_at),
            "settled_at": _utc_iso(bet.settled_at),
            "created_by_admin": 1,  # Default admin user
            "result": bet.result,
        }

        # Include parlay legs if they exist
        if bet.parlay_legs:
            bet_dict["parlay_legs"] = bet.parlay_legs

        return bet_dict

    def _verify_yetai_nba_spread_from_actuals(
        self, bet: YetAIBet, game_day: date, db: Session
    ) -> Optional[Tuple[str, str]]:
        """Settle NBA spread picks using pred_nba_spread_actuals when game_id is missing."""
        from app.models.predictions_models import NBASpreadActuals

        if not self._is_spread_bet(bet) or not self._is_nba_sport(bet.sport):
            return None
        home = (bet.home_team or "").strip()
        away = (bet.away_team or "").strip()
        if not home or not away:
            return None

        row = (
            db.query(NBASpreadActuals)
            .filter(
                NBASpreadActuals.game_date == game_day,
                NBASpreadActuals.home_team_name == home,
                NBASpreadActuals.away_team_name == away,
            )
            .first()
        )
        if not row:
            return None

        return self._evaluate_yetai_bet_outcome(bet, row.home_score, row.away_score)

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
        grace = timedelta(hours=4)
        for row in rows:
            if row.commence_time is not None:
                tipoff = row.commence_time
                if tipoff.tzinfo is not None:
                    tipoff = tipoff.replace(tzinfo=None)
                if tipoff + grace <= now:
                    expired.append(row)
            elif (
                row.commence_time is None
                and row.created_at
                and row.created_at <= stale_cutoff
            ):
                expired.append(row)
        for row in expired:
            row.status = "rejected"
            row.result = clamp_yetai_result("Auto-expired (unapproved)")
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

            from sqlalchemy import and_, or_

            candidates = (
                db.query(YetAIBet)
                .filter(
                    or_(
                        YetAIBet.status.in_(YETAI_UNSETTLED_STATUSES),
                        and_(
                            YetAIBet.status == "lost",
                            YetAIBet.result.ilike("Evaluation%"),
                        ),
                    )
                )
                .all()
            )
            unsettled = []
            for bet in candidates:
                if bet.status in YETAI_UNSETTLED_STATUSES:
                    unsettled.append(bet)
                    continue
                if self._is_retryable_error_loss(bet):
                    unsettled.append(bet)
                    logger.info(
                        "Retrying previously errored YetAI pick %s: %s",
                        bet.id[:8],
                        (bet.result or "")[:80],
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
                settled = False

                if self._is_retryable_error_loss(bet):
                    game_day = game_date_for_yetai_bet(bet)
                    outcome = None
                    if self._is_prop_bet(bet) and self._is_mlb_sport(bet.sport):
                        outcome = prop_service.verify_yetai_mlb_prop(bet, game_day)
                    elif self._is_prop_bet(bet) and self._is_nba_sport(bet.sport):
                        outcome = prop_service.verify_yetai_nba_prop(bet, game_day)
                    if outcome:
                        result_status, result_description = outcome
                        bet.status = result_status
                        bet.settled_at = datetime.utcnow()
                        bet.result = clamp_yetai_result(result_description)
                        total_settled += 1
                        settled = True
                        logger.info(
                            "Regraded YetAI prop %s: %s",
                            bet.id[:8],
                            result_status,
                        )
                    continue

                if bet.status not in YETAI_UNSETTLED_STATUSES:
                    continue

                if yetai_auto_grade_held(bet):
                    continue

                if not yetai_pick_gradeable(bet):
                    continue

                if self._is_parlay_bet(bet):
                    from app.services.yetai_parlay_verification import (
                        verify_yetai_parlay,
                    )

                    parlay_outcome = verify_yetai_parlay(bet, self, prop_service, db)
                    if parlay_outcome:
                        result_status, result_description, updated_legs = parlay_outcome
                        bet.parlay_legs = updated_legs
                        bet.status = result_status
                        bet.settled_at = datetime.utcnow()
                        bet.result = clamp_yetai_result(result_description)
                        total_settled += 1
                        settled = True
                        logger.info(
                            "Settled YetAI parlay %s: %s",
                            bet.id[:8],
                            result_status,
                        )
                    continue

                if self._is_prop_bet(bet) and self._is_mlb_sport(bet.sport):
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

                elif self._is_prop_bet(bet) and self._is_nba_sport(bet.sport):
                    game_day = game_date_for_yetai_bet(bet)
                    outcome = prop_service.verify_yetai_nba_prop(bet, game_day)
                    if outcome:
                        result_status, result_description = outcome
                        bet.status = result_status
                        bet.settled_at = datetime.utcnow()
                        bet.result = clamp_yetai_result(result_description)
                        total_settled += 1
                        settled = True
                        logger.info(
                            "Settled YetAI NBA prop %s: %s",
                            bet.id[:8],
                            result_status,
                        )

                elif self._is_spread_bet(bet) and self._is_nba_sport(bet.sport):
                    game_day = game_date_for_yetai_bet(bet)
                    outcome = self._verify_yetai_nba_spread_from_actuals(
                        bet, game_day, db
                    )
                    if outcome:
                        result_status, result_description = outcome
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
                                "Settled YetAI NBA spread %s: %s",
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
