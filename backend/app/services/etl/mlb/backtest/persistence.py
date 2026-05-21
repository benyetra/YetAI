"""File-based backtest run persistence (YetAI has no Flask backtest tables)."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime
from typing import Any

from app.services.etl.mlb.backtest.report import RUNS_DIR

logger = logging.getLogger(__name__)


def _run_path(backtest_id: str) -> str:
    os.makedirs(RUNS_DIR, exist_ok=True)
    return os.path.join(RUNS_DIR, f"{backtest_id}.json")


def save_run(
    backtest_id: str,
    config: dict[str, Any],
    metrics: dict[str, Any],
    data_quality_summary: dict[str, Any],
    game_results: list[dict[str, Any]],
) -> str:
    payload = {
        "id": backtest_id,
        "run_date": datetime.utcnow().isoformat(),
        "model_version": config.get("model_version"),
        "date_range_start": config.get("start_date"),
        "date_range_end": config.get("end_date"),
        "n_games": config.get("n_games"),
        "seed": config.get("seed"),
        "config": config,
        "metrics": metrics,
        "data_quality_summary": data_quality_summary,
        "game_results": game_results,
    }
    path = _run_path(backtest_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    logger.info("Saved backtest run to %s", path)
    return path


def load_run(compare_id: str) -> dict[str, Any] | None:
    if not os.path.isdir(RUNS_DIR):
        return None
    prefix = compare_id.lower()
    matches = sorted(
        f for f in os.listdir(RUNS_DIR) if f.startswith(prefix) and f.endswith(".json")
    )
    if not matches:
        return None
    path = os.path.join(RUNS_DIR, matches[0])
    with open(path, encoding="utf-8") as f:
        return json.load(f)
