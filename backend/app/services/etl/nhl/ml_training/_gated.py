"""Champion-gated upload shared by the three NHL trainers.

Shots and goalie saves also pass ``line_col``: the stored betting line is a column of
their feature frame, and the shared promote gate judges the candidate against it."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
from typing import Any

import numpy as np
import pandas as pd

from app.services.ml import model_store
from app.services.ml.promote_gate import format_gate_line, promote_gate, record_outcome
from app.services.ml.upload_to_s3 import live_predictions

logger = logging.getLogger(__name__)


def upload_gated_model(
    s3_prefix: str,
    model_key: str,
    model: Any,
    metadata: dict[str, Any],
    X_hold: pd.DataFrame,
    y_hold: Any,
    line_col: str | None = None,
) -> dict[str, Any]:
    """Upload only if the candidate's holdout MAE is not worse than the live
    model's MAE on that same holdout (live model's own feature list).

    With ``line_col`` the candidate must also pass the promote gate against the line in
    that column of ``X_hold`` (<= 0 means no line). The builders give no game date, so
    every row counts as its own date. The outcome is recorded next to the model;
    a failed gate returns its status without touching the live model."""
    meta_name = f"{model_key}_metadata.json"
    y = np.asarray(y_hold, dtype=float)
    live_pkl, live_meta = f"{s3_prefix}/{model_key}.pkl", f"{s3_prefix}/{meta_name}"

    # None when there is no live model; a live model without usable metadata raises,
    # as for NBA: judging the candidate on the line alone would hide a broken champion.
    champion_pred = live_predictions(live_pkl, live_meta, X_hold)

    def score_champion(live_body: bytes) -> float:
        if champion_pred is None:
            raise ValueError("live predictions unavailable")
        return float(np.mean(np.abs(champion_pred - y)))

    gate = None
    if line_col is not None:
        gate = promote_gate(
            np.asarray(model.predict(X_hold), dtype=float),
            y,
            X_hold[line_col],
            champion_pred=champion_pred,
        )
        logger.info(format_gate_line(f"NHL {model_key}", gate))
        record_outcome(live_pkl, gate, extra={"model_key": model_key})
        if not gate["passes"]:
            return {
                "status": gate["status"],
                "reason": gate["reason"],
                "line_gate": gate,
            }

    return model_store.gated_upload(
        f"{s3_prefix}/{model_key}.pkl",
        pickle.dumps(model),
        candidate_metric=float(metadata["holdout_mae"]),
        metric_name="holdout_mae",
        score_champion=score_champion,
        extra_files={meta_name: json.dumps(metadata, indent=2, default=str).encode()},
        manifest_extra={"model_key": model_key},
        version_prefix=model_key.split("_")[0],
        line_gate=gate,
    )
