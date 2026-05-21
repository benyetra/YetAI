"""
Prediction endpoints — surfaces YetiBets' ML prediction tables (the pred_*
schema) via YetAI's REST API.

Each sport endpoint returns the most recent rows from the highest-value
prediction tables for that sport. PRO and ELITE subscribers only.

Today's auth path returns subscription_tier='pro' for any valid-looking JWT
(see app/main.py:get_current_user), so the tier guard is effectively permissive
in dev; the guard will start enforcing real tiers once auth is fixed.
"""

from datetime import date as date_type
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.predictions_models import (
    AssistsProjections,
    BlocksProjections,
    GameProjections,
    Homer,
    KickerPredictions,
    NBATotalsProjections,
    NHLGoaliePredictions,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsPredictions,
    PointsProjections,
    PRAProjections,
    ProjectedHits,
    ProjectedHomers,
    QBPredictions,
    ReboundsProjections,
    StealsProjections,
    StrikeoutProjections,
    ThreePointProjections,
)

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

ALLOWED_TIERS = {"pro", "elite", "PRO", "ELITE"}
DEFAULT_LIMIT = 50
MAX_LIMIT = 500


def require_paid_tier(current_user: dict = Depends(get_current_user)) -> dict:
    """Guard: only PRO/ELITE subscribers can read predictions."""
    tier = current_user.get("subscription_tier", "free")
    if tier not in ALLOWED_TIERS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Predictions require a PRO or ELITE subscription.",
        )
    return current_user


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _query_recent(
    db: Session,
    model: Any,
    date_col_name: str | None,
    target_date: date_type | None,
    limit: int,
    *,
    dedupe_keys: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    q = db.query(model)
    if date_col_name and target_date is not None:
        q = q.filter(getattr(model, date_col_name) == target_date)
    if hasattr(model, "id"):
        q = q.order_by(model.id.desc())
    fetch_limit = limit * 5 if dedupe_keys else limit
    rows = [_row_to_dict(r) for r in q.limit(fetch_limit).all()]
    if not dedupe_keys:
        return rows[:limit]
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in dedupe_keys)
        if key not in latest:
            latest[key] = row
    return list(latest.values())[:limit]


@router.get("/health")
def health() -> dict[str, Any]:
    """Public — confirms the predictions module is wired up."""
    return {"status": "ok", "module": "predictions", "tables_exposed": 15}


@router.get("/mlb")
def mlb_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent MLB props: strikeouts, game slate, batter boards, HR picks."""
    return {
        "strikeout_projections": _query_recent(
            db, StrikeoutProjections, "date", target_date, limit
        ),
        "game_projections": _query_recent(
            db, GameProjections, "date", target_date, limit
        ),
        "projected_hits": _query_recent(db, ProjectedHits, "date", target_date, limit),
        "projected_homers": _query_recent(
            db, ProjectedHomers, "date", target_date, limit
        ),
        "home_run_predictions": _query_recent(db, Homer, None, None, limit),
    }


@router.get("/nba")
def nba_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NBA props: game totals O/U plus points, assists, rebounds, etc."""
    return {
        "totals": _query_recent(
            db, NBATotalsProjections, "game_date", target_date, limit
        ),
        "points": _query_recent(db, PointsProjections, "date", target_date, limit),
        "assists": _query_recent(db, AssistsProjections, "date", target_date, limit),
        "rebounds": _query_recent(db, ReboundsProjections, "date", target_date, limit),
        "three_point": _query_recent(
            db, ThreePointProjections, "date", target_date, limit
        ),
        "steals": _query_recent(db, StealsProjections, "date", target_date, limit),
        "blocks": _query_recent(db, BlocksProjections, "date", target_date, limit),
        "pra": _query_recent(db, PRAProjections, "date", target_date, limit),
    }


@router.get("/nfl")
def nfl_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NFL props: QB passing/rushing + kicker FG predictions."""
    return {
        "qb_predictions": _query_recent(
            db, QBPredictions, "game_date", target_date, limit
        ),
        "kicker_predictions": _query_recent(
            db, KickerPredictions, "game_date", target_date, limit
        ),
    }


@router.get("/nhl")
def nhl_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NHL props: goalie saves, player SOG, game totals O/U."""
    return {
        "goalie_predictions": _query_recent(
            db,
            NHLGoaliePredictions,
            "game_date",
            target_date,
            limit,
            dedupe_keys=("goalie_id", "game_date"),
        ),
        "player_shots": _query_recent(
            db,
            NHLPlayerShotsPredictions,
            "game_date",
            target_date,
            limit,
            dedupe_keys=("player_id", "game_date"),
        ),
        "team_totals": _query_recent(
            db,
            NHLTeamTotalsPredictions,
            "game_date",
            target_date,
            limit,
            dedupe_keys=("home_team_id", "away_team_id", "game_date"),
        ),
    }
