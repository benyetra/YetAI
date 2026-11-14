"""
Database-powered service for managing admin-created YetAI Bets
"""

import os
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
import logging
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from app.core.database import SessionLocal
from app.models.database_models import (
    BetSource,
    User,
    YetAIBet,
    SubscriptionTier,
    BetType,
)
from app.models.bet_models import (
    CreateYetAIBetRequest,
    CreateParlayBetRequest,
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


_ET = ZoneInfo("America/New_York")


def format_game_time_et(commence_time: datetime) -> str:
    """Naive-UTC start -> "11/13/2026 @7:30 PM ET" (Eastern wall clock, DST aware)."""
    utc = (
        commence_time.replace(tzinfo=timezone.utc)
        if (commence_time.tzinfo is None)
        else commence_time
    )
    et = utc.astimezone(_ET)
    return f"{et:%m/%d/%Y} @{et:%I:%M %p}".replace("@0", "@") + " ET"


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
        ct = _naive_utc(bet.commence_time).replace(tzinfo=timezone.utc)
        return ct.astimezone(_ET).date()  # same ET day as yetai_grading.game_day_for
    factors = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    event_id = str(factors.get("event_id") or "")
    match = PROP_EVENT_DATE_RE.search(event_id)
    if match:
        return date.fromisoformat(match.group(1))
    if bet.created_at:
        return bet.created_at.date()
    return datetime.utcnow().date()


AUTO_GRADE_HOLD_KEY = "auto_grade_hold"


AUTO_GRADE_HOLD_AT_KEY = "auto_grade_hold_at"
AUTO_GRADE_HOLD_TTL = timedelta(hours=24)


def yetai_auto_grade_held(bet: YetAIBet, now: Optional[datetime] = None) -> bool:
    """True while the 24h hold set by admin reopen is running (no timestamp = elapsed)."""
    factors = getattr(bet, "prediction_factors", None)
    if not isinstance(factors, dict) or not factors.get(AUTO_GRADE_HOLD_KEY):
        return False
    try:
        held_at = datetime.fromisoformat(str(factors[AUTO_GRADE_HOLD_AT_KEY]))
    except (KeyError, TypeError, ValueError):
        return False
    held_at = _naive_utc(held_at)
    return (now or datetime.utcnow()) - held_at < AUTO_GRADE_HOLD_TTL


def set_yetai_auto_grade_hold(bet: YetAIBet, *, held: bool = True) -> None:
    factors = (
        dict(bet.prediction_factors) if isinstance(bet.prediction_factors, dict) else {}
    )
    if held:
        factors[AUTO_GRADE_HOLD_KEY] = True
        factors[AUTO_GRADE_HOLD_AT_KEY] = datetime.utcnow().isoformat()
    else:
        factors.pop(AUTO_GRADE_HOLD_KEY, None)
        factors.pop(AUTO_GRADE_HOLD_AT_KEY, None)
    bet.prediction_factors = factors


def _prop_without_tipoff(bet: YetAIBet) -> bool:
    if bet.commence_time is not None:
        return False
    bt = bet.bet_type
    if isinstance(bt, BetType):
        return bt == BetType.PROP
    return str(bt or "").lower() == "prop"


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


def publish_gates_enabled() -> bool:
    """Default on; YETAI_PUBLISH_GATES_ENABLED=false/0/no/off is the kill switch."""
    return os.getenv("YETAI_PUBLISH_GATES_ENABLED", "true").strip().lower() not in (
        "false",
        "0",
        "no",
        "off",
    )


def pick_started(commence_time: Optional[datetime], *, now: Optional[datetime] = None):
    """True when tipoff is within START_BUFFER (or past); no commence_time -> False."""
    from app.services.auto_pick.selector import START_BUFFER

    if commence_time is None:
        return False
    tipoff = _naive_utc(
        commence_time.astimezone(timezone.utc)
        if commence_time.tzinfo
        else commence_time
    )
    return tipoff <= (now or datetime.utcnow()) + START_BUFFER


def _single_pick_ungradeable_reason(bet_like) -> Optional[str]:
    """Mirror yetai_grading.grade_pick's pre-ESPN checks, same order, same inputs."""
    from app.services import yetai_grading as g

    sel = getattr(bet_like, "selection", None)
    if not g._meta(bet_like):
        bad = g.unsupported_market(sel)
        if bad:
            return f"Unsupported market: {bad}"
    spec = g.grading_spec(bet_like)
    if not spec:
        if not g.normalize_league(getattr(bet_like, "sport", None)):
            return f"Grader cannot settle {getattr(bet_like, 'sport', None)}"
        bt = getattr(getattr(bet_like, "bet_type", None), "value", None) or getattr(
            bet_like, "bet_type", ""
        )
        return f"Grader cannot parse pick '{sel}' for a {bt} bet"
    if not g.can_grade(spec["league"], spec["market"], spec.get("stat")):
        return f"Grader cannot settle {spec['league']} {spec['market']}"
    return None


def yetai_pick_ungradeable_reason(bet_like) -> Optional[str]:
    """Why the grader would void this pick as ungradeable (None when it can grade it)."""
    legs = getattr(bet_like, "parlay_legs", None)
    if not legs:
        return _single_pick_ungradeable_reason(bet_like)
    from app.services.yetai_parlay_verification import _leg_as_bet

    created = getattr(bet_like, "created_at", None)
    for n, leg in enumerate(legs, 1):
        if not isinstance(leg, dict):
            continue
        reason = _single_pick_ungradeable_reason(
            _leg_as_bet(leg, created.date() if created else None)
        )
        if reason:
            return f"Leg {n}: {reason}"
    return None


def publish_gate_reason(bet_like, *, now: Optional[datetime] = None) -> Optional[str]:
    """Why this pick must not be published now (started game or ungradeable); None = ok."""
    if not publish_gates_enabled():
        return None
    legs = getattr(bet_like, "parlay_legs", None)
    if legs:
        for n, leg in enumerate(legs, 1):
            ct = leg.get("commence_time") if isinstance(leg, dict) else None
            if ct:
                from app.services.yetai_parlay_verification import _parse_time

                if pick_started(_parse_time(ct), now=now):
                    game = leg.get("game") or leg.get("pick")
                    return (
                        "Game has already started (or starts within 20 minutes): "
                        f"Leg {n} {game}"
                    )
    elif pick_started(getattr(bet_like, "commence_time", None), now=now):
        game = getattr(bet_like, "title", None) or getattr(bet_like, "selection", "")
        return f"Game has already started (or starts within 20 minutes): {game}"
    return yetai_pick_ungradeable_reason(bet_like)


def yetai_pick_gradeable(bet: YetAIBet, *, now: Optional[datetime] = None) -> bool:
    """True when the game window has likely finished and auto-grading is safe."""
    now = now or datetime.utcnow()
    if yetai_auto_grade_held(bet, now):
        return False

    tipoff = _naive_utc(bet.commence_time)
    if tipoff is not None:
        return now >= tipoff + timedelta(hours=3)

    from app.services import yetai_grading

    if yetai_grading.game_day_for(bet) is None:
        return True  # no date anywhere: the grader voids it (nothing to wait for)

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


def settle_retry_days() -> int:
    """Days after the game day that an unready pick keeps being retried."""
    try:
        return int(os.getenv("YETAI_SETTLE_RETRY_DAYS", "3"))
    except ValueError:
        return 3


SETTLE_BACKSTOP_DAYS = 14


def _settlement(bet) -> dict:
    factors = getattr(bet, "prediction_factors", None)
    out = factors.get("settlement") if isinstance(factors, dict) else None
    return out if isinstance(out, dict) else {}


def settle_window_elapsed(day: Optional[date], now: datetime) -> bool:
    """True once ``now`` is past the end of ``day`` plus the retry window."""
    if day is None:
        return False
    return now > datetime.combine(day, time.max) + timedelta(days=settle_retry_days())


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
    def _is_parlay_bet(bet: YetAIBet) -> bool:
        if getattr(bet, "bet_type", None) == BetType.PARLAY:
            return True
        legs = getattr(bet, "parlay_legs", None)
        return isinstance(legs, list) and len(legs) >= 2

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
                    "run line": "spread",
                    "runline": "spread",
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

                refusal = publish_gate_reason(
                    SimpleNamespace(
                        sport=bet_request.sport,
                        bet_type=normalized_bet_type,
                        selection=bet_request.pick,
                        title=bet_request.game,
                        home_team=home_team,
                        away_team=away_team,
                        commence_time=game_commence_time,
                        created_at=datetime.utcnow(),
                        prediction_factors={},
                    )
                )
                if refusal:
                    return {"success": False, "error": refusal}

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

                refusal = publish_gate_reason(
                    SimpleNamespace(
                        parlay_legs=[
                            leg.model_dump(mode="json") for leg in parlay_request.legs
                        ],
                        created_at=datetime.utcnow(),
                    )
                )
                if refusal:
                    return {"success": False, "error": refusal}

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
    SUBSCRIBER_VISIBLE_STATUSES = {"active", "pending", "won", "lost", "pushed", "void"}
    YETAI_LIVE_STATUSES = ("active", "pending")
    YETAI_HISTORY_STATUSES = ("won", "lost", "pushed", "void")

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
    ) -> Dict[str, float | int | None]:
        won = [b for b in bets if b.get("status") == "won"]
        lost = [b for b in bets if b.get("status") == "lost"]
        pushed = [b for b in bets if b.get("status") == "pushed"]
        void = [b for b in bets if b.get("status") == "void"]
        graded = len(won) + len(lost)
        units = 0.0
        for bet in bets:
            status = bet.get("status")
            try:
                odds_val = float(bet.get("effective_odds") or bet.get("odds", 0))
            except (TypeError, ValueError):
                odds_val = 0.0
            if status == "won":
                units += self._american_odds_units_profit(odds_val)
            elif status == "lost":
                units -= 1.0
        # None (not 0) when nothing was graded: "no record" is not a 0% record.
        win_rate = round((len(won) / graded) * 100, 1) if graded else None
        return {
            "period_days": period_days,
            "total": len(bets),
            "won": len(won),
            "lost": len(lost),
            "pushed": len(pushed),
            "void": len(void),
            "graded": graded,
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

    def sync_unified_from_yetai_pick(
        self, db: Session, yetai: YetAIBet, unified_bet
    ) -> bool:
        """Make a linked placed bet equal its YetAI pick (the pick is the only grader).

        Terminal pick -> copy mirrors it (any correction allowed, void -> CANCELLED with
        the stake back). Pick back to active/pending (admin reopen) -> copy PENDING.
        """
        from app.models.simple_unified_bet_model import BetStatus as UnifiedBetStatus

        yetai_status = (yetai.status or "").lower()
        if yetai_status in {"active", "pending"}:
            if unified_bet.status in (UnifiedBetStatus.PENDING, UnifiedBetStatus.LIVE):
                return False
            unified_bet.status = UnifiedBetStatus.PENDING
            unified_bet.settled_at = None
            unified_bet.result_amount = None
            unified_bet.reasoning = None
            return True
        pulled = yetai_status in {"rejected", "expired"}
        if pulled:
            # Never published, or pulled before it was shown: nobody will grade the
            # copy, so an open one is cancelled with the stake back, like a void.
            # (Expired rows the sweep still grades or voids are left to it.)
            if unified_bet.status not in (
                UnifiedBetStatus.PENDING,
                UnifiedBetStatus.LIVE,
            ):
                return False
            if yetai_status == "expired" and (
                self._legacy_sweepable(yetai) or self._admin_expired_shown(db, yetai)
            ):
                return False
        elif yetai_status not in {"won", "lost", "pushed", "void"}:
            return False

        # A voided pick (postponed, DNP, ungradeable) refunds the placed bet: the
        # unified model's no-action status is CANCELLED with the stake returned.
        void = pulled or yetai_status == "void"
        target = UnifiedBetStatus.CANCELLED if void else UnifiedBetStatus(yetai_status)
        if unified_bet.status == target:
            return False

        unified_bet.status = target
        unified_bet.settled_at = yetai.settled_at or datetime.utcnow()
        note = (yetai.result or "").strip()
        unified_bet.reasoning = note or (
            f"YetAI pick withdrawn ({yetai_status}); stake returned"
            if pulled
            else f"Graded from YetAI pick ({yetai_status})"
        )

        if target == UnifiedBetStatus.WON:
            unified_bet.result_amount = unified_bet.amount + unified_bet.potential_win
        elif target in (UnifiedBetStatus.PUSHED, UnifiedBetStatus.CANCELLED):
            unified_bet.result_amount = unified_bet.amount
        else:
            unified_bet.result_amount = 0.0

        if not unified_bet.yetai_bet_id:
            unified_bet.yetai_bet_id = yetai.id

        return True

    def mirror_to_linked_copies(self, db: Session, yetai: YetAIBet) -> int:
        """Push the pick's state onto every linked user copy (caller commits)."""
        return sum(
            self.sync_unified_from_yetai_pick(db, yetai, copy)
            for copy in self._linked_unified_bets_for_yetai_pick(db, yetai)
        )

    def _mirror_in_savepoint(self, db: Session, yetai: YetAIBet) -> None:
        """Mirror inside a savepoint: a failing copy must not roll back (and so retry
        forever) the pick's own settlement. The page-load sync is the catch-up."""
        try:
            with db.begin_nested():
                self.mirror_to_linked_copies(db, yetai)
        except Exception:
            logger.exception(
                "YETAI_MIRROR_FAILED pick=%s (pick still settles)", yetai.id
            )

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

    def get_yetai_bets_for_user(self, user_tier: object, db: Session) -> List[Dict]:
        """Return open YetAI picks (active/pending) for the subscriber tier."""
        tier_slug = coerce_subscription_tier(user_tier)
        rows = self._query_yetai_bets_for_user(tier_slug, db, self.YETAI_LIVE_STATUSES)
        live_rows = [bet for bet in rows if yetai_bet_subscriber_live_visible(bet)]
        return [self._yetai_bet_to_dict(bet) for bet in live_rows]

    def _history_stat_rows(
        self, user_tier: str, db: Session, since: datetime
    ) -> List[Dict]:
        """Settled rows (the history population) as dicts for compute_history_stats."""
        return [
            {
                "status": bet.status,
                "odds": bet.odds,
                "effective_odds": _settlement(bet).get("effective_odds"),
                "created_at": bet.created_at,
                "settled_at": bet.settled_at,
            }
            for bet in self._query_yetai_bets_for_user(
                user_tier,
                db,
                self.YETAI_HISTORY_STATUSES,
                since=since,
                order_by="created",
            )
        ]

    def get_public_history_stats(self, db: Session, *, days: int = 90) -> Dict:
        """History stats over all non-demo shown picks (every tier) in the window."""
        since = datetime.utcnow() - timedelta(days=max(days, 1))
        rows = self._history_stat_rows(SubscriptionTier.ELITE.value, db, since)
        return self.compute_history_stats(rows, period_days=days)

    def get_yetai_bets_history_for_user(
        self,
        user_tier: str,
        db: Session,
        *,
        days: int = 90,
        limit: int = 100,
    ) -> tuple[List[Dict], Dict, Dict[str, Dict]]:
        """Promoted picks in the window (newest first).

        Returns (bets, stats, blocks): stats cover the whole window; blocks holds the
        `today` (America/New_York day) and `last_7d` stats over the same population:
        `today` counts results (settled_at in the ET day: last night's picks settle this
        morning and today's picks are pending all day); `last_7d` counts picks created
        in the last 7 days, like the history itself.
        """
        now = datetime.utcnow()
        since = now - timedelta(days=max(days, 1))
        rows = self._query_yetai_bets_for_user(
            user_tier,
            db,
            tuple(self.SUBSCRIBER_VISIBLE_STATUSES),
            since=since,
            limit=limit,
            order_by="created",
        )
        bets = [self._yetai_bet_to_dict(bet) for bet in rows]
        settled = self._history_stat_rows(user_tier, db, since)
        stats = self.compute_history_stats(settled, period_days=days)
        stats["returned"] = len(bets)
        stats["settled"] = len(settled)

        et_midnight = (
            datetime.now(ZoneInfo("America/New_York"))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .astimezone(timezone.utc)
            .replace(tzinfo=None)
        )

        def window(start: datetime, period: int, key: str) -> Dict:
            return self.compute_history_stats(
                [r for r in settled if r[key] and r[key] >= start],
                period_days=period,
            )

        blocks = {
            "today": window(et_midnight, 1, "settled_at"),
            "last_7d": window(now - timedelta(days=7), 7, "created_at"),
        }
        return bets, stats, blocks

    async def get_active_bets(self, user_tier: object = "free") -> List[Dict]:
        """Get active YetAI Bets based on user tier from database

        Returns bets that are:
        - Status "pending" or "active" (not yet settled, not pending_approval/rejected)
        - Tier-gated: FREE sees FREE only, PRO sees FREE+PRO, ELITE sees all

        Unsettled rows are graded by verify_pending_yetai_bets (never expired).
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

    async def delete_bet(self, bet_id: str, admin_user_id: int) -> Dict:
        """Delete a never-shown YetAI Bet (pending_approval/rejected) and its bet history"""
        try:
            db = SessionLocal()
            try:
                bet = db.query(YetAIBet).filter(YetAIBet.id == bet_id).first()

                if not bet:
                    return {"success": False, "error": "Bet not found"}

                if bet.status not in ("pending_approval", "rejected"):
                    return {
                        "success": False,
                        "code": 409,
                        "error": "This bet was shown to users; pull it instead "
                        "(POST /api/admin/yetai-picks/{id}/reject) so it stays in "
                        "history as void.",
                    }

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

    def _yetai_bet_to_dict(self, bet: YetAIBet) -> Dict:
        """Convert YetAIBet model to dictionary"""
        # Eastern wall clock: commence_time is naive UTC
        game_time_formatted = "TBD"
        if bet.commence_time:
            try:
                game_time_formatted = format_game_time_et(bet.commence_time)
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
            bet_dict["parlay_legs"] = [
                {
                    "sport": leg.get("sport"),
                    "game": leg.get("game"),
                    "pick": leg.get("pick"),
                    "odds": leg.get("odds"),
                    "bet_type": leg.get("bet_type"),
                    "leg_status": leg.get("leg_status") or "pending",
                    "leg_result": leg.get("leg_result"),
                }
                for leg in bet.parlay_legs
                if isinstance(leg, dict)
            ]

        return bet_dict

    def _expire_stale_pending_approval(self, db: Session) -> int:
        """Drop admin-queue picks that are past game day or >24h old without commence_time."""
        now = datetime.utcnow()
        stale_cutoff = now - timedelta(hours=24)
        rows = db.query(YetAIBet).filter(YetAIBet.status == "pending_approval").all()
        expired = []
        for row in rows:
            if row.commence_time is not None:
                tipoff = row.commence_time
                if tipoff.tzinfo is not None:
                    tipoff = tipoff.replace(tzinfo=None)
                if tipoff <= now:
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

    LEGACY_STATUSES = ("expired", "pending_manual_review")
    SETTLE_LEGACY_LIMIT = 50
    # Results written by "expired" writers whose rows may never have been shown:
    # the admin expire endpoint (any status) and the unapproved-queue expiry.
    NOT_GRADER_EXPIRED = ("Admin expired", "Auto-expired")

    @classmethod
    def _legacy_filter(cls):
        """Rows the old grader parked or expired itself (they were shown to users).

        History (git log -p): the old grader wrote ``pending_manual_review`` (results
        "Auto-expired: ...") and later ``expired`` with ``settled_at`` set and result
        "Unsettled >24h, no result" (or the prior result). The unapproved-queue expiry
        (expire_pending_picks / _expire_stale_pending_approval before 7f12466c) wrote
        ``expired`` with no result and no ``settled_at``; the admin expire wrote
        "Admin expired (stale pick)" on any status. Those two are never re-graded.
        """
        return or_(
            YetAIBet.status == "pending_manual_review",
            and_(
                YetAIBet.status == "expired",
                YetAIBet.settled_at.isnot(None),
                YetAIBet.result.isnot(None),
                *[~YetAIBet.result.ilike(f"{p}%") for p in cls.NOT_GRADER_EXPIRED],
            ),
        )

    def _admin_expired_shown(self, db: Session, bet: YetAIBet) -> bool:
        """Pick an admin (or the reopen script) expired that users had seen. Manual picks
        are created pending, so always shown. Auto picks look the same as never-approved
        queue rows, except when a user placed a copy (linked bet): that proves it was shown.
        Nothing writes "expired" any more; this only sweeps old rows."""
        if not (
            (bet.status or "").lower() == "expired"
            and (bet.result or "").lower().startswith("admin expired")
        ):
            return False
        source = getattr(bet.source, "value", bet.source)
        return source == BetSource.MANUAL.value or bool(
            self._linked_unified_bets_for_yetai_pick(db, bet)
        )

    @classmethod
    def _legacy_sweepable(cls, bet: YetAIBet) -> bool:
        status = (bet.status or "").lower()
        if status == "pending_manual_review":
            return True
        result = (bet.result or "").lower()
        return (
            status == "expired"
            and bet.settled_at is not None
            and bet.result is not None
            and not any(result.startswith(p.lower()) for p in cls.NOT_GRADER_EXPIRED)
        )

    def _settle_candidates(self, db: Session) -> List[YetAIBet]:
        """Unsettled rows, retryable error losses and legacy dead ends (oldest first)."""
        rows = (
            db.query(YetAIBet)
            .filter(
                or_(
                    YetAIBet.status.in_(YETAI_UNSETTLED_STATUSES),
                    and_(
                        YetAIBet.status == "lost", YetAIBet.result.ilike("Evaluation%")
                    ),
                )
            )
            .all()
        )
        legacy = (
            db.query(YetAIBet)
            .filter(self._legacy_filter())
            .order_by(YetAIBet.created_at)
            .limit(self.SETTLE_LEGACY_LIMIT)
            .all()
        )
        # Shown, then expired by an admin: moved to history as void (not re-graded).
        admin_expired = (
            db.query(YetAIBet)
            .filter(
                YetAIBet.status == "expired",
                YetAIBet.result.ilike("Admin expired%"),
            )
            .all()
        )
        admin_expired = [b for b in admin_expired if self._admin_expired_shown(db, b)]
        seen = set()
        return [
            b
            for b in [
                *rows,
                *legacy,
                *admin_expired,
                *self._pulled_with_open_copies(db),
            ]
            if not (b.id in seen or seen.add(b.id))
        ]

    @staticmethod
    def _pulled_with_open_copies(db: Session) -> List[YetAIBet]:
        """Rejected/expired picks that still have a PENDING/LIVE linked copy."""
        from app.models.simple_unified_bet_model import BetStatus as UnifiedBetStatus
        from app.models.simple_unified_bet_model import SimpleUnifiedBet

        prefix = "yetai-pick-"
        open_copies = (
            db.query(SimpleUnifiedBet.yetai_bet_id, SimpleUnifiedBet.odds_api_event_id)
            .filter(
                SimpleUnifiedBet.status.in_(
                    [UnifiedBetStatus.PENDING, UnifiedBetStatus.LIVE]
                )
            )
            .filter(
                or_(
                    SimpleUnifiedBet.yetai_bet_id.isnot(None),
                    SimpleUnifiedBet.odds_api_event_id.like(f"{prefix}%"),
                )
            )
            .all()
        )
        ids = {yid or (event or "")[len(prefix) :] for yid, event in open_copies} - {""}
        if not ids:
            return []
        return (
            db.query(YetAIBet)
            .filter(YetAIBet.id.in_(ids), YetAIBet.status.in_(["rejected", "expired"]))
            .all()
        )

    @staticmethod
    def _load_for_settlement(db: Session, bet_id: str) -> Optional[YetAIBet]:
        """Fresh row, row-locked on Postgres (skip rows another settler holds)."""
        query = db.query(YetAIBet).filter(YetAIBet.id == bet_id)
        try:
            postgres = db.get_bind().dialect.name == "postgresql"
        except Exception:
            postgres = False
        if postgres:
            query = query.with_for_update(skip_locked=True)
        return query.populate_existing().first()

    def _settle_one(self, db: Session, bet: YetAIBet, now: datetime) -> str:
        """Grade one bet. Returns skipped | pending | settled | void (caller commits)."""
        from app.services import yetai_grading
        from app.services import yetai_parlay_verification as parlays

        status = (bet.status or "").lower()
        if self._admin_expired_shown(db, bet):
            bet.status = "void"  # keeps the admin's reason in `result`
            bet.settled_at = bet.settled_at or now
            logger.info("YETAI_ADMIN_EXPIRED_TO_VOID bet=%s", bet.id)
            self._mirror_in_savepoint(db, bet)
            return "void"
        if status in ("rejected", "expired") and not self._legacy_sweepable(bet):
            self._mirror_in_savepoint(db, bet)  # cancel any open copy (A7)
            return "skipped"
        legacy = status in self.LEGACY_STATUSES
        error_loss = status == "lost" and self._is_retryable_error_loss(bet)
        if not (status in YETAI_UNSETTLED_STATUSES or legacy or error_loss):
            return "skipped"
        if legacy and not self._legacy_sweepable(bet):
            return "skipped"
        if yetai_auto_grade_held(bet, now):
            return "skipped"
        if status in YETAI_UNSETTLED_STATUSES and not yetai_pick_gradeable(
            bet, now=now
        ):
            return "skipped"

        prior = _settlement(bet)
        first_attempt = prior.get("first_attempt_at") or now.isoformat()
        try:
            first_day = datetime.fromisoformat(str(first_attempt)).date()
        except ValueError:
            first_attempt, first_day = now.isoformat(), now.date()

        parlay = self._is_parlay_bet(bet)
        game_day = (
            parlays.parlay_last_day(bet) if parlay else yetai_grading.game_day_for(bet)
        ) or (bet.created_at.date() if bet.created_at else now.date())
        # Legacy rows get a full window from their first attempt, not from game day.
        anchor = max(game_day, first_day)
        window_over = settle_window_elapsed(anchor, now)
        backstop = now > datetime.combine(anchor, time.max) + timedelta(
            days=SETTLE_BACKSTOP_DAYS
        )

        legs = None
        if parlay:
            outcome, legs = parlays.grade_parlay(bet, now, window_over, backstop)
        else:
            outcome = yetai_grading.grade_pick(bet, db)

        kind, text = outcome.kind, outcome.result
        if kind in ("not_ready", "error") and not parlay:
            waiting = kind == "error" or text in yetai_grading.WAITING
            if backstop or (window_over and not waiting):
                kind, text = "void", f"Ungradeable: {text}"
        if kind == "ungradeable":
            kind, text = "void", f"Ungradeable: {text}"
        keep_error_loss = error_loss and kind not in ("won", "lost", "pushed")

        settlement = {
            "attempts": int(prior.get("attempts", 0) or 0) + 1,
            "first_attempt_at": first_attempt,
            "last_attempt_at": now.isoformat(),
            "last_kind": outcome.kind,
            "last_error": text if kind in ("not_ready", "error", "void") else None,
        }
        if parlay and kind == "won" and legs:
            effective = parlays.effective_parlay_odds(legs)
            if effective is not None:
                settlement["effective_odds"] = effective
        factors = (
            dict(bet.prediction_factors)
            if isinstance(bet.prediction_factors, dict)
            else {}
        )
        factors["settlement"] = settlement
        self._add_closing(db, bet, factors, now)
        bet.prediction_factors = factors
        if legs:
            bet.parlay_legs = legs

        if kind in ("not_ready", "error") or keep_error_loss:
            return "pending"
        if kind == "void":
            logger.error(
                "YETAI_SETTLEMENT_VOID bet=%s sport=%s selection=%r reason=%s",
                bet.id,
                bet.sport,
                bet.selection,
                text,
            )
        bet.status = kind
        bet.settled_at = now
        bet.result = clamp_yetai_result(text, max_len=200)
        self._mirror_in_savepoint(db, bet)
        return "void" if kind == "void" else "settled"

    @staticmethod
    def _add_closing(db: Session, bet: YetAIBet, factors: dict, now: datetime) -> None:
        """Store the closing quote and CLV on an auto NBA prop once its game has started.

        Never blocks settlement; nothing is written when no close exists yet."""
        try:
            g = factors.get("grading") or {}
            ct = bet.commence_time
            if (
                factors.get("closing")
                or str(
                    getattr(bet.source, "value", getattr(bet, "source", None))
                ).lower()
                != "auto"
                or g.get("league") != "NBA"
                or g.get("market") != "player_prop"
                or not ct
                or ct.replace(tzinfo=None) > now.replace(tzinfo=None)
            ):
                return
            from app.services.prop_clv import NBA_STAT_MARKET, clv_vs_close
            from app.services.odds_snapshots import closing_quotes

            market = NBA_STAT_MARKET.get(g.get("stat"))
            side = {"over": "o", "under": "u"}.get(g.get("side"))
            if not (market and side and g.get("player") and g.get("line") is not None):
                return
            day = date.fromisoformat(str(g["game_date"])[:10])
            with db.begin_nested():  # a failed read must not abort the settlement
                rows = closing_quotes(db, day, market, g["player"])
            book = (factors.get("projection_metadata") or {}).get("book") or "fanduel"
            c = clv_vs_close(side, float(g["line"]), bet.odds, book, rows, market)
            if c is None:
                return
            r = c["row"]
            factors["closing"] = {
                "book": c["book"],
                "line": c["line"],
                "price": c["price"],
                "observed_at": r.first_seen_at.isoformat(),
                "last_seen_at": r.last_seen_at.isoformat(),
                "line_clv": c["line_clv"],
                "prob_clv": c["prob_clv"],
                "books": c["books"],
            }
        except Exception:
            logger.exception("YETAI_CLOSING_FAILED bet=%s", getattr(bet, "id", None))

    def _record_settlement_error(
        self, db: Session, bet_id: str, exc: Exception
    ) -> None:
        """Best-effort: note why a row failed, in its own transaction."""
        try:
            bet = db.query(YetAIBet).filter(YetAIBet.id == bet_id).first()
            if bet is None:
                return
            factors = dict(bet.prediction_factors or {})
            prior = _settlement(bet)
            now = datetime.utcnow().isoformat()
            factors["settlement"] = {
                **prior,
                "attempts": int(prior.get("attempts", 0) or 0) + 1,
                "first_attempt_at": prior.get("first_attempt_at") or now,
                "last_attempt_at": now,
                "last_kind": "error",
                "last_error": f"{type(exc).__name__}: {exc}"[:300],
            }
            bet.prediction_factors = factors
            db.commit()
        except Exception:
            db.rollback()

    def verify_pending_yetai_bets(self) -> Dict:
        """
        Settle every shown YetAI bet through ``yetai_grading.grade_pick``.

        Plain (blocking) function: the Celery task calls it directly, async callers via
        ``asyncio.to_thread``. Each bet is re-loaded (row-locked on Postgres), graded and
        committed on its own, so one bad row never blocks the others and concurrent
        settlers never double-write. Nothing is ever expired: a bet that cannot be graded
        within ``YETAI_SETTLE_RETRY_DAYS`` becomes ``void`` with a reason (transport
        errors only after the 14-day backstop). ``expired`` is kept and is always 0.
        """
        from app.services import espn_results

        logger.info("Starting YetAI bets verification...")
        espn_results.clear_cache()  # the cache never expires; the worker is long-lived
        db = SessionLocal()
        try:
            expired_approval = self._expire_stale_pending_approval(db)
            if expired_approval:
                logger.info(
                    "Expired %s stale pending_approval YetAI picks", expired_approval
                )
                db.commit()

            candidate_ids = [b.id for b in self._settle_candidates(db)]
            db.commit()  # end the read transaction; each bet gets its own below
            counts = {"settled": 0, "voided": 0}
            now = datetime.utcnow()
            for bet_id in candidate_ids:
                try:
                    bet = self._load_for_settlement(db, bet_id)
                    # None: another settler holds the row lock (or it was deleted)
                    result = self._settle_one(db, bet, now) if bet else "skipped"
                    db.commit()
                except Exception as exc:
                    logger.error(
                        "YetAI settlement failed for %s: %s", bet_id, exc, exc_info=True
                    )
                    db.rollback()
                    self._record_settlement_error(db, bet_id, exc)
                    continue
                if result in ("settled", "void"):
                    counts["settled"] += 1
                if result == "void":
                    counts["voided"] += 1

            logger.info(
                "YetAI verification complete: %s of %s settled (%s void)",
                counts["settled"],
                len(candidate_ids),
                counts["voided"],
            )
            return {
                "success": True,
                "verified": len(candidate_ids),
                "settled": counts["settled"],
                "voided": counts["voided"],
                "expired": 0,
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
