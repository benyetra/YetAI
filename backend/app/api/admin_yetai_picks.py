"""Admin API for listing, approving, editing, and rejecting pending YetAI auto-picks."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Any, Optional

from app.core.database import get_db
from app.core.auth import require_admin
from app.models.database_models import AutoPickRun, YetAIBet, SubscriptionTier
from app.services.auto_pick.diagnostics import get_run_diagnostics
from app.services.yetai_bets_service_db import (
    clamp_yetai_result,
    set_yetai_auto_grade_hold,
)

router = APIRouter(prefix="/api/admin/yetai-picks", tags=["admin-yetai-picks"])

PENDING_STATUS = "pending_approval"
ACTIVE_STATUS = "active"
REJECTED_STATUS = "rejected"
EXPIRED_STATUS = "expired"
REOPENABLE_STATUSES = frozenset({"won", "lost", "pushed", "expired"})
EXPIRABLE_STATUSES = frozenset({"pending", "active", "pending_approval"})


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


class EditPickRequest(BaseModel):
    tier_requirement: Optional[SubscriptionTier] = None
    reasoning: Optional[str] = None
    selection: Optional[str] = None
    odds: Optional[float] = None
    title: Optional[str] = None


def _clear_parlay_leg_results(legs: Any) -> Any:
    if not isinstance(legs, list):
        return legs
    cleaned: list = []
    for leg in legs:
        if isinstance(leg, dict):
            cleaned.append({k: v for k, v in leg.items() if k != "leg_result"})
        else:
            cleaned.append(leg)
    return cleaned


def _serialize(bet: YetAIBet) -> dict:
    return {
        "id": bet.id,
        "title": bet.title,
        "selection": bet.selection,
        "bet_type": bet.bet_type.value if bet.bet_type else None,
        "sport": bet.sport,
        "odds": bet.odds,
        "status": bet.status,
        "tier_requirement": (
            bet.tier_requirement.value if bet.tier_requirement else None
        ),
        "confidence_score": bet.confidence_score,
        "score_breakdown": bet.score_breakdown,
        "reasoning": bet.reasoning,
        "source": bet.source.value if bet.source else None,
        "created_at": bet.created_at.isoformat() if bet.created_at else None,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/diagnostics")
async def run_diagnostics(
    run_id: int,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Projection coverage + drop-reason summary for an auto_pick_runs row."""
    body = get_run_diagnostics(db, run_id)
    if not body.get("found"):
        raise HTTPException(status_code=404, detail=f"Auto-pick run {run_id} not found")
    return body


@router.get("/runs/latest")
async def latest_run_diagnostics(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Diagnostics for the most recent auto_pick_runs row."""
    run = db.query(AutoPickRun).order_by(AutoPickRun.id.desc()).first()
    if not run:
        raise HTTPException(status_code=404, detail="No auto-pick runs yet")
    return get_run_diagnostics(db, run.id)


@router.get("/pending")
async def list_pending(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List all bets currently in pending_approval status."""
    rows = db.query(YetAIBet).filter(YetAIBet.status == PENDING_STATUS).all()
    return {"picks": [_serialize(b) for b in rows]}


@router.post("/{pick_id}/approve")
async def approve(
    pick_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Approve a single pending pick → active."""
    bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
    if not bet:
        raise HTTPException(status_code=404, detail="Pick not found")
    if bet.status != PENDING_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve a bet in status '{bet.status}'",
        )
    bet.status = ACTIVE_STATUS
    db.commit()
    return _serialize(bet)


@router.post("/{pick_id}/reopen")
async def reopen(
    pick_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return a settled pick to active (clears settlement) after bad auto-grading."""
    bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
    if not bet:
        raise HTTPException(status_code=404, detail="Pick not found")
    if bet.status not in REOPENABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reopen a bet in status '{bet.status}'",
        )
    bet.status = ACTIVE_STATUS
    bet.settled_at = None
    bet.result = None
    set_yetai_auto_grade_hold(bet, held=True)
    if bet.parlay_legs:
        bet.parlay_legs = _clear_parlay_leg_results(bet.parlay_legs)
    db.commit()
    return _serialize(bet)


@router.post("/{pick_id}/expire")
async def expire_pick(
    pick_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Expire a stale unsettled pick so it leaves the subscriber live board."""
    bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
    if not bet:
        raise HTTPException(status_code=404, detail="Pick not found")
    if bet.status not in EXPIRABLE_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot expire a bet in status '{bet.status}'",
        )
    bet.status = EXPIRED_STATUS
    bet.settled_at = datetime.utcnow()
    bet.result = clamp_yetai_result("Admin expired (stale pick)")
    db.commit()
    return _serialize(bet)


@router.post("/{pick_id}/reject")
async def reject(
    pick_id: str,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Reject a single pending pick."""
    bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
    if not bet:
        raise HTTPException(status_code=404, detail="Pick not found")
    if bet.status != PENDING_STATUS:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject a bet in status '{bet.status}'",
        )
    bet.status = REJECTED_STATUS
    db.commit()
    return _serialize(bet)


@router.patch("/{pick_id}")
async def edit(
    pick_id: str,
    payload: EditPickRequest,
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Edit editable fields on any pending pick (tier_requirement, reasoning, selection, odds, title)."""
    bet = db.query(YetAIBet).filter(YetAIBet.id == pick_id).first()
    if not bet:
        raise HTTPException(status_code=404, detail="Pick not found")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(bet, field, val)
    db.commit()
    return _serialize(bet)


@router.post("/approve-all")
async def approve_all(
    _: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Bulk-approve every pending_approval pick in one shot."""
    rows = db.query(YetAIBet).filter(YetAIBet.status == PENDING_STATUS).all()
    for bet in rows:
        bet.status = ACTIVE_STATUS
    db.commit()
    return {"approved": [b.id for b in rows]}
