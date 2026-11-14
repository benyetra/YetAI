"""Upload a trained, validated prop model to s3://yetibets/<league>/ml_models/."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
import tempfile
from pathlib import Path
from typing import Any, Callable

import boto3
import numpy as np
import pandas as pd
import xgboost as xgb

from app.services.ml import model_store
from app.services.ml.config import LeagueMLConfig

logger = logging.getLogger(__name__)

S3_BUCKET = "yetibets"


def upload(
    config: LeagueMLConfig,
    stat_col: str,
    model: xgb.XGBRegressor,
    metadata: dict[str, Any],
    *,
    boto3_module: Any | None = None,
) -> dict:
    """Upload xgb_<stat>.pkl + xgb_<stat>_metadata.json. Returns S3 keys written."""
    boto3_mod = boto3_module if boto3_module is not None else boto3
    s3 = boto3_mod.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / f"xgb_{stat_col}.pkl"
        meta_path = Path(tmpdir) / f"xgb_{stat_col}_metadata.json"
        with model_path.open("wb") as f:
            pickle.dump(model, f)
        meta_path.write_text(json.dumps(metadata, indent=2, default=str))

        model_key = f"{config.s3_prefix}/xgb_{stat_col}.pkl"
        meta_key = f"{config.s3_prefix}/xgb_{stat_col}_metadata.json"
        s3.upload_file(str(model_path), S3_BUCKET, model_key)
        s3.upload_file(str(meta_path), S3_BUCKET, meta_key)
        logger.info(
            "uploaded s3://%s/%s and s3://%s/%s",
            S3_BUCKET,
            model_key,
            S3_BUCKET,
            meta_key,
        )
        return {"model_key": model_key, "metadata_key": meta_key}


def upload_spread_model(
    config: LeagueMLConfig,
    model: xgb.XGBRegressor,
    metadata: dict[str, Any],
    *,
    boto3_module: Any | None = None,
) -> dict:
    """Upload spread margin model as xgb_spread.pkl."""
    return upload(config, "spread", model, metadata, boto3_module=boto3_module)


def score_live_mae(
    config: LeagueMLConfig,
    stat_col: str,
    X_hold: pd.DataFrame,
    y_hold: Any,
    *,
    fill: float = 0.0,
) -> Callable[[bytes], float]:
    """``score_champion`` for ``gated_upload``: MAE of the live model on the
    candidate's holdout, using the live model's own feature list (from its
    stored metadata). Features the holdout lacks are filled with ``fill``
    (0 for props, as predict does; NaN for the spread model)."""
    return score_live_pickle(
        f"{config.s3_prefix}/xgb_{stat_col}_metadata.json",
        X_hold,
        y_hold,
        fill=fill,
    )


def score_live_pickle(
    meta_key: str,
    X_hold: pd.DataFrame,
    y_hold: Any,
    *,
    fill: float = 0.0,
) -> Callable[[bytes], float]:
    """``score_champion`` for any pickled regressor whose metadata JSON (at
    ``meta_key``) lists its features. Totals residual models use this too: the
    residual MAE equals the full-total MAE, since actual - (heuristic + pred)
    is the residual target minus the residual prediction."""

    def score(live_body: bytes) -> float:
        raw = model_store.get_bytes(boto3.client("s3"), S3_BUCKET, meta_key)
        if raw is None:
            raise ValueError(f"live metadata {meta_key} missing")
        meta = json.loads(raw)
        feats = meta.get("feature_names") or meta.get("features")
        if not feats:
            raise ValueError("live metadata has no feature list")
        X = pd.DataFrame(
            {f: X_hold[f] if f in X_hold.columns else fill for f in feats},
            index=X_hold.index,
        ).apply(pd.to_numeric, errors="coerce")
        X = X.replace([np.inf, -np.inf], np.nan)
        if not np.isnan(fill):
            X = X.fillna(fill)
        live = pickle.loads(live_body)  # nosec B301 - our own private bucket
        pred = np.asarray(live.predict(X), dtype=float)
        return float(np.mean(np.abs(pred - np.asarray(y_hold, dtype=float))))

    return score


def upload_gated_pickle(
    model_key: str,
    model: Any,
    metadata: dict[str, Any],
    *,
    candidate_metric: float,
    score_champion: Callable[[bytes], float],
    metric_name: str = "holdout_mae",
) -> dict:
    """``upload_gated`` for a model with its own key (``<name>.pkl`` +
    ``<name>_metadata.json``), e.g. the totals residual models."""
    meta_key = f"{model_key.rsplit('.', 1)[0]}_metadata.json"
    out = model_store.gated_upload(
        model_key,
        pickle.dumps(model),
        candidate_metric=candidate_metric,
        metric_name=metric_name,
        score_champion=score_champion,
        extra_files={
            meta_key.rsplit("/", 1)[-1]: json.dumps(
                metadata, indent=2, default=str
            ).encode()
        },
        manifest_extra={"data_window": metadata.get("data_window")},
    )
    if out["status"] != "rejected_by_champion":
        out["metadata_key"] = meta_key
    return out


def upload_gated(
    config: LeagueMLConfig,
    stat_col: str,
    model: xgb.XGBRegressor,
    metadata: dict[str, Any],
    *,
    candidate_metric: float,
    score_champion: Callable[[bytes], float],
    metric_name: str = "holdout_mae",
) -> dict:
    """Like ``upload`` but only replaces the live model if the candidate is
    not worse on the same holdout; archives the live model first.
    Status is one of first_upload / uploaded / rejected_by_champion."""
    out = model_store.gated_upload(
        f"{config.s3_prefix}/xgb_{stat_col}.pkl",
        pickle.dumps(model),
        candidate_metric=candidate_metric,
        metric_name=metric_name,
        score_champion=score_champion,
        extra_files={
            f"xgb_{stat_col}_metadata.json": json.dumps(
                metadata, indent=2, default=str
            ).encode()
        },
        manifest_extra={"stat": stat_col, "data_window": metadata.get("data_window")},
    )
    if out["status"] != "rejected_by_champion":
        out["metadata_key"] = f"{config.s3_prefix}/xgb_{stat_col}_metadata.json"
    return out
