"""Admin API for listing, approving, editing, and rejecting pending YetAI auto-picks."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.auth import require_admin
from app.models.database_models import AutoPickRun, YetAIBet, SubscriptionTier
from app.services.auto_pick.diagnostics import get_run_diagnostics

router = APIRouter(prefix="/api/admin/yetai-picks", tags=["admin-yetai-picks"])

PENDING_STATUS = "pending_approval"
ACTIVE_STATUS = "active"
REJECTED_STATUS = "rejected"


# ---------------------------------------------------------------------------
# Request / response helpers
# ---------------------------------------------------------------------------


class EditPickRequest(BaseModel):
    tier_requirement: Optional[SubscriptionTier] = None
    reasoning: Optional[str] = None
    selection: Optional[str] = None
    odds: Optional[float] = None
    title: Optional[str] = None


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
