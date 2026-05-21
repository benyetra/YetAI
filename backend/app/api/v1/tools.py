"""Tools ported from YetiBets / Yetimonstah — betting corner, etc."""

from datetime import date as date_type, datetime, timedelta
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.predictions_models import BettingCorner

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])

ALLOWED_RESULTS: tuple[str, ...] = ("Pending", "Win", "Loss", "Push")


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


# ---------------------------------------------------------------------------
# Admin CRUD for Owen's Betting Corner
# ---------------------------------------------------------------------------


class OwensBetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    odds: str = Field(min_length=1, max_length=50)
    date: date_type
    result: Literal["Pending", "Win", "Loss", "Push"] = "Pending"


class OwensBetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    odds: Optional[str] = Field(default=None, min_length=1, max_length=50)
    date: Optional[date_type] = None
    result: Optional[Literal["Pending", "Win", "Loss", "Push"]] = None


def _require_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """Lightweight admin guard for this router.

    The main app's require_admin lives in main.py and depends on the auth
    service. We don't want to import main.py here, so re-check the same
    is_admin flag the auth layer already attaches to the current user.
    """
    if not current_user.get("is_admin", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return current_user


admin_router = APIRouter(
    prefix="/api/admin/owens-bets",
    tags=["admin", "tools"],
    dependencies=[Depends(_require_admin_user)],
)


@admin_router.get("")
def admin_list_owens_bets(
    result: Optional[Literal["Pending", "Win", "Loss", "Push"]] = None,
    limit: int = 200,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List Owen's bets for admin management — newest first, optional filter."""
    limit = max(1, min(limit, 1000))
    q = db.query(BettingCorner)
    if result is not None:
        q = q.filter(BettingCorner.result == result)
    bets = (
        q.order_by(BettingCorner.date.desc(), BettingCorner.id.desc())
        .limit(limit)
        .all()
    )
    return {"bets": [_bet_row(b) for b in bets], "count": len(bets)}


@admin_router.post("", status_code=status.HTTP_201_CREATED)
def admin_create_owens_bet(
    payload: OwensBetCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new Owen's bet."""
    bet = BettingCorner(
        name=payload.name.strip(),
        odds=payload.odds.strip(),
        date=payload.date,
        result=payload.result,
    )
    db.add(bet)
    db.commit()
    db.refresh(bet)
    return _bet_row(bet)


@admin_router.patch("/{bet_id}")
def admin_update_owens_bet(
    bet_id: int,
    payload: OwensBetUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update fields on an Owen's bet (typically used to settle a pending pick)."""
    bet = db.query(BettingCorner).filter(BettingCorner.id == bet_id).first()
    if not bet:
        raise HTTPException(status_code=404, detail="Bet not found")

    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates:
        bet.name = updates["name"].strip()
    if "odds" in updates:
        bet.odds = updates["odds"].strip()
    if "date" in updates:
        bet.date = updates["date"]
    if "result" in updates:
        bet.result = updates["result"]

    db.commit()
    db.refresh(bet)
    return _bet_row(bet)


@admin_router.delete("/{bet_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_owens_bet(
    bet_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Delete an Owen's bet."""
    deleted = (
        db.query(BettingCorner)
        .filter(BettingCorner.id == bet_id)
        .delete(synchronize_session=False)
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="Bet not found")
    db.commit()
