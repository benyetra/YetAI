#!/usr/bin/env python3
"""Orchestrate dingerParlay HR training artifact rebuild (offline / admin).

Runs stages in dependency order. Each stage invokes the underlying module CLI.
Paths default under ``MLB_HR_S3_PREFIX`` (``s3://yetibets/mlb/``).

Usage (from backend/):

    PYTHONPATH=. python scripts/mlb_hr_rebuild.py --list-stages
    PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage build-training --season 2024
    PYTHONPATH=. python scripts/mlb_hr_rebuild.py --stage train --holdout-date 2024-07-01
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = BACKEND_ROOT / "scripts" / "mlb_hr_rebuild_manifest.json"
DPKG = "app.services.etl.mlb.dingerParlay"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

STAGES = (
    "download-pa",
    "pitcher-stats",
    "park-factors",
    "build-training",
    "train",
)

# Keys that already exist on s3://yetibets/mlb/ (use for --use-existing-s3)
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
        return Path(uri).is_file()
    try:
        import boto3
        from botocore.exceptions import ClientError

        bucket, key = uri.split("/")[2], "/".join(uri.split("/")[3:])
        boto3.client("s3").head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    except Exception:
        return False


def _require_s3(uri: str, hint: str) -> None:
    if _s3_exists(uri):
        return
    logger.error("Missing S3 object: %s", uri)
    logger.error(hint)
    raise SystemExit(1)


def _resolve_pa_path(season: int, use_existing: bool) -> str:
    if use_existing:
        return _artifact(EXISTING_S3_DEFAULTS["pa"])
    per_season = _artifact(f"historical_pa_{season}.csv")
    if _s3_exists(per_season):
        return per_season
    combined = _artifact(EXISTING_S3_DEFAULTS["pa"])
    if _s3_exists(combined):
        logger.info("Using combined PA file (skip download-pa): %s", combined)
        return combined
    return per_season


def _run_module(module: str, argv: list[str]) -> None:
    cmd = [sys.executable, "-m", module, *argv]
    logger.info("Running: %s", " ".join(cmd))
    subprocess.run(cmd, cwd=str(BACKEND_ROOT), check=True)


def stage_download_pa(season: int) -> dict:
    combined = _artifact(f"historical_pa_{season}.csv")
    out_dir = _prefix()
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
            out_dir,
        ],
    )
    return {"historical_pa": combined, "out_dir": out_dir}


def stage_pitcher_stats(season: int) -> dict:
    out = _artifact("pitcher_stats.csv")
    _run_module(
        f"{DPKG}.compute_pitcher_stats",
        ["--start", str(season), "--end", str(season), "--output", out],
    )
    return {"pitcher_stats": out}


def stage_park_factors(season: int) -> dict:
    out = _artifact("park_factors.csv")
    _run_module(
        f"{DPKG}.download_park_factors",
        ["--season", str(season), "--output", out],
    )
    return {"park_factors": out}


def stage_build_training(season: int, *, use_existing: bool = False) -> dict:
    pa = os.getenv("MLB_HR_PA_S3") or _resolve_pa_path(season, use_existing)
    power = os.getenv("MLB_HR_POWER_SCORES_S3") or _artifact(
        EXISTING_S3_DEFAULTS["power"] if use_existing else "power_scores.csv"
    )
    pitcher = os.getenv("MLB_HR_PITCHER_STATS_S3") or _artifact(
        EXISTING_S3_DEFAULTS["pitcher_stats"] if use_existing else "pitcher_stats.csv"
    )
    park = os.getenv("MLB_HR_PARK_FACTORS_S3") or _artifact(
        EXISTING_S3_DEFAULTS["park_factors"]
    )
    weather = os.getenv("MLB_HR_WEATHER_S3") or _artifact(
        EXISTING_S3_DEFAULTS["weather"]
        if use_existing
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
        _require_s3(path, f"Upload or generate {label} before build-training.")
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
    )
    return {"training_data": out}


def stage_train(
    season: int, holdout_date: str, training_path: str | None = None
) -> dict:
    training = training_path or _artifact(f"training_data_{season}.csv")
    _require_s3(
        training,
        "Run build-training first, e.g.\n"
        f"  python scripts/mlb_hr_rebuild.py --stage build-training --season {season} --use-existing-s3\n"
        "Or set MLB_HR_TRAINING_S3 to an existing training CSV on S3.",
    )
    model_out = os.getenv("MLB_HR_MODEL_S3") or _artifact(EXISTING_S3_DEFAULTS["model"])
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
    )
    return {"model": model_out, "plot": plot}


def main() -> int:
    parser = argparse.ArgumentParser(description="dingerParlay HR rebuild orchestrator")
    parser.add_argument("--list-stages", action="store_true")
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument(
        "--holdout-date",
        default="2024-07-01",
        help="Hold-out split for train stage (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--use-existing-s3",
        action="store_true",
        help="build-training: use large YetiBets artifacts already on S3 (historical_pa.csv, etc.)",
    )
    parser.add_argument(
        "--run-through",
        choices=STAGES,
        metavar="STAGE",
        help="Run this stage and all following stages in order (e.g. build-training → train)",
    )
    parser.add_argument(
        "--training",
        help="Override training CSV for train stage (local path or s3://)",
    )
    args = parser.parse_args()

    if args.list_stages:
        for s in STAGES:
            print(s)
        return 0

    stage = args.run_through or args.stage
    if not stage:
        parser.error("Pass --stage <name>, --run-through <name>, or --list-stages")

    stages_to_run = STAGES[STAGES.index(stage) :]
    started = datetime.now(timezone.utc).isoformat()
    artifacts: dict = {
        "stages": list(stages_to_run),
        "season": args.season,
        "started_at": started,
        "use_existing_s3": args.use_existing_s3,
    }
    training_out: str | None = args.training

    for st in stages_to_run:
        logger.info("=== stage: %s ===", st)
        if st == "download-pa":
            artifacts.update(stage_download_pa(args.season))
        elif st == "pitcher-stats":
            artifacts.update(stage_pitcher_stats(args.season))
        elif st == "park-factors":
            artifacts.update(stage_park_factors(args.season))
        elif st == "build-training":
            built = stage_build_training(args.season, use_existing=args.use_existing_s3)
            artifacts.update(built)
            training_out = built.get("training_data", training_out)
        elif st == "train":
            artifacts.update(
                stage_train(args.season, args.holdout_date, training_path=training_out)
            )

    artifacts["completed_at"] = datetime.now(timezone.utc).isoformat()
    artifacts["status"] = "ok"
    MANIFEST_PATH.write_text(json.dumps(artifacts, indent=2), encoding="utf-8")
    logger.info("Wrote manifest → %s", MANIFEST_PATH)
    print(json.dumps(artifacts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
