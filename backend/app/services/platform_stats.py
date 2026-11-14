"""Platform-wide stats for the public login / auth hero panel."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.database_models import SubscriptionTier, User, YetAIBet
from app.services.yetai_bets_demo import is_demo_yetai_bet


def _settlement_time(bet: YetAIBet) -> datetime:
    return bet.settled_at or bet.created_at or datetime.utcnow()


def _profit_dollars(bet: YetAIBet, *, stake: float = 100.0) -> float:
    """Profit for a $100 unit on a graded straight pick (won = profit, lost = -stake)."""
    status = (bet.status or "").lower()
    if status == "lost":
        return -stake
    if status != "won":
        return 0.0
    try:
        # A parlay with void/pushed legs pays at the reduced price the grader stored.
        factors = (
            bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
        )
        effective = (factors.get("settlement") or {}).get("effective_odds")
        odds = float(effective or bet.odds or 0)
    except (TypeError, ValueError):
        return 0.0
    if odds > 0:
        return stake * (odds / 100.0)
    if odds < 0:
        return stake * (100.0 / abs(odds))
    return 0.0


def _graded_bets(db: Session) -> List[YetAIBet]:
    rows = db.query(YetAIBet).filter(YetAIBet.status.in_(["won", "lost"])).all()
    return [b for b in rows if not is_demo_yetai_bet(b)]


PUBLIC_RECORD_DAYS = 90


def public_record(db: Session, service: Any = None) -> Dict[str, Any]:
    """Login-panel record: the history stats over all non-demo shown picks (every
    tier, no user tier on a public page), same 90d created_at window as history."""
    if service is None:
        from app.services.yetai_bets_service_db import YetAIBetsServiceDB

        service = YetAIBetsServiceDB()
    stats = service.get_public_history_stats(db, days=PUBLIC_RECORD_DAYS)
    return {
        "label": f"Last {PUBLIC_RECORD_DAYS} days, all YetAI Bets",
        "stats": stats,
    }


def legacy_performance(db: Session, service: Any = None, now: datetime | None = None):
    """performance_30d / performance_7d in the shape the previously deployed login
    panel reads (a bundle cached in a browser, or a frontend deployed after this
    backend, calls ``performance_30d.win_rate.toFixed``): same population and
    created_at windows as ``record``, $100 a pick, numbers (never null)."""
    if service is None:
        from app.services.yetai_bets_service_db import YetAIBetsServiceDB

        service = YetAIBetsServiceDB()
    now = now or datetime.utcnow()
    rows = service._history_stat_rows(
        SubscriptionTier.ELITE.value, db, now - timedelta(days=30)
    )

    def window(days: int, ago: int = 0):
        lo, hi = now - timedelta(days=days + ago), now - timedelta(days=ago)
        stats = service.compute_history_stats(
            [r for r in rows if r["created_at"] and lo <= r["created_at"] < hi],
            period_days=days,
        )
        return stats, round(stats["units"] * 100, 2)

    s30, profit_30d = window(30)
    s7, profit_7d = window(7)
    _, profit_prev = window(7, ago=7)
    if profit_prev != 0:
        wow = (profit_7d - profit_prev) / abs(profit_prev) * 100
    else:
        wow = 100.0 if profit_7d > 0 else 0.0
    return {
        "performance_30d": {
            "win_rate": s30["win_rate"] or 0.0,
            "profit": profit_30d,
            "total_bets": s30["graded"],
            "wins": s30["won"],
            "losses": s30["lost"],
        },
        "performance_7d": {
            "win_rate": s7["win_rate"] or 0.0,
            "profit": profit_7d,
            "wow_change": round(wow, 1),
        },
    }


def compute_platform_stats(db: Session) -> Dict[str, Any]:
    """Aggregate YetAI Bets performance for /api/platform/stats."""
    total_users = (
        db.query(func.count(User.id)).filter(User.is_hidden == False).scalar() or 0
    )

    graded = _graded_bets(db)
    won = [b for b in graded if b.status == "won"]

    total_winnings = sum(_profit_dollars(b) for b in won)

    record = public_record(db)

    recent_users = (
        db.query(User)
        .filter(and_(User.avatar_url.isnot(None), User.is_hidden == False))
        .order_by(User.created_at.desc())
        .limit(3)
        .all()
    )
    user_avatars = []
    for user in recent_users:
        if user.avatar_url:
            user_avatars.append(
                {
                    "url": user.avatar_url,
                    "name": f"{user.first_name or ''} {user.last_name or ''}".strip()
                    or user.username,
                }
            )

    return {
        "total_users": total_users,
        "total_winnings": round(total_winnings, 2),
        "record": record,
        **legacy_performance(db),
        "user_avatars": user_avatars,
    }
