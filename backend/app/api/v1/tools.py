"""Tools ported from YetiBets / Yetimonstah — betting corner, etc."""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.predictions_models import BettingCorner

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


def _bet_row(bet: BettingCorner) -> dict[str, Any]:
    return {
        "id": bet.id,
        "name": bet.name,
        "odds": bet.odds,
        "date": bet.date.isoformat() if bet.date else None,
        "result": bet.result,
    }


def _implied_units_for_bet(bet: BettingCorner) -> float:
    odds = (bet.odds or "").strip()
    if bet.result == "Win":
        if odds.startswith("+"):
            return (float(odds.replace("+", "")) / 100) + 1
        if odds.startswith("-"):
            return (100 / float(odds.replace("-", ""))) + 1
        return 1.0
    if bet.result == "Loss":
        return -1.0
    return 0.0


@router.get("/owens-betting-corner")
def owens_betting_corner(
    _user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Pending and historical picks from Owen's Betting Corner."""
    today = datetime.today()
    week_start = today - timedelta(days=today.weekday())

    pending = (
        db.query(BettingCorner)
        .filter(
            BettingCorner.result == "Pending",
            BettingCorner.date >= week_start.date(),
        )
        .order_by(BettingCorner.date.asc())
        .all()
    )

    historical = (
        db.query(BettingCorner)
        .filter(BettingCorner.result != "Pending")
        .order_by(BettingCorner.date.desc())
        .all()
    )

    implied_units = sum(_implied_units_for_bet(b) for b in historical)
    total = len(historical)
    wins = sum(1 for b in historical if b.result == "Win")
    losses = total - wins
    success_rate = round((wins / total * 100), 2) if total else 0.0

    return {
        "pending_bets": [_bet_row(b) for b in pending],
        "historical_bets": [_bet_row(b) for b in historical],
        "summary": {
            "total_historical": total,
            "wins": wins,
            "losses": losses,
            "success_rate": success_rate,
            "implied_units": round(implied_units, 1),
            "implied_units_display": (
                f"+{implied_units:.1f}" if implied_units > 0 else f"{implied_units:.1f}"
            ),
        },
    }
