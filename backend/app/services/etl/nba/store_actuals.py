"""Write yesterday's actual per-stat values into the pred_*_actuals tables.

Port of the per-script `store_actuals(date)` helpers scattered across
YetiBets/scripts/nba/*.py (points_predictions_v2, rebounds_predictions_v2,
three_point_projections, steals_predictions_v2, …).

Flow per stat:
  1. Look up yesterday's date (Eastern).
  2. Pull all projections for yesterday from the per-stat projections table.
  3. For each projection, find the matching RecentGames row for that player
     on that date — that's the source of the actual value.
  4. Compute `correct_prediction` from fanduel_line/fanduel_over_under when
     available (points, rebounds, assists, three_pt, PRA).
  5. Upsert into the corresponding pred_*_actuals table.

Returns a per-stat dict of counts so the caller can see at-a-glance which
stats had data and which were missing.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.predictions_models import (
    ActualThreePointMade,
    AssistsActuals,
    AssistsProjections,
    BlocksActuals,
    BlocksProjections,
    FreeThrowActuals,
    FreeThrowPredictions,
    PointsActuals,
    PointsProjections,
    PRAActuals,
    PRAProjections,
    ReboundsActuals,
    ReboundsProjections,
    RecentGames,
    StealsActuals,
    StealsProjections,
    ThreePointProjections,
)
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)


# Per-stat configuration. Each entry describes how to map a projection row +
# a RecentGames row into an actuals row.
#
# Keys:
#   projection_model: source projections table for the stat
#   actuals_model:    target actuals table to upsert into
#   projected_attr:   attribute on the projection holding the projected value
#                     (also used as the actuals row's `projected_<stat>` column)
#   actual_attr:      attribute name on actuals row holding the actual value
#   recent_attr:      attribute on RecentGames holding the actual stat value
#   has_fanduel:      whether the projection carries fanduel_line/over_under
STAT_CONFIG: dict[str, dict[str, Any]] = {
    "points": {
        "projection_model": PointsProjections,
        "actuals_model": PointsActuals,
        "projected_attr": "projected_points",
        "actual_attr": "actual_points",
        "recent_attr": "points",
        "has_fanduel": True,
    },
    "rebounds": {
        "projection_model": ReboundsProjections,
        "actuals_model": ReboundsActuals,
        "projected_attr": "projected_rebounds",
        "actual_attr": "actual_rebounds",
        "recent_attr": "rebounds",
        "has_fanduel": True,
        # Extra columns for rebounds: offensive/defensive splits.
        "extra_actual_attrs": {
            "actual_offensive_rebounds": "offensive_rebounds",
            "actual_defensive_rebounds": "defensive_rebounds",
        },
    },
    "assists": {
        "projection_model": AssistsProjections,
        "actuals_model": AssistsActuals,
        "projected_attr": "projected_assists",
        "actual_attr": "actual_assists",
        "recent_attr": "assists",
        "has_fanduel": True,
    },
    "steals": {
        "projection_model": StealsProjections,
        "actuals_model": StealsActuals,
        "projected_attr": "projected_steals",
        "actual_attr": "actual_steals",
        "recent_attr": "steals",
        "has_fanduel": False,
    },
    "blocks": {
        "projection_model": BlocksProjections,
        "actuals_model": BlocksActuals,
        "projected_attr": "projected_blocks",
        "actual_attr": "actual_blocks",
        "recent_attr": "blocks",
        "has_fanduel": False,
    },
    "free_throw": {
        "projection_model": FreeThrowPredictions,
        "actuals_model": FreeThrowActuals,
        # FreeThrowPredictions uses different column names than the rest.
        "projected_attr": "predicted_free_throws",
        "actuals_projected_attr": "projected_free_throws",
        "actual_attr": "actual_free_throws",
        "recent_attr": "free_throws_made",
        "has_fanduel": False,
    },
    "three_point": {
        "projection_model": ThreePointProjections,
        "actuals_model": ActualThreePointMade,
        "projected_attr": "projected_three_pt_made",
        "actual_attr": "actual_three_pt_made",
        "recent_attr": "three_pt_made",
        "has_fanduel": True,
    },
}


def _compute_correct_prediction(
    projection: Any, actual_value: float, has_fanduel: bool
) -> bool | None:
    """Replicate YetiBets logic: compare actual to fanduel line if available.

    Returns None when no fanduel line/side is recorded on the projection
    (which is the common case in YetAI today).
    """
    if not has_fanduel:
        return None
    line = getattr(projection, "fanduel_line", None)
    over_under = getattr(projection, "fanduel_over_under", None)
    if line is None or not over_under:
        return None
    side = str(over_under).lower()
    try:
        line_value = float(line)
    except (TypeError, ValueError):
        return None
    # YetiBets uses both single-char ('o'/'u') and full ('over'/'under') in
    # different scripts — accept both.
    if side in ("o", "over"):
        return actual_value > line_value
    if side in ("u", "under"):
        return actual_value < line_value
    return None


def _ou_coverage_stats(
    projections: list[Any], *, has_fanduel: bool, graded: int
) -> dict[str, Any]:
    """Summarize how many rows had a line vs were O/U graded."""
    found = len(projections)
    with_line = 0
    if has_fanduel and found:
        for proj in projections:
            line = getattr(proj, "fanduel_line", None)
            ou = getattr(proj, "fanduel_over_under", None)
            if line is not None and ou:
                with_line += 1
    pct = round(100.0 * with_line / found, 1) if found and has_fanduel else None
    graded_pct = round(100.0 * graded / found, 1) if found and has_fanduel else None
    return {
        "projections_with_line": with_line,
        "ou_line_coverage_pct": pct,
        "ou_graded": graded,
        "ou_graded_coverage_pct": graded_pct,
    }


def _store_stat(
    db: Session, stat_key: str, cfg: dict[str, Any], target_date: date
) -> dict[str, int]:
    written = 0
    missing_actual = 0
    no_projection = 0
    errors = 0
    ou_graded = 0

    projections = (
        db.query(cfg["projection_model"])
        .filter(cfg["projection_model"].date == target_date)
        .all()
    )

    if not projections:
        logger.info("store_actuals[%s]: no projections for %s", stat_key, target_date)
        return {
            "written": written,
            "missing_actual": missing_actual,
            "missing_projection": no_projection,
            "errors": errors,
            "projections_found": 0,
        }

    # Pre-fetch yesterday's RecentGames rows for the players we projected so we
    # only touch the table once per stat.
    player_ids = [p.player_id for p in projections]
    recent_rows = (
        db.query(RecentGames)
        .filter(
            RecentGames.game_date == target_date,
            RecentGames.player_id.in_(player_ids),
        )
        .all()
    )
    recent_by_pid = {r.player_id: r for r in recent_rows}

    actuals_model = cfg["actuals_model"]
    recent_attr = cfg["recent_attr"]
    actual_attr = cfg["actual_attr"]
    projected_attr = cfg["projected_attr"]
    # FreeThrow's actuals table uses a different projected_* column name than
    # the predictions table; everything else mirrors itself.
    actuals_projected_attr = cfg.get("actuals_projected_attr", projected_attr)
    extra_actual_attrs: dict[str, str] = cfg.get("extra_actual_attrs", {}) or {}

    for proj in projections:
        try:
            recent = recent_by_pid.get(proj.player_id)
            if recent is None:
                missing_actual += 1
                continue
            actual_value = getattr(recent, recent_attr, None)
            if actual_value is None:
                missing_actual += 1
                continue

            projected_value = getattr(proj, projected_attr, None)
            correct = _compute_correct_prediction(
                proj, float(actual_value), cfg["has_fanduel"]
            )
            if correct is not None:
                ou_graded += 1

            existing = (
                db.query(actuals_model)
                .filter(
                    actuals_model.date == target_date,
                    actuals_model.player_id == proj.player_id,
                )
                .first()
            )

            if existing:
                setattr(existing, actual_attr, float(actual_value))
                if projected_value is not None:
                    setattr(existing, actuals_projected_attr, float(projected_value))
                existing.player_name = getattr(
                    proj, "player_name", existing.player_name
                )
                existing.opponent_team_name = getattr(
                    proj, "opponent_team_name", existing.opponent_team_name
                )
                existing.correct_prediction = correct
                for col, recent_col in extra_actual_attrs.items():
                    val = getattr(recent, recent_col, None)
                    setattr(existing, col, float(val) if val is not None else None)
            else:
                kwargs: dict[str, Any] = {
                    "date": target_date,
                    "player_id": proj.player_id,
                    "player_name": getattr(proj, "player_name", None),
                    "opponent_team_name": getattr(proj, "opponent_team_name", None),
                    actual_attr: float(actual_value),
                    "correct_prediction": correct,
                }
                if projected_value is not None:
                    kwargs[actuals_projected_attr] = float(projected_value)
                else:
                    # Some actuals tables require projected_* NOT NULL
                    # (PointsActuals, FreeThrowActuals). Default to 0.0 in that
                    # case to avoid IntegrityError.
                    column = actuals_model.__table__.columns.get(actuals_projected_attr)
                    if column is not None and not column.nullable:
                        kwargs[actuals_projected_attr] = 0.0
                for col, recent_col in extra_actual_attrs.items():
                    val = getattr(recent, recent_col, None)
                    kwargs[col] = float(val) if val is not None else None
                db.add(actuals_model(**kwargs))

            db.commit()
            written += 1
        except Exception:
            logger.exception(
                "store_actuals[%s]: failed for player_id=%s",
                stat_key,
                getattr(proj, "player_id", "?"),
            )
            db.rollback()
            errors += 1
            continue

    result = {
        "written": written,
        "missing_actual": missing_actual,
        "missing_projection": no_projection,
        "errors": errors,
        "projections_found": len(projections),
    }
    result.update(
        _ou_coverage_stats(
            projections, has_fanduel=cfg["has_fanduel"], graded=ou_graded
        )
    )
    if cfg["has_fanduel"] and projections:
        logger.info(
            "store_actuals[%s]: ou_line_coverage=%s%% ou_graded=%s/%s",
            stat_key,
            result.get("ou_line_coverage_pct"),
            ou_graded,
            len(projections),
        )
    return result


def _store_pra(db: Session, target_date: date) -> dict[str, int]:
    """PRA actuals = points + rebounds + assists from RecentGames."""
    written = 0
    missing_actual = 0
    errors = 0
    ou_graded = 0

    projections = (
        db.query(PRAProjections).filter(PRAProjections.date == target_date).all()
    )
    if not projections:
        return {
            "written": 0,
            "missing_actual": 0,
            "errors": 0,
            "projections_found": 0,
        }

    player_ids = [p.player_id for p in projections]
    recent_rows = (
        db.query(RecentGames)
        .filter(
            RecentGames.game_date == target_date,
            RecentGames.player_id.in_(player_ids),
        )
        .all()
    )
    recent_by_pid = {r.player_id: r for r in recent_rows}

    for proj in projections:
        try:
            recent = recent_by_pid.get(proj.player_id)
            if recent is None:
                missing_actual += 1
                continue
            ap = recent.points or 0
            ar = recent.rebounds or 0
            aa = recent.assists or 0
            actual_pra = float(ap + ar + aa)
            correct = _compute_correct_prediction(
                proj, actual_pra, bool(proj.fanduel_line)
            )
            if correct is not None:
                ou_graded += 1
            existing = (
                db.query(PRAActuals)
                .filter(
                    PRAActuals.date == target_date,
                    PRAActuals.player_id == proj.player_id,
                )
                .first()
            )
            payload = {
                "player_name": proj.player_name,
                "opponent_team_name": proj.opponent_team_name,
                "actual_points": float(ap),
                "actual_rebounds": float(ar),
                "actual_assists": float(aa),
                "actual_pra": actual_pra,
                "projected_pra": proj.projected_pra,
                "prediction_error": actual_pra - proj.projected_pra,
                "correct_prediction": correct,
            }
            if existing:
                for k, v in payload.items():
                    setattr(existing, k, v)
            else:
                db.add(
                    PRAActuals(
                        date=target_date,
                        player_id=proj.player_id,
                        **payload,
                    )
                )
            db.commit()
            written += 1
        except Exception:
            logger.exception(
                "store_actuals[pra]: failed for player_id=%s", proj.player_id
            )
            db.rollback()
            errors += 1

    result = {
        "written": written,
        "missing_actual": missing_actual,
        "errors": errors,
        "projections_found": len(projections),
    }
    result.update(_ou_coverage_stats(projections, has_fanduel=True, graded=ou_graded))
    if projections:
        logger.info(
            "store_actuals[pra]: ou_line_coverage=%s%% ou_graded=%s/%s",
            result.get("ou_line_coverage_pct"),
            ou_graded,
            len(projections),
        )
    return result


def run(target_date: date | None = None) -> dict:
    """Run store_actuals for every configured stat.

    target_date defaults to yesterday (Eastern). Override is useful for
    backfills.
    """
    if target_date is None:
        target_date = (now_eastern() - timedelta(days=1)).date()

    summary: dict[str, Any] = {
        "status": "ok",
        "date": target_date.isoformat(),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "stats": {},
    }

    db = SessionLocal()
    try:
        for stat_key, cfg in STAT_CONFIG.items():
            summary["stats"][stat_key] = _store_stat(db, stat_key, cfg, target_date)
            logger.info("store_actuals[%s]: %s", stat_key, summary["stats"][stat_key])
        summary["stats"]["pra"] = _store_pra(db, target_date)
        logger.info("store_actuals[pra]: %s", summary["stats"]["pra"])
    finally:
        db.close()

    return summary
