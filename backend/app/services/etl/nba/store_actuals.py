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
from app.services.etl.grading_window import grading_dates
from app.services.etl.nba._espn import NBA_TEAM_NAMES

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


def opponent_matches(proj: Any, recent: Any) -> bool:
    """False when the box row's opponent is not the one the projection was made for.

    A projection without an opponent name, or a box opponent id we cannot name,
    is not blocked.
    """
    name = getattr(proj, "opponent_team_name", None)
    box_name = NBA_TEAM_NAMES.get(getattr(recent, "opponent_team_id", None))
    if not name or not box_name:
        return True
    return str(name).strip().lower() == box_name.lower()


def pra_value(recent: Any) -> float | None:
    parts = (recent.points, recent.rebounds, recent.assists)
    return None if any(v is None for v in parts) else float(sum(parts))


# PRA is graded from three box columns; it has no STAT_CONFIG entry.
PRA_CONFIG: dict[str, Any] = {
    "projection_model": PRAProjections,
    "actuals_model": PRAActuals,
    "actual_attr": "actual_pra",
    "value_fn": pra_value,
}
GRADED_STATS = [*STAT_CONFIG, "pra"]


def _value_fn(cfg: dict[str, Any]):
    return cfg.get("value_fn") or (lambda r: getattr(r, cfg["recent_attr"], None))


def resolve_actuals(
    db: Session, cfg: dict[str, Any], target_date: date
) -> tuple[list[Any], list[tuple[Any, Any, float]], list[Any]]:
    """The one rule for what the actuals of a date must be.

    Returns (projections, matches, stale): ``matches`` are (projection, box row,
    value) where the player has a box row with a value and the opponent agrees;
    ``stale`` are existing actual rows that must not exist (no matching box row,
    or an orphan with neither projection nor box row).
    """
    projections = (
        db.query(cfg["projection_model"])
        .filter(cfg["projection_model"].date == target_date)
        .all()
    )
    box = {
        r.player_id: r
        for r in db.query(RecentGames)
        .filter(RecentGames.game_date == target_date)
        .all()
    }
    value_fn = _value_fn(cfg)
    matches = []
    for proj in projections:
        recent = box.get(proj.player_id)
        value = value_fn(recent) if recent is not None else None
        if value is not None and opponent_matches(proj, recent):
            matches.append((proj, recent, value))
    keep = {p.player_id for p, _, _ in matches}
    projected = {p.player_id for p in projections}
    actuals_model = cfg["actuals_model"]
    stale = [
        a
        for a in db.query(actuals_model).filter(actuals_model.date == target_date).all()
        if a.player_id not in keep
        and (a.player_id in projected or a.player_id not in box)
    ]
    return projections, matches, stale


def _delete_rows(db: Session, rows: list[Any]) -> int:
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)


def _store_stat(
    db: Session, stat_key: str, cfg: dict[str, Any], target_date: date
) -> dict[str, int]:
    written = 0
    no_projection = 0
    errors = 0
    ou_graded = 0

    projections, matches, stale = resolve_actuals(db, cfg, target_date)
    deleted = _delete_rows(db, stale)
    missing_actual = len(projections) - len(matches)

    if not projections:
        logger.info("store_actuals[%s]: no projections for %s", stat_key, target_date)
        return {
            "written": written,
            "missing_actual": missing_actual,
            "missing_projection": no_projection,
            "errors": errors,
            "projections_found": 0,
            "deleted": deleted,
        }

    actuals_model = cfg["actuals_model"]
    actual_attr = cfg["actual_attr"]
    projected_attr = cfg["projected_attr"]
    # FreeThrow's actuals table uses a different projected_* column name than
    # the predictions table; everything else mirrors itself.
    actuals_projected_attr = cfg.get("actuals_projected_attr", projected_attr)
    extra_actual_attrs: dict[str, str] = cfg.get("extra_actual_attrs", {}) or {}

    for proj, recent, actual_value in matches:
        try:
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
        "deleted": deleted,
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
    """PRA actuals = points + rebounds + assists from RecentGames (all three non-null)."""
    written = 0
    missing_actual = 0
    errors = 0
    ou_graded = 0

    projections, matches, stale = resolve_actuals(db, PRA_CONFIG, target_date)
    deleted = _delete_rows(db, stale)
    missing_actual = len(projections) - len(matches)
    if not projections:
        return {
            "written": 0,
            "missing_actual": 0,
            "errors": 0,
            "projections_found": 0,
            "deleted": deleted,
        }

    for proj, recent, actual_pra in matches:
        try:
            ap, ar, aa = recent.points, recent.rebounds, recent.assists
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
        "deleted": deleted,
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


def plan_counts(db: Session, stat_key: str, target_date: date) -> dict[str, int]:
    """Read-only: what storing ``stat_key`` for the date would change."""
    cfg = PRA_CONFIG if stat_key == "pra" else STAT_CONFIG[stat_key]
    _, matches, stale = resolve_actuals(db, cfg, target_date)
    model = cfg["actuals_model"]
    existing = {
        a.player_id: a for a in db.query(model).filter(model.date == target_date)
    }
    counts = {"updated": 0, "deleted": len(stale), "inserted": 0, "unchanged": 0}
    for proj, _, value in {m[0].player_id: m for m in matches}.values():
        row = existing.get(proj.player_id)
        if row is None:
            counts["inserted"] += 1
        elif getattr(row, cfg["actual_attr"]) != float(value):
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    return counts


def store_date(db: Session, target_date: date) -> dict[str, Any]:
    """Store every stat (and PRA) for one date on an open session."""
    stats = {k: _store_stat(db, k, c, target_date) for k, c in STAT_CONFIG.items()}
    stats["pra"] = _store_pra(db, target_date)
    return stats


def run(target_date: date | None = None) -> dict:
    """Run store_actuals for every configured stat.

    target_date=None re-grades ``grading_dates("nba")`` (upserts, so a partial
    night heals); the summary reports the newest date. Pass a date for a backfill.
    """
    dates = [target_date] if target_date else grading_dates("nba")

    summary: dict[str, Any] = {
        "status": "ok",
        "date": dates[-1].isoformat(),
        "dates": [d.isoformat() for d in dates],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "stats": {},
    }

    db = SessionLocal()
    try:
        for d in dates:
            stats = store_date(db, d)
            for stat_key, res in stats.items():
                logger.info("store_actuals[%s] %s: %s", stat_key, d, res)
            summary["stats"] = stats
    finally:
        db.close()

    return summary
