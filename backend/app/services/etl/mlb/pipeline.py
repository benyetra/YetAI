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

    results["ballpark_pal"] = _run_ballpark_pal_sync(today)

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

    from app.services.etl.mlb.weather import run as run_weather

    results["weather"] = run_weather()

    results["hr_predictions"] = _run_hr_predictions_optional()

    from app.services.etl.mlb.blowouts import run as run_blowouts

    results["blowouts"] = run_blowouts()

    from app.services.etl.mlb.mlb_ev import run as run_mlb_ev

    results["value_bets"] = run_mlb_ev()

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


def _run_ballpark_pal_sync(today: date) -> dict:
    try:
        from app.services.ballpark_pal.sync import sync_ballpark_pal_slate

        return sync_ballpark_pal_slate(today)
    except Exception as exc:
        logger.warning("Ballpark Pal sync failed: %s", exc)
        return {"status": "error", "error": str(exc)}


def _run_hr_predictions_optional() -> dict:
    from app.services.etl.mlb.hr_ml_build import (
        build_hr_inputs,
        hr_ml_auto_build_enabled,
        hr_ml_enabled,
        resolve_hr_paths,
    )

    if not hr_ml_enabled():
        logger.info(
            "Skipping HR ML (set MLB_HR_AUTO_BUILD=1 or MLB_DAILY_FEATURES_S3 + MLB_LINEUP_CSV_S3)"
        )
        return {"status": "skipped", "reason": "hr_ml_disabled"}

    model = os.getenv("MLB_HR_MODEL_S3", "s3://yetibets/mlb/hr_model.pkl")
    lineup_csv, daily_csv = resolve_hr_paths()

    from app.services.etl.mlb.dingerParlay.predict_today import predict_and_store
    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        build_result = None
        if hr_ml_auto_build_enabled():
            build_result = build_hr_inputs()
        stored = predict_and_store(
            daily_csv,
            lineup_csv,
            model,
            top_n=int(os.getenv("MLB_HR_TOP_N", "50")),
        )
        return {
            "status": "ok",
            "model": model,
            "hr_predictions_stored": stored,
            "build": build_result,
        }
    finally:
        close_session()
