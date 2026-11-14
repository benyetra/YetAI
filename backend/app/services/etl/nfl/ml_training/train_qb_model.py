"""Train NFL QB passing yards regressor (+ optional O/U classifier) and upload."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
from datetime import date
from pathlib import Path
from typing import Any, Callable

import boto3
import numpy as np
import pandas as pd

from app.services.etl.nfl.ml_training.build_qb_dataset import build
from app.services.etl.nfl.qb_features import feature_names as qb_feature_names
from app.services.etl.nfl.qb_ou_classifier import (
    BRIER_METRIC,
    COIN_FLIP_BRIER,
    MODEL_KEY as OU_MODEL_KEY,
    build_ou_feature_row,
    ou_model_feature_order,
    train_qb_ou_classifier,
)
from app.services.etl.nfl.qb_passing_yards_ml import (
    MODEL_KEY,
    S3_BUCKET,
    S3_PREFIX,
    _model_is_residual,
    predict_yards_ml,
    train_qb_yards_model,
)
from app.services.ml import model_store

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 40
S3_OBJECT_KEY = f"{S3_PREFIX}/{MODEL_KEY}.pkl"
S3_META_KEY = f"{S3_PREFIX}/{MODEL_KEY}_metadata.json"
S3_OU_OBJECT_KEY = f"{S3_PREFIX}/{OU_MODEL_KEY}.pkl"
S3_OU_META_KEY = f"{S3_PREFIX}/{OU_MODEL_KEY}_metadata.json"


def _live_metadata(meta_key: str) -> dict[str, Any]:
    raw = model_store.get_bytes(boto3.client("s3"), S3_BUCKET, meta_key)
    if raw is None:
        raise ValueError(f"live metadata {meta_key} missing")
    return json.loads(raw)


def live_yards_scorer(X_hold: pd.DataFrame, y_hold: Any) -> Callable[[bytes], float]:
    """``score_champion``: yards MAE of the live QB model on the candidate holdout
    (raw ML prediction, as the promote eval measures it)."""

    def score(live_body: bytes) -> float:
        meta = _live_metadata(S3_META_KEY)
        live = pickle.loads(live_body)  # nosec B301 - our own private bucket
        order = meta.get("features") or qb_feature_names()
        residual = _model_is_residual(meta)
        mode = str(meta.get("baseline_mode") or "market")
        pred = np.array(
            [
                predict_yards_ml(
                    live,
                    X_hold.iloc[i].to_dict(),
                    feature_order=list(order),
                    residual_target=residual,
                    baseline_mode=mode,
                )
                for i in range(len(X_hold))
            ]
        )
        return float(np.mean(np.abs(pred - np.asarray(y_hold, dtype=float))))

    return score


def live_ou_scorer(X_hold: pd.DataFrame, y_hold: Any) -> Callable[[bytes], float]:
    """``score_champion``: Brier of the live O/U classifier on the candidate holdout."""

    def score(live_body: bytes) -> float:
        meta = _live_metadata(S3_OU_META_KEY)
        live = pickle.loads(live_body)  # nosec B301 - our own private bucket
        X = X_hold.reindex(columns=ou_model_feature_order(meta), fill_value=0.0)
        proba = live.predict_proba(X)[:, 1]
        return float(np.mean((proba - np.asarray(y_hold, dtype=float)) ** 2))

    return score


def _gated(
    model_key: str,
    model: Any,
    metadata: dict[str, Any],
    *,
    candidate_metric: float,
    metric_name: str,
    score_champion: Callable[[bytes], float],
    version_prefix: str,
) -> dict[str, Any]:
    meta_name = f"{model_key.rsplit('.', 1)[0].rsplit('/', 1)[-1]}_metadata.json"
    return model_store.gated_upload(
        model_key,
        pickle.dumps(model),
        candidate_metric=candidate_metric,
        metric_name=metric_name,
        score_champion=score_champion,
        extra_files={meta_name: json.dumps(metadata, indent=2, default=str).encode()},
        manifest_extra={
            "model_key": model_key,
            "data_window": metadata.get("data_window"),
        },
        version_prefix=version_prefix,
    )


def upload_qb_model(
    model: Any,
    metadata: dict[str, Any],
    *,
    candidate_mae: float,
    X_hold: pd.DataFrame,
    y_hold: Any,
) -> dict[str, Any]:
    """Upload only if not worse than the live model on this holdout (yards MAE)."""
    return _gated(
        S3_OBJECT_KEY,
        model,
        metadata,
        candidate_metric=float(candidate_mae),
        metric_name="holdout_mae",
        score_champion=live_yards_scorer(X_hold, y_hold),
        version_prefix="gbm-qb",
    )


def upload_ou_model(
    model: Any,
    metadata: dict[str, Any],
    *,
    X_hold: pd.DataFrame,
    y_hold: Any,
) -> dict[str, Any]:
    """Upload the O/U classifier only if its holdout Brier beats a coin flip and is
    not worse than the live classifier's on the same rows."""
    brier = metadata.get(BRIER_METRIC)
    if brier is None or not float(brier) < COIN_FLIP_BRIER:
        logger.warning("O/U classifier not uploaded: holdout Brier %s >= %s", brier, COIN_FLIP_BRIER)
        return {
            "status": "rejected_coin_flip",
            "metric_name": BRIER_METRIC,
            "candidate_metric": brier,
            "threshold": COIN_FLIP_BRIER,
        }
    return _gated(
        S3_OU_OBJECT_KEY,
        model,
        metadata,
        candidate_metric=float(brier),
        metric_name=BRIER_METRIC,
        score_champion=live_ou_scorer(X_hold, y_hold),
        version_prefix="gbm-ou",
    )


def upload_local_artifacts(
    models_dir: Path, holdout: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Gated upload of the QB yards model and O/U classifier a retrain script just
    wrote to ``models_dir``. ``holdout`` is the sink the script filled:
    ``yards`` (X, y), ``yards_mae``, ``ou`` (X, y). Result is keyed by model key."""
    out: dict[str, dict[str, Any]] = {}

    def _load(key: str) -> tuple[Any, dict[str, Any]] | None:
        pkl = models_dir / f"{key}.pkl"
        if not pkl.is_file():
            return None
        with pkl.open("rb") as f:
            model = pickle.load(f)  # nosec B301 - written by this run
        return model, json.loads((models_dir / f"{key}_metadata.json").read_text())

    if "yards" in holdout and (got := _load(MODEL_KEY)):
        out[MODEL_KEY] = upload_qb_model(
            *got,
            candidate_mae=holdout["yards_mae"],
            X_hold=holdout["yards"][0],
            y_hold=holdout["yards"][1],
        )
    if "ou" in holdout and (got := _load(OU_MODEL_KEY)):
        out[OU_MODEL_KEY] = upload_ou_model(
            *got, X_hold=holdout["ou"][0], y_hold=holdout["ou"][1]
        )
    return out


def _build_ou_training_frame(
    features_df: pd.DataFrame,
    target: pd.Series,
    *,
    session,
    season_start: date,
    season_end: date,
) -> tuple[pd.DataFrame, pd.Series] | None:
    """Join stored ou_line from QBPredictions onto actuals-ordered rows."""
    from app.models.predictions_models import QBActuals, QBPredictions

    rows = (
        session.query(QBActuals)
        .filter(
            QBActuals.game_date >= season_start,
            QBActuals.game_date <= season_end,
        )
        .order_by(QBActuals.season, QBActuals.week)
        .all()
    )
    if len(rows) != len(features_df):
        return None
    ou_rows: list[dict[str, float]] = []
    labels: list[int] = []
    for i, row in enumerate(rows):
        pred = (
            session.query(QBPredictions)
            .filter(
                QBPredictions.qb_player_id == row.qb_player_id,
                QBPredictions.season == row.season,
                QBPredictions.week == row.week,
            )
            .first()
        )
        if pred is None or pred.ou_line is None:
            continue
        line = float(pred.ou_line)
        if line <= 0:
            continue
        actual = float(row.actual_passing_yards)
        if abs(actual - line) < 1e-9:
            continue  # push
        feat_row = features_df.iloc[i].to_dict()
        ou_rows.append(build_ou_feature_row(feat_row, line))
        labels.append(1 if actual > line else 0)
    if len(ou_rows) < 40:
        return None
    return pd.DataFrame(ou_rows), pd.Series(labels, name="over")


def run(
    *,
    season_start: date,
    season_end: date,
    upload: bool = False,
    train_ou: bool = True,
) -> dict[str, Any]:
    features_df, target = build(season_start, season_end)
    if features_df.empty or len(features_df) < MIN_TRAINING_ROWS:
        return {
            "status": "insufficient_data",
            "rows": len(features_df),
            "min_required": MIN_TRAINING_ROWS,
        }

    holdout: dict[str, Any] = {}
    model, metadata = train_qb_yards_model(
        (features_df, target), residual_target=True, holdout_sink=holdout
    )
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if upload:
        result["s3_keys"] = upload_qb_model(
            model,
            metadata,
            candidate_mae=metadata["holdout_mae"],
            X_hold=holdout["X"],
            y_hold=holdout["y"],
        )

    if train_ou:
        try:
            from app.core.database import SessionLocal

            session = SessionLocal()
            try:
                ou_ds = _build_ou_training_frame(
                    features_df,
                    target,
                    session=session,
                    season_start=season_start,
                    season_end=season_end,
                )
            finally:
                session.close()
            if ou_ds is not None:
                ou_holdout: dict[str, Any] = {}
                ou_model, ou_meta = train_qb_ou_classifier(
                    ou_ds[0], ou_ds[1], holdout_sink=ou_holdout
                )
                result["ou_classifier"] = {"status": "ok", "metadata": ou_meta}
                if upload:
                    result["ou_classifier"]["s3_keys"] = upload_ou_model(
                        ou_model,
                        ou_meta,
                        X_hold=ou_holdout["X"],
                        y_hold=ou_holdout["y"],
                    )
            else:
                result["ou_classifier"] = {"status": "insufficient_ou_rows"}
        except Exception as exc:
            logger.info("QB O/U classifier train skipped: %s", exc)
            result["ou_classifier"] = {"status": "skipped", "error": str(exc)}

    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Train NFL QB passing yards ML")
    parser.add_argument("--season-start", type=str, required=True)
    parser.add_argument("--season-end", type=str, required=True)
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--no-ou", action="store_true", help="Skip O/U classifier")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    out = run(
        season_start=date.fromisoformat(args.season_start),
        season_end=date.fromisoformat(args.season_end),
        upload=args.upload,
        train_ou=not args.no_ou,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
