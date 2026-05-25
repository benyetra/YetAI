"""Strikeout classifier training data checks and retrain (prod DB)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.services.etl.mlb._db import db_session, init_session, close_session

logger = logging.getLogger(__name__)

DEFAULT_MIN_JOINED = 50


def min_joined_rows() -> int:
    raw = os.getenv("MLB_STRIKEOUT_MIN_JOINED_ROWS", str(DEFAULT_MIN_JOINED))
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_MIN_JOINED


def should_retrain_strikeout_classifier(
    db_counts: dict[str, int] | None = None,
) -> tuple[bool, str]:
    """
    Whether joined projection+actual rows meet the retrain guardrail.

    Returns (ready, reason). Weekly ops: when ready is True, consider
    ``run_retrain_strikeouts`` / Celery ``retrain_strikeout_classifier``.
    """
    counts = db_counts if db_counts is not None else get_strikeout_table_counts()
    joined = int(counts.get("joined", 0))
    minimum = min_joined_rows()
    if joined < minimum:
        return (
            False,
            f"joined={joined} < {minimum} (projections={counts.get('projections', 0)}, "
            f"actuals={counts.get('actuals', 0)})",
        )
    return (
        True,
        f"joined={joined} >= {minimum}; retrain eligible — "
        "scripts/mlb_retrain_strikeouts.py or admin ml-ops/retrain-strikeouts",
    )


def get_strikeout_table_counts() -> dict[str, int]:
    row = (
        db_session.execute(
            text(
                """
            SELECT
              (SELECT COUNT(*) FROM pred_strikeout_projections) AS projections,
              (SELECT COUNT(*) FROM pred_strikeout_actuals) AS actuals,
              (SELECT COUNT(*) FROM pred_strikeout_projections p
                 JOIN pred_strikeout_actuals a
                   ON p.date = a.date AND p.pitcher_id = a.pitcher_id) AS joined
            """
            )
        )
        .mappings()
        .first()
    )
    return {
        "projections": int(row["projections"] or 0),
        "actuals": int(row["actuals"] or 0),
        "joined": int(row["joined"] or 0),
    }


def run_retrain_strikeouts(*, dry_run: bool = False) -> dict[str, Any]:
    """
    Retrain strikeout classifier when joined row count meets threshold.

    Raises RuntimeError with counts when guardrail fails.
    """
    from app.services.etl.mlb.classification_model import (
        MODEL_LOCAL_PATH,
        S3_BUCKET,
        S3_KEY,
        load_training_data,
        train_and_persist,
    )

    init_session()
    try:
        counts = get_strikeout_table_counts()
        minimum = min_joined_rows()
        manifest: dict[str, Any] = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": dry_run,
            "counts": counts,
            "min_joined_required": minimum,
            "model_local": MODEL_LOCAL_PATH,
            "s3_uri": f"s3://{S3_BUCKET}/{S3_KEY}",
        }

        if counts["joined"] < minimum:
            raise RuntimeError(
                f"Strikeout retrain blocked: joined={counts['joined']} "
                f"(need >= {minimum}). projections={counts['projections']} "
                f"actuals={counts['actuals']}. Run daily store_strikeout_projections "
                f"+ store_strikeout_actuals until dates align."
            )

        df = load_training_data()
        if df.empty:
            raise RuntimeError(
                f"Joined count OK ({counts['joined']}) but load_training_data() "
                "returned 0 rows after feature dropna — check thresholds/lines."
            )

        manifest["training_rows"] = int(len(df))

        if dry_run:
            manifest["status"] = "dry_run"
            return manifest

        path = train_and_persist()
        manifest["status"] = "ok"
        manifest["model_path"] = path
        _write_metrics_manifest(manifest)
        return manifest
    finally:
        close_session()


def _write_metrics_manifest(manifest: dict[str, Any]) -> None:
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "mlb_strikeout_retrain_metrics.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Wrote strikeout retrain metrics → %s", path)
