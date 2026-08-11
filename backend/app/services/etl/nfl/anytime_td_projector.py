"""NFL anytime-TD projector: feature rows → λ → P(≥1 TD) → DB upsert."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import NFLAnytimeTDPredictions
from app.services.etl.nfl.anytime_td_calibration import (
    MODEL_VERSION_GBM,
    MODEL_VERSION_HIER,
)
from app.services.etl.nfl.anytime_td_model import expected_tds
from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

# Default label when GBM artifact is absent; upserts stamp the applied version.
MODEL_VERSION = MODEL_VERSION_HIER

# Mutable columns on conflict; omit created_at (insert-only) and identity keys.
ANYTIME_TD_UPSERT_UPDATE_KEYS = [
    "game_date",
    "player_name",
    "position",
    "team_name",
    "opponent_team_name",
    "expected_tds",
    "td_probability",
    "confidence_score",
    "features",
    "model_version",
    "prediction_date",
]


def project_prediction_from_features(row: dict[str, Any]) -> dict[str, float | str]:
    """Pure: compute expected TDs and anytime probability from a feature row.

    Applies residual GBM calibration when the artifact is present and enabled.
    ``availability_mult`` (injury) scales λ before probability / calibration.
    """
    from app.services.etl.nfl.anytime_td_calibration import (
        apply_calibrated_probability,
        calibration_enabled,
        load_calibration_model,
    )
    from app.services.etl.nfl.anytime_td_model import anytime_td_probability

    availability = max(0.0, min(1.0, float(row.get("availability_mult") or 1.0)))
    lam = (
        expected_tds(
            team_rz_trips=float(row["team_rz_trips"]),
            player_rz_share=float(row["player_rz_share"]),
            conversion_rate=float(row["conversion_rate"]),
            defense_mult=float(row["defense_mult"]),
            weather_mult=float(row["weather_mult"]),
            script_mult=float(row["script_mult"]),
        )
        * availability
    )
    hier_p = anytime_td_probability(lam)
    enriched = dict(row)
    enriched["expected_tds"] = lam
    enriched["td_probability"] = hier_p

    gbm_applied = False
    td_prob = hier_p
    if calibration_enabled():
        model = load_calibration_model()
        if model is not None:
            td_prob = apply_calibrated_probability(enriched, model=model)
            gbm_applied = True

    return {
        "expected_tds": lam,
        "td_probability": td_prob,
        "model_version": MODEL_VERSION_GBM if gbm_applied else MODEL_VERSION_HIER,
    }


def _resolve_game_date(row: dict[str, Any], *, season: int, week: int) -> date:
    raw = row.get("game_date")
    if isinstance(raw, date):
        return raw
    if raw is not None:
        return date.fromisoformat(str(raw)[:10])
    return date.today()


def _json_safe(value: Any) -> Any:
    """Convert dates/datetimes so JSON/JSONB columns can bind."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def build_upsert_row(
    feature_row: dict[str, Any],
    *,
    season: int,
    week: int,
    now: datetime,
) -> dict[str, Any]:
    """Build a DB upsert dict for ``pred_nfl_anytime_td_predictions``."""
    proj = project_prediction_from_features(feature_row)
    td_prob = proj["td_probability"]
    snap = feature_row.get("snap_pct")
    confidence = min(1.0, float(snap) * td_prob * 1.2) if snap is not None else td_prob

    return {
        "season": season,
        "week": week,
        "game_date": _resolve_game_date(feature_row, season=season, week=week),
        "player_id": feature_row["player_id"],
        "player_name": feature_row["player_name"],
        "position": feature_row["position"],
        "team_name": feature_row["team_name"],
        "opponent_team_name": feature_row["opponent_team_name"],
        "expected_tds": proj["expected_tds"],
        "td_probability": td_prob,
        "confidence_score": confidence,
        # Feature rows carry Python date objects from schedules; JSONB needs ISO strings.
        "features": _json_safe(feature_row),
        "model_version": str(proj.get("model_version") or MODEL_VERSION),
        "prediction_date": now,
        "created_at": now,
    }


def _try_build_feature_rows(season: int, week: int) -> list[dict[str, Any]]:
    """Build feature rows from nflverse weekly/schedules/depth + YAML schemes."""
    from app.services.etl.nfl.anytime_td_features import (
        build_feature_rows_from_nflverse,
    )

    try:
        rows = build_feature_rows_from_nflverse(season, week)
    except Exception as exc:
        # Missing nflverse parquets (early season 404) are expected; avoid
        # traceback spam in Railway while still logging unexpected failures.
        from urllib.error import HTTPError

        if isinstance(exc, HTTPError) and getattr(exc, "code", None) == 404:
            logger.warning(
                "anytime TD feature build skipped — nflverse data not ready "
                "(season=%s week=%s): %s",
                season,
                week,
                exc,
            )
        else:
            logger.exception(
                "anytime TD feature build failed (season=%s week=%s): %s",
                season,
                week,
                exc,
            )
        return []
    logger.info(
        "anytime TD feature rows built: %s (season=%s week=%s)",
        len(rows),
        season,
        week,
    )
    return rows


def run(
    *,
    season: int | None = None,
    week: int | None = None,
    feature_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project anytime-TD probabilities and upsert predictions.

    Pass ``feature_rows`` in tests. When ``feature_rows`` is None, builds rows
    from nflverse weekly/schedules/depth charts plus YAML scheme tags.
    """
    resolved_season = resolve_nfl_season(season)
    resolved_week = week if week is not None else get_current_nfl_week(resolved_season)

    rows = (
        feature_rows
        if feature_rows is not None
        else _try_build_feature_rows(resolved_season, resolved_week)
    )

    if not rows:
        return {
            "status": "ok",
            "predictions": 0,
            "season": resolved_season,
            "week": resolved_week,
        }

    now = datetime.utcnow()
    upsert_rows = [
        build_upsert_row(r, season=resolved_season, week=resolved_week, now=now)
        for r in rows
    ]

    db = SessionLocal()
    try:
        upsert_many(
            db,
            NFLAnytimeTDPredictions,
            upsert_rows,
            conflict_keys=["season", "week", "player_id"],
            update_keys=ANYTIME_TD_UPSERT_UPDATE_KEYS,
        )
        db.commit()
        return {
            "status": "ok",
            "predictions": len(upsert_rows),
            "season": resolved_season,
            "week": resolved_week,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
