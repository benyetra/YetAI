"""WNBA player-prop calibration: holdout residuals → P(actual > line).

Port of ``nba.prop_calibration`` with WNBA env flag and metadata loader.
Supports dict upsert rows (generators) as well as ORM objects.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.services.etl.nba.prop_calibration import (  # noqa: F401 — re-export
    MIN_RESIDUAL_STD,
    N_BUCKETS,
    RESIDUAL_MEAN_GATE,
    CalibrationBucket,
    CalibrationParams,
    calibration_params_from_metadata,
    fit_residual_calibration,
    p_over_line,
)

logger = logging.getLogger(__name__)


def is_prop_calibration_enabled() -> bool:
    return os.getenv("WNBA_PROP_CALIBRATION_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def attach_p_over(row: Any, p_over: float | None) -> None:
    """Persist ``p_over`` on ORM rows or dict upsert payloads via ``factors``."""
    if p_over is None:
        return
    value = round(float(p_over), 4)
    if isinstance(row, dict):
        existing = row.get("factors") or {}
        if not isinstance(existing, dict):
            existing = {}
        existing = dict(existing)
        existing["p_over"] = value
        row["factors"] = existing
        return
    if hasattr(row, "factors"):
        existing = getattr(row, "factors", None) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing = dict(existing)
        existing["p_over"] = value
        row.factors = existing
    if hasattr(row, "p_over"):
        row.p_over = float(p_over)


def load_calibration_params(stat: str) -> CalibrationParams | None:
    """Load calibration bundle from WNBA XGB metadata (S3/local cache)."""
    try:
        from app.services.etl.wnba._ml_predict import get_metadata

        return calibration_params_from_metadata(get_metadata(stat))
    except Exception as exc:
        logger.debug("load_calibration_params(%s): %s", stat, exc)
        return None


def maybe_attach_p_over(
    row: Any,
    *,
    stat: str,
    projected: float,
    line: float | None,
) -> float | None:
    """Compute and attach P(over) when env flag and stable calibration are set."""
    if not is_prop_calibration_enabled():
        return None
    if line is None:
        if isinstance(row, dict):
            line = row.get("market_line")
        else:
            line = getattr(row, "market_line", None)
    if line is None:
        return None
    params = load_calibration_params(stat)
    if params is None or not params.passes_gate:
        return None
    p_over = p_over_line(projected, float(line), params)
    attach_p_over(row, p_over)
    return p_over
