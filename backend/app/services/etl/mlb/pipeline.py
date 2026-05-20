"""MLB daily pipeline phases (ported from YetiBets mlb_daily_projections.yml).

Projection order matches fixed YetiBets sequence:
  strikeouts → hits → archive K projections → game projections → batter boards → HR ML → weather → blowouts
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta

from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)


def run_projections_phase(target_date: date | None = None) -> dict:
    """Pre-game slate: populate all pred_* MLB tables for ``target_date`` (default today ET)."""
    today = target_date or now_eastern().date()
    results = {}

    from app.services.etl.mlb.strikeouts import run as run_strikeouts

    results["strikeouts"] = run_strikeouts()

    from app.services.etl.mlb.hits import run as run_hits

    results["hits"] = run_hits()

    from app.services.etl.mlb.daily_projection_update import (
        run_store_strikeout_projections,
    )

    results["strikeout_projections"] = run_store_strikeout_projections(today)

    from app.services.etl.mlb.game_projection_pipeline import run_game_projections

    results["game_projections"] = run_game_projections(today)

    from app.services.etl.mlb.daily_batter_projection import run_projections

    results["batter_projections"] = run_projections(today)

    results["hr_predictions"] = _run_hr_predictions_optional()

    from app.services.etl.mlb.weather import run as run_weather

    results["weather"] = run_weather()

    from app.services.etl.mlb.blowouts import run as run_blowouts

    results["blowouts"] = run_blowouts()

    return {
        "status": "ok",
        "date": today.isoformat(),
        "phase": "projections",
        "results": results,
    }


def run_actuals_phase(target_date: date | None = None) -> dict:
    """Post-game: grade yesterday (or ``target_date``) K / game / batter actuals."""
    yesterday = target_date or (now_eastern().date() - timedelta(days=1))
    results = {}

    from app.services.etl.mlb.game_projection_pipeline import run_store_game_actuals

    results["game_actuals"] = run_store_game_actuals(yesterday)

    from app.services.etl.mlb.daily_projection_update import run_store_strikeout_actuals

    results["strikeout_actuals"] = run_store_strikeout_actuals(yesterday)

    from app.services.etl.mlb.daily_batter_projection import run_store_batter_actuals

    results["batter_actuals"] = run_store_batter_actuals(yesterday)

    return {
        "status": "ok",
        "date": yesterday.isoformat(),
        "phase": "actuals",
        "results": results,
    }


def _run_hr_predictions_optional() -> dict:
    model = os.getenv("MLB_HR_MODEL_S3", "s3://yetibets/mlb/hr_model.pkl")
    daily_csv = os.getenv("MLB_DAILY_FEATURES_S3")
    lineup_csv = os.getenv("MLB_LINEUP_CSV_S3")
    if not daily_csv or not lineup_csv:
        logger.info(
            "Skipping HR ML predict_today (set MLB_DAILY_FEATURES_S3 and MLB_LINEUP_CSV_S3)"
        )
        return {"status": "skipped", "reason": "missing_feature_csv_env"}
    from app.services.etl.mlb.dingerParlay.predict_today import predict_and_store

    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        predict_and_store(
            daily_csv,
            lineup_csv,
            model,
            top_n=int(os.getenv("MLB_HR_TOP_N", "50")),
        )
        return {"status": "ok", "model": model}
    finally:
        close_session()
