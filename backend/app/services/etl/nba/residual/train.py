"""Train the NBA line-residual model, apply the shared promote gate, upload.

``train`` fits on all but the last 20% of dates, gates the holdout predictions
(``promote_gate``: line evidence, beat the line, beat the live model), then refits on
every row. A model that fails the gate is never uploaded, with or without ``upload``.
"""

from __future__ import annotations

import inspect
import json
import logging
import math
import pickle  # nosec B403 - artifacts written to private bucket only
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.etl.nba.residual import model as residual_model
from app.services.etl.nba.residual.dataset import (
    build_rows,
    feature_columns,
    load_inputs,
)
from app.services.etl.nba.residual.gate import MIN_SLOPE_T
from app.services.ml import model_store, promote_gate, upload_to_s3

logger = logging.getLogger(__name__)

MIN_ROWS = 300
HOLDOUT_FRAC = 0.2
DEFAULT_KIND = inspect.signature(residual_model.fit).parameters["kind"].default


def model_key(stat: str) -> str:
    return f"nba/ml_models/residual_{stat}.pkl"


def _meta_key(stat: str) -> str:
    return model_key(stat).rsplit(".", 1)[0] + "_metadata.json"


def _load_rows(stat: str, start, end) -> pd.DataFrame:
    from app.core import database

    with database.engine.connect() as conn:
        inputs = load_inputs(conn, start, end)
    return build_rows(inputs, stat, start=start, end=end)


def split_holdout(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Last 20% of distinct dates are the holdout; strictly later than the rest."""
    rows = rows.assign(date=pd.to_datetime(rows["date"])).sort_values("date")
    dates = np.sort(rows["date"].unique())
    cut = dates[len(dates) - max(1, math.ceil(len(dates) * HOLDOUT_FRAC))]
    return rows[rows["date"] < cut], rows[rows["date"] >= cut]


def champion_predictions(stat: str, hold: pd.DataFrame, s3=None):
    """The live model's predicted values (line + residual) per holdout row, NaN for
    rows dated on or before its own train_end (it saw those). None when there is no
    live model or no metadata to date it."""
    import boto3

    client = s3 or boto3.client("s3")
    body = model_store.get_bytes(client, upload_to_s3.S3_BUCKET, model_key(stat))
    raw = model_store.get_bytes(client, upload_to_s3.S3_BUCKET, _meta_key(stat))
    if body is None or raw is None:
        return None
    train_end = pd.Timestamp(json.loads(raw)["train_end"])
    out = np.full(len(hold), np.nan)
    later = (pd.to_datetime(hold["date"]) > train_end).to_numpy()
    if later.any():
        live = pickle.loads(body)  # nosec B301 - our own private bucket
        pred, _ = live.predict(hold[later])
        out[later] = hold.loc[later, "line"].to_numpy(dtype=float) + pred
    return out


def _save_local(dirpath, stat: str, mdl, metadata: dict) -> dict:
    d = Path(dirpath)
    d.mkdir(parents=True, exist_ok=True)
    pkl, meta = d / f"residual_{stat}.pkl", d / f"residual_{stat}_metadata.json"
    pkl.write_bytes(pickle.dumps(mdl))
    meta.write_text(json.dumps(metadata, indent=2, default=str))
    return {"model": str(pkl), "metadata": str(meta)}


def train(
    stat: str,
    start,
    end,
    *,
    upload: bool = False,
    kind: str | None = None,
    save_local=None,
    rows: pd.DataFrame | None = None,
    s3=None,
) -> dict:
    kind = kind or DEFAULT_KIND
    if rows is None:
        rows = _load_rows(stat, start, end)
    rows = rows[rows["line"] > 0].reset_index(drop=True)
    if len(rows) < MIN_ROWS:
        return {"status": "insufficient_data", "stat": stat, "n_rows": len(rows)}

    feats = feature_columns()
    fit_df, hold = split_holdout(rows)
    holdout_fit = residual_model.fit(fit_df, feats, kind, stat=stat)
    pred, _ = holdout_fit.predict(hold)
    line = hold["line"].to_numpy(dtype=float)
    champ = champion_predictions(stat, hold, s3) if upload else None
    gate = promote_gate.promote_gate(
        line + pred,
        line + hold["resid"].to_numpy(dtype=float),
        line,
        dates=hold["date"].to_numpy(),
        champion_pred=champ,
        min_slope_t=MIN_SLOPE_T,
    )
    logger.info(promote_gate.format_gate_line(f"NBA residual {stat}", gate))
    holdout_mae = float(np.mean(np.abs(hold["resid"].to_numpy() - pred)))
    line_mae = float(np.mean(np.abs(hold["resid"].to_numpy())))

    final = residual_model.fit(rows, feats, kind, stat=stat)
    last = pd.to_datetime(rows["date"]).max().date().isoformat()
    metadata = {
        "stat": stat,
        "kind": kind,
        "features": feats,
        "n_train": len(rows),
        "data_window": f"{pd.Timestamp(start).date()}..{last}",
        "train_end": last,
        "holdout_gate": gate,
        "holdout_mae": holdout_mae,
        "line_mae": line_mae,
        "n_holdout": len(hold),
        "model_version": final.version,
        "gate_passed": bool(gate["passes"]),
    }
    if not gate["passes"]:
        metadata["status"] = gate["status"]
    result = {
        "status": "dry",
        "stat": stat,
        "kind": kind,
        "n_rows": len(rows),
        "n_holdout": len(hold),
        "holdout_mae": holdout_mae,
        "line_mae": line_mae,
        "gate": gate,
    }
    if save_local:
        result["saved"] = _save_local(save_local, stat, final, metadata)
    if not gate["passes"]:
        result["status"] = gate["status"]
        result["note"] = (
            f"promote gate failed ({gate['reason']}): nothing uploaded"
            if upload
            else f"promote gate failed ({gate['reason']}): --upload would not upload"
        )
    if upload:
        promote_gate.record_outcome(
            model_key(stat),
            gate,
            extra={
                "stat": stat,
                "kind": kind,
                "candidate_version": final.version,
                "data_window": metadata["data_window"],
            },
            s3=s3,
        )
    if not gate["passes"] or not upload:
        return result

    # Same rows for both sides, so gated_upload's strict check agrees with the gate.
    cb = gate["champion"]
    comparable = bool(cb and cb["comparable"])
    out = upload_to_s3.upload_gated_pickle(
        model_key(stat),
        final,
        metadata,
        candidate_metric=cb["candidate_mae"] if comparable else holdout_mae,
        score_champion=lambda _body: cb["champion_mae"] if comparable else float("inf"),
        line_gate=gate,
        version_prefix=kind.replace("_", ""),  # "ridgecv-2026...", not "xgb-"
    )
    result["upload"] = out
    result["status"] = (
        "ok" if out["status"] in ("first_upload", "uploaded") else out["status"]
    )
    if not comparable:
        result["note"] = (
            "champion not comparable (<50 post-train_end rows); line gate is the bar"
        )
    return result
