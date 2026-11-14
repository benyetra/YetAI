"""Admin API: the daily model review (same report that is emailed at 09:45 ET)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.database import get_db
from app.services.auto_pick.candidate import utc_to_eastern
from app.services.model_review_service import build_review, render_text

router = APIRouter(prefix="/api/admin/model-review", tags=["admin-model-review"])


@router.get("")
def get_model_review(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: dict = Depends(require_admin),
) -> dict:
    """Review as of ``date`` (YYYY-MM-DD, default today ET)."""
    try:
        today = (
            datetime.strptime(date, "%Y-%m-%d").date()
            if date
            else utc_to_eastern(datetime.utcnow()).date()
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD")
    review = build_review(db, today)
    return {**review, "text": render_text(review)}
