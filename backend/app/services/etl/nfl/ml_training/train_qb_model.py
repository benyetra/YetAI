"""Train NFL QB passing yards regressor (+ optional O/U classifier) and upload."""

from __future__ import annotations

import json
import logging
import pickle  # nosec B403 - artifacts written to private bucket only
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import boto3
import pandas as pd

from app.services.etl.nfl.ml_training.build_qb_dataset import build
from app.services.etl.nfl.qb_ou_classifier import (
    MODEL_KEY as OU_MODEL_KEY,
    build_ou_feature_row,
    train_qb_ou_classifier,
)
from app.services.etl.nfl.qb_passing_yards_ml import (
    MODEL_KEY,
    S3_BUCKET,
    S3_PREFIX,
    train_qb_yards_model,
)

logger = logging.getLogger(__name__)

MIN_TRAINING_ROWS = 40
S3_OBJECT_KEY = f"{S3_PREFIX}/{MODEL_KEY}.pkl"
S3_META_KEY = f"{S3_PREFIX}/{MODEL_KEY}_metadata.json"
S3_OU_OBJECT_KEY = f"{S3_PREFIX}/{OU_MODEL_KEY}.pkl"
S3_OU_META_KEY = f"{S3_PREFIX}/{OU_MODEL_KEY}_metadata.json"


def upload_artifact(
    model: Any,
    metadata: dict[str, Any],
    *,
    model_filename: str,
    meta_filename: str,
    s3_model_key: str,
    s3_meta_key: str,
    boto3_module: Any | None = None,
) -> dict[str, str]:
    boto3_mod = boto3_module if boto3_module is not None else boto3
    s3 = boto3_mod.client("s3")
    with tempfile.TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / model_filename
        meta_path = Path(tmpdir) / meta_filename
        with model_path.open("wb") as f:
            pickle.dump(model, f)
        meta_path.write_text(json.dumps(metadata, indent=2, default=str))
        s3.upload_file(str(model_path), S3_BUCKET, s3_model_key)
        s3.upload_file(str(meta_path), S3_BUCKET, s3_meta_key)
        return {"model_key": s3_model_key, "metadata_key": s3_meta_key}


def upload_qb_model(
    model: Any,
    metadata: dict[str, Any],
    *,
    boto3_module: Any | None = None,
) -> dict[str, str]:
    return upload_artifact(
        model,
        metadata,
        model_filename=f"{MODEL_KEY}.pkl",
        meta_filename=f"{MODEL_KEY}_metadata.json",
        s3_model_key=S3_OBJECT_KEY,
        s3_meta_key=S3_META_KEY,
        boto3_module=boto3_module,
    )


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

    model, metadata = train_qb_yards_model((features_df, target))
    result: dict[str, Any] = {
        "status": "ok",
        "metadata": metadata,
        "rows": len(features_df),
    }
    if upload:
        result["s3_keys"] = upload_qb_model(model, metadata)

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
                ou_model, ou_meta = train_qb_ou_classifier(ou_ds[0], ou_ds[1])
                result["ou_classifier"] = {"status": "ok", "metadata": ou_meta}
                if upload:
                    result["ou_classifier"]["s3_keys"] = upload_artifact(
                        ou_model,
                        ou_meta,
                        model_filename=f"{OU_MODEL_KEY}.pkl",
                        meta_filename=f"{OU_MODEL_KEY}_metadata.json",
                        s3_model_key=S3_OU_OBJECT_KEY,
                        s3_meta_key=S3_OU_META_KEY,
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
