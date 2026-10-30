"""NBA player-prop calibration: holdout residuals → P(actual > line).

BKB-2.6 / YetAI-ft6.12. Quintile buckets on projected value; gate when every
populated holdout bucket has |residual_mean| < 0.3. Inference uses bucket
residual mean/std with a normal approximation (fallback: global std).
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

RESIDUAL_MEAN_GATE = 0.3
N_BUCKETS = 5
MIN_BUCKET_ROWS = 5
MIN_RESIDUAL_STD = 0.25


def is_prop_calibration_enabled() -> bool:
    return os.getenv("NBA_PROP_CALIBRATION_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class CalibrationBucket:
    lo: float
    hi: float
    count: int
    residual_mean: float
    residual_std: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CalibrationParams:
    stat: str
    passes_gate: bool
    method: str
    global_residual_mean: float
    global_residual_std: float
    max_abs_bucket_residual_mean: float
    buckets: list[CalibrationBucket] = field(default_factory=list)
    bucket_edges: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stat": self.stat,
            "passes_gate": self.passes_gate,
            "method": self.method,
            "global_residual_mean": self.global_residual_mean,
            "global_residual_std": self.global_residual_std,
            "max_abs_bucket_residual_mean": self.max_abs_bucket_residual_mean,
            "buckets": [b.to_dict() for b in self.buckets],
            "bucket_edges": list(self.bucket_edges),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CalibrationParams:
        buckets = [
            CalibrationBucket(
                lo=float(b["lo"]),
                hi=float(b["hi"]),
                count=int(b["count"]),
                residual_mean=float(b["residual_mean"]),
                residual_std=float(b["residual_std"]),
            )
            for b in data.get("buckets") or []
        ]
        return cls(
            stat=str(data.get("stat", "")),
            passes_gate=bool(data.get("passes_gate")),
            method=str(data.get("method") or "normal"),
            global_residual_mean=float(data.get("global_residual_mean", 0.0)),
            global_residual_std=float(
                data.get("global_residual_std", MIN_RESIDUAL_STD)
            ),
            max_abs_bucket_residual_mean=float(
                data.get("max_abs_bucket_residual_mean", 999.0)
            ),
            buckets=buckets,
            bucket_edges=[float(e) for e in data.get("bucket_edges") or []],
        )


def _unique_quantile_edges(values: np.ndarray, n_buckets: int) -> np.ndarray:
    edges = np.quantile(values, np.linspace(0.0, 1.0, n_buckets + 1))
    edges[0] = float(np.min(values)) - 1e-6
    edges[-1] = float(np.max(values)) + 1e-6
    # Collapse duplicate edges so pd.cut-style buckets stay valid.
    uniq: list[float] = [float(edges[0])]
    for edge in edges[1:]:
        if edge > uniq[-1] + 1e-9:
            uniq.append(float(edge))
        else:
            uniq[-1] = float(edge) + 1e-6
    if len(uniq) < 2:
        mid = float(np.mean(values))
        return np.array([mid - 1.0, mid + 1.0])
    return np.array(uniq)


def fit_residual_calibration(
    stat: str,
    holdout_preds: np.ndarray | list[float],
    holdout_actuals: np.ndarray | list[float],
    holdout_lines: np.ndarray | list[float],
    *,
    n_buckets: int = N_BUCKETS,
    residual_mean_gate: float = RESIDUAL_MEAN_GATE,
) -> CalibrationParams:
    """Fit quintile residual buckets on holdout projections.

    Residual is ``pred - actual`` (positive => model over-predicts).
    ``holdout_lines`` must align row-wise; used only for length validation today
    (line enters at inference via ``p_over_line``).
    """
    preds = np.asarray(holdout_preds, dtype=float)
    actuals = np.asarray(holdout_actuals, dtype=float)
    lines = np.asarray(holdout_lines, dtype=float)
    if not (len(preds) == len(actuals) == len(lines)):
        raise ValueError(
            "holdout_preds, holdout_actuals, holdout_lines must have equal length"
        )
    if len(preds) == 0:
        return CalibrationParams(
            stat=stat,
            passes_gate=False,
            method="normal",
            global_residual_mean=0.0,
            global_residual_std=MIN_RESIDUAL_STD,
            max_abs_bucket_residual_mean=999.0,
        )

    residuals = preds - actuals
    global_mean = float(np.mean(residuals))
    global_std = max(float(np.std(residuals)), MIN_RESIDUAL_STD)

    edges = _unique_quantile_edges(preds, n_buckets)
    buckets: list[CalibrationBucket] = []
    max_abs_mean = 0.0
    gate_buckets_checked = 0

    for i in range(len(edges) - 1):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == len(edges) - 2:
            mask = (preds >= lo) & (preds <= hi)
        else:
            mask = (preds >= lo) & (preds < hi)
        count = int(mask.sum())
        if count == 0:
            buckets.append(
                CalibrationBucket(
                    lo=lo,
                    hi=hi,
                    count=0,
                    residual_mean=global_mean,
                    residual_std=global_std,
                )
            )
            continue
        r = residuals[mask]
        mean_r = float(np.mean(r))
        std_r = max(float(np.std(r)), MIN_RESIDUAL_STD)
        buckets.append(
            CalibrationBucket(
                lo=lo,
                hi=hi,
                count=count,
                residual_mean=mean_r,
                residual_std=std_r,
            )
        )
        if count >= MIN_BUCKET_ROWS:
            gate_buckets_checked += 1
            max_abs_mean = max(max_abs_mean, abs(mean_r))

    passes_gate = gate_buckets_checked > 0 and max_abs_mean < residual_mean_gate

    return CalibrationParams(
        stat=stat,
        passes_gate=passes_gate,
        method="normal",
        global_residual_mean=global_mean,
        global_residual_std=global_std,
        max_abs_bucket_residual_mean=max_abs_mean,
        buckets=buckets,
        bucket_edges=[float(e) for e in edges],
    )


def _pick_bucket(projected: float, params: CalibrationParams) -> CalibrationBucket:
    if not params.buckets:
        return CalibrationBucket(
            lo=-1e9,
            hi=1e9,
            count=0,
            residual_mean=params.global_residual_mean,
            residual_std=params.global_residual_std,
        )
    edges = params.bucket_edges
    if len(edges) >= 2:
        for i in range(len(edges) - 1):
            lo, hi = edges[i], edges[i + 1]
            if i == len(edges) - 2:
                if lo <= projected <= hi:
                    return params.buckets[i]
            elif lo <= projected < hi:
                return params.buckets[i]
    # Fallback: bucket with most rows.
    return max(params.buckets, key=lambda b: b.count)


def p_over_line(projected: float, line: float, params: CalibrationParams) -> float:
    """P(actual > line) using bucket residual mean/std (normal approximation)."""
    if line is None or projected is None:
        return 0.5
    bucket = _pick_bucket(float(projected), params)
    mean_actual = float(projected) - bucket.residual_mean
    std = bucket.residual_std or params.global_residual_std
    std = max(std, MIN_RESIDUAL_STD)
    z = (float(line) - mean_actual) / std
    return float(np.clip(1.0 - _norm_cdf(z), 0.01, 0.99))


def attach_p_over(row: Any, p_over: float | None) -> None:
    """Persist ``p_over`` on ORM rows when ``factors`` JSON or ``p_over`` column exists."""
    if p_over is None:
        return
    if hasattr(row, "factors"):
        existing = getattr(row, "factors", None) or {}
        if not isinstance(existing, dict):
            existing = {}
        existing = dict(existing)
        existing["p_over"] = round(float(p_over), 4)
        row.factors = existing
    elif hasattr(row, "p_over"):
        row.p_over = float(p_over)


def calibration_params_from_metadata(
    metadata: dict[str, Any] | None
) -> CalibrationParams | None:
    if not metadata:
        return None
    raw = metadata.get("prop_calibration")
    if not raw:
        return None
    try:
        return CalibrationParams.from_dict(raw)
    except (TypeError, ValueError, KeyError) as exc:
        logger.warning("Invalid prop_calibration metadata: %s", exc)
        return None


def load_calibration_params(stat: str) -> CalibrationParams | None:
    """Load calibration bundle from NBA XGB metadata (S3/local cache)."""
    try:
        from app.services.etl.nba._ml_predict import get_metadata

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
        line = getattr(row, "fanduel_line", None)
    if line is None:
        return None
    params = load_calibration_params(stat)
    if params is None or not params.passes_gate:
        return None
    p_over = p_over_line(projected, float(line), params)
    attach_p_over(row, p_over)
    return p_over
