#!/usr/bin/env python3
"""Offline NFL QB retrain from nflverse + optional S3 upload + promote gate report.

Usage:
  PYTHONPATH=. python scripts/nfl_retrain_qb_models.py --seasons 2023,2024,2025
  PYTHONPATH=. python scripts/nfl_retrain_qb_models.py --seasons 2023,2024,2025 --upload
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle  # nosec B403 - own artifacts
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_MODELS_DIR = Path(__file__).resolve().parents[1] / "models" / "nfl"
_PROMOTE_LIFT = 0.10  # ML must beat tier MAE by ≥10%


def _mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def _holdout_mask(meta: pd.DataFrame, *, holdout_season: int) -> np.ndarray:
    return (meta["season"] == holdout_season).to_numpy()


def train_and_eval(seasons: list[int]) -> dict[str, Any]:
    from app.services.etl.nfl.ml_training.build_qb_dataset_nflverse import (
        build_from_nflverse,
    )
    from app.services.etl.nfl.qb_ou_classifier import (
        MODEL_KEY as OU_KEY,
        build_ou_feature_row,
        train_qb_ou_classifier,
    )
    from app.services.etl.nfl.qb_passing_yards_ml import (
        MODEL_KEY,
        predict_yards_ml,
        train_qb_yards_model,
    )

    features, target, meta = build_from_nflverse(seasons)
    if features.empty or len(features) < 80:
        return {
            "status": "insufficient_data",
            "rows": int(len(features)),
            "seasons": seasons,
        }

    holdout_season = max(seasons)
    mask = _holdout_mask(meta, holdout_season=holdout_season)
    # If holdout is too small, use last 20% by time order
    if mask.sum() < 40 or (~mask).sum() < 40:
        n = len(features)
        cut = int(n * 0.8)
        train_idx = np.arange(n)[:cut]
        test_idx = np.arange(n)[cut:]
        holdout_label = "time_20pct"
    else:
        train_idx = np.where(~mask)[0]
        test_idx = np.where(mask)[0]
        holdout_label = f"season_{holdout_season}"

    X_train = features.iloc[train_idx].reset_index(drop=True)
    y_train = target.iloc[train_idx].reset_index(drop=True)
    X_test = features.iloc[test_idx]
    y_test = target.iloc[test_idx].to_numpy()
    tier_test = meta.iloc[test_idx]["tier_yards"].to_numpy()

    model, metadata = train_qb_yards_model((X_train, y_train))
    ml_pred = np.array(
        [predict_yards_ml(model, X_test.iloc[i].to_dict()) for i in range(len(X_test))]
    )
    tier_mae = _mae(y_test, tier_test)
    ml_mae = _mae(y_test, ml_pred)
    lift = (tier_mae - ml_mae) / tier_mae if tier_mae > 0 else 0.0
    promote = lift >= _PROMOTE_LIFT

    report: dict[str, Any] = {
        "status": "ok",
        "trained_at": datetime.utcnow().isoformat(),
        "seasons": seasons,
        "rows_total": int(len(features)),
        "rows_train": int(len(X_train)),
        "rows_holdout": int(len(X_test)),
        "holdout": holdout_label,
        "tier_mae": round(tier_mae, 3),
        "ml_mae": round(ml_mae, 3),
        "mae_lift": round(lift, 4),
        "promote_gate": _PROMOTE_LIFT,
        "promote_recommended": promote,
        "model_version": metadata.get("model_version"),
        "train_metadata": metadata,
        "recommendation": (
            "Enable NFL_QB_ML_ENABLED=1 after uploading artifacts"
            if promote
            else "Keep tier-v3 production; ML stays shadow-only"
        ),
    }

    # Synthetic O/U labels from tier±noise as line proxy when market lines absent
    ou_rows = []
    ou_labels = []
    rng = np.random.default_rng(42)
    for i in train_idx:
        feats = features.iloc[i].to_dict()
        actual = float(target.iloc[i])
        # Proxy line near tier with small noise (better than skipping entirely)
        line = float(meta.iloc[i]["tier_yards"]) + float(rng.normal(0, 5))
        if abs(actual - line) < 0.5:
            continue
        ou_rows.append(build_ou_feature_row(feats, line))
        ou_labels.append(1 if actual > line else 0)
    if len(ou_rows) >= 60 and len(set(ou_labels)) > 1:
        ou_model, ou_meta = train_qb_ou_classifier(
            pd.DataFrame(ou_rows), pd.Series(ou_labels)
        )
        report["ou_classifier"] = {"status": "ok", "metadata": ou_meta}
    else:
        ou_model, ou_meta = None, None
        report["ou_classifier"] = {"status": "skipped", "rows": len(ou_rows)}

    _MODELS_DIR.mkdir(parents=True, exist_ok=True)
    yards_path = _MODELS_DIR / f"{MODEL_KEY}.pkl"
    yards_meta_path = _MODELS_DIR / f"{MODEL_KEY}_metadata.json"
    with yards_path.open("wb") as f:
        pickle.dump(model, f)
    # Attach promote decision into metadata for ops
    metadata = {
        **metadata,
        "promote_recommended": promote,
        "holdout_tier_mae": report["tier_mae"],
        "holdout_ml_mae": report["ml_mae"],
        "holdout_mae_lift": report["mae_lift"],
        "training_source": "nflverse_weekly",
        "seasons": seasons,
    }
    yards_meta_path.write_text(json.dumps(metadata, indent=2, default=str))
    report["local_artifacts"] = {
        "model": str(yards_path),
        "metadata": str(yards_meta_path),
    }

    if ou_model is not None and ou_meta is not None:
        ou_path = _MODELS_DIR / f"{OU_KEY}.pkl"
        ou_meta_path = _MODELS_DIR / f"{OU_KEY}_metadata.json"
        with ou_path.open("wb") as f:
            pickle.dump(ou_model, f)
        ou_meta_path.write_text(json.dumps(ou_meta, indent=2, default=str))
        report["local_artifacts"]["ou_model"] = str(ou_path)
        report["local_artifacts"]["ou_metadata"] = str(ou_meta_path)

    report_path = _MODELS_DIR / "qb_retrain_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    report["report_path"] = str(report_path)
    return report


def maybe_upload(report: dict[str, Any]) -> dict[str, Any]:
    import boto3

    from app.services.etl.nfl.qb_ou_classifier import MODEL_KEY as OU_KEY
    from app.services.etl.nfl.qb_ou_classifier import S3_BUCKET, S3_PREFIX
    from app.services.etl.nfl.qb_passing_yards_ml import MODEL_KEY

    s3 = boto3.client("s3")
    uploaded = {}
    mapping = {
        MODEL_KEY: (
            _MODELS_DIR / f"{MODEL_KEY}.pkl",
            _MODELS_DIR / f"{MODEL_KEY}_metadata.json",
        ),
        OU_KEY: (
            _MODELS_DIR / f"{OU_KEY}.pkl",
            _MODELS_DIR / f"{OU_KEY}_metadata.json",
        ),
    }
    for key, (model_path, meta_path) in mapping.items():
        if not model_path.is_file() or not meta_path.is_file():
            continue
        s3.upload_file(str(model_path), S3_BUCKET, f"{S3_PREFIX}/{key}.pkl")
        s3.upload_file(str(meta_path), S3_BUCKET, f"{S3_PREFIX}/{key}_metadata.json")
        uploaded[key] = {
            "model": f"s3://{S3_BUCKET}/{S3_PREFIX}/{key}.pkl",
            "metadata": f"s3://{S3_BUCKET}/{S3_PREFIX}/{key}_metadata.json",
        }
    report["s3_uploaded"] = uploaded
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline NFL QB retrain (nflverse)")
    parser.add_argument(
        "--seasons",
        type=str,
        default="2023,2024,2025",
        help="Comma-separated seasons",
    )
    parser.add_argument("--upload", action="store_true", help="Upload to S3 yetibets")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    seasons = [int(s.strip()) for s in args.seasons.split(",") if s.strip()]
    report = train_and_eval(seasons)
    if args.upload and report.get("status") == "ok":
        try:
            report = maybe_upload(report)
        except Exception as exc:
            report["s3_upload_error"] = str(exc)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
