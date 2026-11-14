"""Champion-gated upload shared by the three NHL trainers."""

from __future__ import annotations

import json
import pickle  # nosec B403 - artifacts written to private bucket only
from typing import Any

import boto3
import numpy as np
import pandas as pd

from app.services.ml import model_store


def upload_gated_model(
    s3_prefix: str,
    model_key: str,
    model: Any,
    metadata: dict[str, Any],
    X_hold: pd.DataFrame,
    y_hold: Any,
) -> dict[str, Any]:
    """Upload only if the candidate's holdout MAE is not worse than the live
    model's MAE on that same holdout (live model's own feature list)."""
    meta_name = f"{model_key}_metadata.json"

    def score_champion(live_body: bytes) -> float:
        raw = model_store.get_bytes(
            boto3.client("s3"), model_store.BUCKET, f"{s3_prefix}/{meta_name}"
        )
        if raw is None:
            raise ValueError("live metadata missing")
        feats = json.loads(raw).get("features")
        if not feats:
            raise ValueError("live metadata has no feature list")
        X = pd.DataFrame(
            {f: X_hold[f] if f in X_hold.columns else 0.0 for f in feats},
            index=X_hold.index,
        )
        live = pickle.loads(live_body)  # nosec B301 - our own private bucket
        pred = np.asarray(live.predict(X), dtype=float)
        return float(np.mean(np.abs(pred - np.asarray(y_hold, dtype=float))))

    return model_store.gated_upload(
        f"{s3_prefix}/{model_key}.pkl",
        pickle.dumps(model),
        candidate_metric=float(metadata["holdout_mae"]),
        metric_name="holdout_mae",
        score_champion=score_champion,
        extra_files={meta_name: json.dumps(metadata, indent=2, default=str).encode()},
        manifest_extra={"model_key": model_key},
        version_prefix=model_key.split("_")[0],
    )
