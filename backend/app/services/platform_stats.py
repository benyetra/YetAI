"""Platform-wide stats for the public login / auth hero panel."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.models.database_models import User, YetAIBet
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
        odds = float(bet.odds or 0)
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


def compute_platform_stats(db: Session) -> Dict[str, Any]:
    """Aggregate YetAI Bets performance for /api/platform/stats."""
    total_users = (
        db.query(func.count(User.id)).filter(User.is_hidden == False).scalar() or 0
    )

    graded = _graded_bets(db)
    won = [b for b in graded if b.status == "won"]

    total_winnings = sum(_profit_dollars(b) for b in won)

    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    def in_window(bet: YetAIBet, start: datetime, end: datetime | None = None) -> bool:
        ts = _settlement_time(bet)
        if ts < start:
            return False
        if end is not None and ts >= end:
            return False
        return True

    last_30_days = [b for b in graded if in_window(b, thirty_days_ago)]
    last_7_days = [b for b in graded if in_window(b, seven_days_ago)]
    prev_7_days = [b for b in graded if in_window(b, fourteen_days_ago, seven_days_ago)]

    wins_30d = sum(1 for b in last_30_days if b.status == "won")
    total_30d = len(last_30_days)
    win_rate_30d = (wins_30d / total_30d * 100) if total_30d > 0 else 0
    profit_30d = sum(_profit_dollars(b) for b in last_30_days)

    wins_7d = sum(1 for b in last_7_days if b.status == "won")
    total_7d = len(last_7_days)
    win_rate_7d = (wins_7d / total_7d * 100) if total_7d > 0 else 0
    profit_7d = sum(_profit_dollars(b) for b in last_7_days)
    profit_prev_7d = sum(_profit_dollars(b) for b in prev_7_days)

    if profit_prev_7d != 0:
        wow_change = ((profit_7d - profit_prev_7d) / abs(profit_prev_7d)) * 100
    elif profit_7d > 0:
        wow_change = 100.0
    else:
        wow_change = 0.0

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
        "performance_30d": {
            "win_rate": round(win_rate_30d, 1),
            "profit": round(profit_30d, 2),
            "total_bets": total_30d,
            "wins": wins_30d,
            "losses": total_30d - wins_30d,
        },
        "performance_7d": {
            "win_rate": round(win_rate_7d, 1),
            "profit": round(profit_7d, 2),
            "wow_change": round(wow_change, 1),
        },
        "user_avatars": user_avatars,
    }
