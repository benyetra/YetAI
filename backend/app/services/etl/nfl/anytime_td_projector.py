"""NFL anytime-TD projector: feature rows → λ → P(≥1 TD) → DB upsert."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import NFLAnytimeTDPredictions
from app.services.etl.nfl.anytime_td_model import anytime_td_probability, expected_tds
from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

MODEL_VERSION = "hierarchical_v1"

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


def project_prediction_from_features(row: dict[str, Any]) -> dict[str, float]:
    """Pure: compute expected TDs and anytime probability from a feature row."""
    lam = expected_tds(
        team_rz_trips=float(row["team_rz_trips"]),
        player_rz_share=float(row["player_rz_share"]),
        conversion_rate=float(row["conversion_rate"]),
        defense_mult=float(row["defense_mult"]),
        weather_mult=float(row["weather_mult"]),
        script_mult=float(row["script_mult"]),
    )
    return {
        "expected_tds": lam,
        "td_probability": anytime_td_probability(lam),
    }


def _resolve_game_date(row: dict[str, Any], *, season: int, week: int) -> date:
    raw = row.get("game_date")
    if isinstance(raw, date):
        return raw
    if raw is not None:
        return date.fromisoformat(str(raw))
    return date.today()


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
        "features": feature_row,
        "model_version": MODEL_VERSION,
        "prediction_date": now,
        "created_at": now,
    }


def _try_build_feature_rows(season: int, week: int) -> list[dict[str, Any]]:
    """Attempt nflverse-backed feature build; empty until hooks are wired."""
    from app.services.etl.nfl.anytime_td_features import fetch_player_usage_nflverse

    try:
        fetch_player_usage_nflverse(season=season, week=week)
    except NotImplementedError:
        logger.info(
            "anytime TD feature fetch not wired (season=%s week=%s); skipping",
            season,
            week,
        )
        return []
    return []


def run(
    *,
    season: int | None = None,
    week: int | None = None,
    feature_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project anytime-TD probabilities and upsert predictions.

    Pass ``feature_rows`` in tests or when nflverse ETL is unavailable.
    When ``feature_rows`` is None, attempts the real nflverse path (may return
    zero rows until feature fetch is implemented).
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
