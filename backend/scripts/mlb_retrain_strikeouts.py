#!/usr/bin/env python3
"""Retrain the MLB strikeout over/under classifier and write a metrics manifest.

Usage (from backend/, needs DATABASE_URL + optional AWS for S3 upload):

    PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py
    PYTHONPATH=. python scripts/mlb_retrain_strikeouts.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
METRICS_PATH = BACKEND_ROOT / "scripts" / "mlb_strikeout_retrain_metrics.json"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrain MLB strikeout classifier")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load training data only; do not fit or upload",
    )
    args = parser.parse_args()

    from sqlalchemy import text

    from app.services.etl.mlb._db import db_session
    from app.services.etl.mlb.classification_model import (
        MODEL_LOCAL_PATH,
        S3_BUCKET,
        S3_KEY,
        load_training_data,
        train_and_persist,
    )

    counts = db_session.execute(
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
    ).mappings().first()
    logger.info(
        "Strikeout tables — projections=%s actuals=%s joined=%s",
        counts["projections"],
        counts["actuals"],
        counts["joined"],
    )

    df = load_training_data()
    if df.empty:
        logger.error(
            "No strikeout training rows. Retrain needs joined history in the DB "
            "your DATABASE_URL points at (not S3). "
            "1) Run MLB daily pipeline (strikeouts → store_strikeout_projections). "
            "2) After games, run store_strikeout_actuals (04:30 ET Beat or admin Celery). "
            "3) Repeat over multiple days to accumulate rows. "
            "On Railway: enqueue verify-etl / run_mlb_update_pipeline against prod DB."
        )
        return 1

    manifest = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "training_rows": int(len(df)),
        "model_local": MODEL_LOCAL_PATH,
        "s3_uri": f"s3://{S3_BUCKET}/{S3_KEY}",
        "status": "dry_run" if args.dry_run else "ok",
    }

    if args.dry_run:
        logger.info("Dry run: %s rows available", manifest["training_rows"])
    else:
        path = train_and_persist()
        manifest["model_path"] = path
        logger.info("Retrain complete → %s", path)

    METRICS_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    logger.info("Wrote metrics → %s", METRICS_PATH)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
