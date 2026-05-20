"""
Build S3 inputs for dingerParlay HR ML (lineup + daily_features).

Enable with MLB_HR_AUTO_BUILD=1 on the celery-worker. Runs after pred_weather is populated
(weather enrichment phase before HR in the daily pipeline).
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import date

import pandas as pd

from app.services.etl.mlb.classification_model import VENUE_TO_PARK_ID
from app.services.etl.mlb.dingerParlay.daily_features import build_daily_features
from app.services.etl.mlb.dingerParlay.get_lineups import build_today_lineup
from app.services.etl.nba._espn import now_eastern

logger = logging.getLogger(__name__)

_HR_AUTO = ("1", "true", "yes")


def hr_ml_auto_build_enabled() -> bool:
    return os.getenv("MLB_HR_AUTO_BUILD", "").strip().lower() in _HR_AUTO


def hr_ml_enabled() -> bool:
    if hr_ml_auto_build_enabled():
        return True
    return bool(os.getenv("MLB_DAILY_FEATURES_S3") and os.getenv("MLB_LINEUP_CSV_S3"))


def _s3_prefix() -> str:
    prefix = os.getenv("MLB_HR_S3_PREFIX", "s3://yetibets/mlb/").rstrip("/")
    return f"{prefix}/"


def resolve_hr_paths() -> tuple[str, str]:
    prefix = _s3_prefix()
    lineup = os.getenv("MLB_LINEUP_CSV_S3") or f"{prefix}lineups_today.csv"
    daily = os.getenv("MLB_DAILY_FEATURES_S3") or f"{prefix}daily_features_today.csv"
    return lineup, daily


def _static_path(name: str, env_key: str) -> str:
    return os.getenv(env_key) or f"{_s3_prefix()}{name}"


def export_weather_csv_from_db(output_path: str, target_date: date) -> int:
    """Write park_id/game_date weather rows from pred_weather for HR feature merge."""
    from app.models.predictions_models import Weather
    from app.services.etl.mlb._db import db_session
    from app.services.etl.mlb.dingerParlay.daily_features import write_s3_csv

    rows = []
    for w in db_session.query(Weather).all():
        park_id = VENUE_TO_PARK_ID.get(w.venue_name) or VENUE_TO_PARK_ID.get(w.stadium)
        if not park_id:
            continue
        rows.append(
            {
                "park_id": park_id,
                "game_date": target_date.isoformat(),
                "temp": w.temperature,
                "wind_speed": w.wind_speed,
            }
        )

    if not rows:
        logger.warning("No pred_weather rows to export for HR ML")
        return 0

    df = pd.DataFrame(rows)
    if output_path.startswith("s3://"):
        write_s3_csv(df, output_path)
    else:
        df.to_csv(output_path, index=False)
    return len(df)


def build_hr_inputs(target_date: date | None = None) -> dict:
    """
    Build lineup + daily_features CSVs on S3 (or local paths).

    Requires static training artifacts on S3 (power_scores, pitcher_stats, park_factors).
    Weather: today's export from pred_weather, else fallback MLB_HR_WEATHER_S3 static file.
    """
    today = target_date or now_eastern().date()
    lineup_path, daily_path = resolve_hr_paths()

    power_scores = _static_path("power_scores.csv", "MLB_HR_POWER_SCORES_S3")
    pitcher_stats = _static_path("pitcher_stats.csv", "MLB_HR_PITCHER_STATS_S3")
    park_factors = _static_path("park_factors.csv", "MLB_HR_PARK_FACTORS_S3")
    weather_static = _static_path("weather_normalized.csv", "MLB_HR_WEATHER_S3")

    logger.info("Building HR lineup → %s", lineup_path)
    build_today_lineup(lineup_path)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
        weather_today_path = tmp.name
    try:
        n_weather = export_weather_csv_from_db(weather_today_path, today)
        weather_path = weather_today_path if n_weather > 0 else weather_static
        if n_weather <= 0:
            logger.info(
                "Using static weather file %s (pred_weather empty)", weather_static
            )

        logger.info("Building HR daily features → %s", daily_path)
        rows = build_daily_features(
            lineup_path=lineup_path,
            power_scores_path=power_scores,
            pitcher_stats_path=pitcher_stats,
            park_factors_path=park_factors,
            weather_path=weather_path,
            output_path=daily_path,
        )
    finally:
        try:
            os.unlink(weather_today_path)
        except OSError:
            pass

    return {
        "status": "ok",
        "date": today.isoformat(),
        "lineup_path": lineup_path,
        "daily_features_path": daily_path,
        "feature_rows": rows,
    }
