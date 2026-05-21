"""dingerParlay HR rebuild stages (callable from Celery or CLI)."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DPKG = "app.services.etl.mlb.dingerParlay"

STAGES = (
    "download-pa",
    "pitcher-stats",
    "park-factors",
    "build-training",
    "train",
)

EXISTING_S3_DEFAULTS = {
    "pa": "historical_pa.csv",
    "power": "power_scores_all.csv",
    "pitcher_stats": "pitcher_stats_all.csv",
    "park_factors": "park_factors.csv",
    "weather": "weather_normalized_full.csv",
    "model": "hr_model.pkl",
}


def _prefix() -> str:
    return os.getenv("MLB_HR_S3_PREFIX", "s3://yetibets/mlb/").rstrip("/") + "/"


def _artifact(name: str) -> str:
    return f"{_prefix()}{name}"


def _s3_exists(uri: str) -> bool:
    if not uri.startswith("s3://"):
        from pathlib import Path

        return Path(uri).is_file()
    import boto3
    from botocore.exceptions import ClientError

    bucket, key = uri.split("/")[2], "/".join(uri.split("/")[3:])
    try:
        boto3.client("s3").head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _require_s3(uri: str, label: str) -> None:
    if _s3_exists(uri):
        return
    raise RuntimeError(f"Missing S3 object for {label}: {uri}")


def _resolve_pa_path(season: int, use_existing: bool) -> str:
    if use_existing:
        return _artifact(EXISTING_S3_DEFAULTS["pa"])
    per_season = _artifact(f"historical_pa_{season}.csv")
    if _s3_exists(per_season):
        return per_season
    combined = _artifact(EXISTING_S3_DEFAULTS["pa"])
    if _s3_exists(combined):
        return combined
    return per_season


def _run_module(module: str, argv: list[str], backend_root: str) -> None:
    cmd = [sys.executable, "-m", module, *argv]
    logger.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, cwd=backend_root, check=True)


def run_hr_rebuild_stage(
    stage: str,
    *,
    season: int = 2024,
    holdout_date: str = "2024-07-01",
    use_existing_s3: bool = False,
    training_path: str | None = None,
    backend_root: str | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown stage {stage!r}; choose from {STAGES}")

    root = backend_root or os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )
    started = datetime.now(timezone.utc).isoformat()
    artifacts: dict[str, Any] = {
        "stage": stage,
        "season": season,
        "started_at": started,
        "use_existing_s3": use_existing_s3,
    }

    if stage == "download-pa":
        combined = _artifact(f"historical_pa_{season}.csv")
        _run_module(
            f"{DPKG}.download_historical_pa",
            [
                "--start-year",
                str(season),
                "--end-year",
                str(season),
                "--combined",
                combined,
                "--out-dir",
                _prefix(),
            ],
            root,
        )
        artifacts["historical_pa"] = combined
    elif stage == "pitcher-stats":
        out = _artifact("pitcher_stats.csv")
        _run_module(
            f"{DPKG}.compute_pitcher_stats",
            ["--start", str(season), "--end", str(season), "--output", out],
            root,
        )
        artifacts["pitcher_stats"] = out
    elif stage == "park-factors":
        out = _artifact("park_factors.csv")
        _run_module(
            f"{DPKG}.download_park_factors",
            ["--season", str(season), "--output", out],
            root,
        )
        artifacts["park_factors"] = out
    elif stage == "build-training":
        pa = os.getenv("MLB_HR_PA_S3") or _resolve_pa_path(season, use_existing_s3)
        power = os.getenv("MLB_HR_POWER_SCORES_S3") or _artifact(
            EXISTING_S3_DEFAULTS["power"] if use_existing_s3 else "power_scores.csv"
        )
        pitcher = os.getenv("MLB_HR_PITCHER_STATS_S3") or _artifact(
            EXISTING_S3_DEFAULTS["pitcher_stats"]
            if use_existing_s3
            else "pitcher_stats.csv"
        )
        park = os.getenv("MLB_HR_PARK_FACTORS_S3") or _artifact(
            EXISTING_S3_DEFAULTS["park_factors"]
        )
        weather = os.getenv("MLB_HR_WEATHER_S3") or _artifact(
            EXISTING_S3_DEFAULTS["weather"]
            if use_existing_s3
            else "weather_normalized_full.csv"
        )
        out = _artifact(f"training_data_{season}.csv")
        for label, path in (
            ("PA", pa),
            ("power", power),
            ("pitcher_stats", pitcher),
            ("park_factors", park),
            ("weather", weather),
        ):
            _require_s3(path, label)
        _run_module(
            f"{DPKG}.build_training_data",
            [
                "--pa",
                pa,
                "--power",
                power,
                "--pitcher_stats",
                pitcher,
                "--park_factors",
                park,
                "--weather",
                weather,
                "--output",
                out,
            ],
            root,
        )
        artifacts["training_data"] = out
    elif stage == "train":
        training = training_path or _artifact(f"training_data_{season}.csv")
        _require_s3(
            training,
            "training CSV (run build-training first or set MLB_HR_TRAINING_S3)",
        )
        model_out = os.getenv("MLB_HR_MODEL_S3") or _artifact(
            EXISTING_S3_DEFAULTS["model"]
        )
        plot = _artifact(f"hr_model_importance_{season}.png")
        _run_module(
            f"{DPKG}.train_hr_model",
            [
                "--training",
                training,
                "--output",
                model_out,
                "--holdout-date",
                holdout_date,
                "--plot-path",
                plot,
            ],
            root,
        )
        artifacts["model"] = model_out
        artifacts["plot"] = plot

    artifacts["completed_at"] = datetime.now(timezone.utc).isoformat()
    artifacts["status"] = "ok"
    return artifacts
