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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import DateTime, func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.predictions_models import (
    AssistsProjections,
    BlocksProjections,
    GameProjections,
    Homer,
    KickerPredictions,
    NBASpreadProjections,
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
    StrikeoutActuals,
    StrikeoutProjections,
    ThreePointProjections,
    WNBAAssistsProjections,
    WNBAPointsProjections,
    WNBAReboundsProjections,
    WNBASpreadProjections,
    WNBATotalsProjections,
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


def _safe_tz(tz: str) -> str:
    """Validate the IANA timezone string. Falls back to UTC if invalid."""
    try:
        ZoneInfo(tz)
        return tz
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def _query_recent(
    db: Session,
    model: Any,
    date_col_name: str | None,
    target_date: date_type | None,
    limit: int,
    *,
    tz: str = "UTC",
    dedupe_keys: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    q = db.query(model)
    if date_col_name and target_date is not None:
        col = getattr(model, date_col_name)
        if isinstance(col.type, DateTime):
            # Naive DateTime columns are stored as UTC. Convert to the user's
            # timezone, then extract the calendar date so the picker matches
            # what the user sees locally.
            local_col = func.timezone(tz, func.timezone("UTC", col))
            q = q.filter(func.date(local_col) == target_date)
        else:
            # Date columns: compare directly.
            q = q.filter(col == target_date)
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
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent MLB props: strikeouts, game slate, batter boards, HR picks.

    Each strikeout projection row is enriched with actual_strikeouts and
    actual_innings_pitched when the corresponding StrikeoutActuals row
    exists for the same date — the frontend uses these to render
    actual-vs-projection columns on past-date views.
    """
    tz = _safe_tz(tz)
    strikeouts = _query_recent(
        db, StrikeoutProjections, "date", target_date, limit, tz=tz
    )
    # Drop rows with blank pitcher_name (incomplete ETL writes) and dedupe by
    # pitcher_id so the same pitcher doesn't appear twice in the table.
    seen_pitchers: set[str] = set()
    cleaned_strikeouts = []
    for row in strikeouts:
        name = (row.get("pitcher_name") or "").strip()
        if not name:
            continue
        pid = row.get("pitcher_id")
        if pid in seen_pitchers:
            continue
        seen_pitchers.add(pid)
        cleaned_strikeouts.append(row)

    # Merge actuals for the selected date. When target_date is None (today),
    # actuals likely don't exist yet — the lookup returns an empty dict and
    # rows pass through unchanged.
    actuals_date = target_date
    if actuals_date is None and cleaned_strikeouts:
        first_date = cleaned_strikeouts[0].get("date")
        if first_date is not None:
            actuals_date = first_date
    if actuals_date is not None:
        actuals_by_pid = {
            r.pitcher_id: r
            for r in db.query(StrikeoutActuals)
            .filter(StrikeoutActuals.date == actuals_date)
            .all()
        }
        for row in cleaned_strikeouts:
            actual = actuals_by_pid.get(row.get("pitcher_id"))
            row["actual_strikeouts"] = actual.actual_strikeouts if actual else None
            row["actual_innings_pitched"] = (
                actual.actual_innings_pitched if actual else None
            )

    return {
        "strikeout_projections": cleaned_strikeouts,
        "game_projections": _query_recent(
            db, GameProjections, "date", target_date, limit, tz=tz
        ),
        "projected_hits": _query_recent(
            db, ProjectedHits, "date", target_date, limit, tz=tz
        ),
        "projected_homers": _query_recent(
            db, ProjectedHomers, "date", target_date, limit, tz=tz
        ),
        "home_run_predictions": _query_recent(
            db, Homer, "game_time", target_date, limit, tz=tz
        ),
    }


@router.get("/mlb/accuracy")
def mlb_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day projection accuracy for the AccuracySummary cards.

    Returns three buckets: pitcher_ks_ou (FanDuel-line call accuracy +
    K MAE), projected_hits (success rate for batters projected to get
    hits), and projected_homers (success rate for batters projected to
    hit a HR). `available` is true when any data exists for the date.

    `date` is required — meaningful summaries need a fully-played day.
    """
    from app.services.mlb_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/nba")
def nba_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NBA props: game totals O/U plus points, assists, rebounds, etc."""
    tz = _safe_tz(tz)
    return {
        "totals": _query_recent(
            db, NBATotalsProjections, "game_date", target_date, limit, tz=tz
        ),
        "spreads": _query_recent(
            db, NBASpreadProjections, "game_date", target_date, limit, tz=tz
        ),
        "points": _query_recent(
            db, PointsProjections, "date", target_date, limit, tz=tz
        ),
        "assists": _query_recent(
            db, AssistsProjections, "date", target_date, limit, tz=tz
        ),
        "rebounds": _query_recent(
            db, ReboundsProjections, "date", target_date, limit, tz=tz
        ),
        "three_point": _query_recent(
            db, ThreePointProjections, "date", target_date, limit, tz=tz
        ),
        "steals": _query_recent(
            db, StealsProjections, "date", target_date, limit, tz=tz
        ),
        "blocks": _query_recent(
            db, BlocksProjections, "date", target_date, limit, tz=tz
        ),
        "pra": _query_recent(db, PRAProjections, "date", target_date, limit, tz=tz),
    }


@router.get("/nfl")
def nfl_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NFL props: QB passing/rushing + kicker FG predictions."""
    tz = _safe_tz(tz)
    return {
        "qb_predictions": _query_recent(
            db, QBPredictions, "game_date", target_date, limit, tz=tz
        ),
        "kicker_predictions": _query_recent(
            db, KickerPredictions, "game_date", target_date, limit, tz=tz
        ),
    }


@router.get("/nba/accuracy")
def nba_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day NBA projection accuracy → unified bucket shape."""
    from app.services.nba_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/nfl/accuracy")
def nfl_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day NFL projection accuracy → unified bucket shape."""
    from app.services.nfl_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/nhl")
def nhl_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NHL props: goalie saves, player SOG, game totals O/U."""
    tz = _safe_tz(tz)
    return {
        "goalie_predictions": _query_recent(
            db,
            NHLGoaliePredictions,
            "game_date",
            target_date,
            limit,
            tz=tz,
            dedupe_keys=("goalie_id", "game_date"),
        ),
        "player_shots": _query_recent(
            db,
            NHLPlayerShotsPredictions,
            "game_date",
            target_date,
            limit,
            tz=tz,
            dedupe_keys=("player_id", "game_date"),
        ),
        "team_totals": _query_recent(
            db,
            NHLTeamTotalsPredictions,
            "game_date",
            target_date,
            limit,
            tz=tz,
            dedupe_keys=("home_team_id", "away_team_id", "game_date"),
        ),
    }


@router.get("/nhl/accuracy")
def nhl_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day NHL projection accuracy → unified bucket shape."""
    from app.services.nhl_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/wnba")
def wnba_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """WNBA: totals, spread/win-prob, and player props."""
    tz = _safe_tz(tz)
    return {
        "totals": _query_recent(
            db, WNBATotalsProjections, "game_date", target_date, limit, tz=tz
        ),
        "spreads": _query_recent(
            db, WNBASpreadProjections, "game_date", target_date, limit, tz=tz
        ),
        "points": _query_recent(
            db, WNBAPointsProjections, "date", target_date, limit, tz=tz
        ),
        "assists": _query_recent(
            db, WNBAAssistsProjections, "date", target_date, limit, tz=tz
        ),
        "rebounds": _query_recent(
            db, WNBAReboundsProjections, "date", target_date, limit, tz=tz
        ),
    }


@router.get("/wnba/accuracy")
def wnba_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day WNBA projection accuracy → unified bucket shape."""
    from app.services.wnba_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)
