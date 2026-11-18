"""Does a model beat the betting line? Pure numpy.

``line_comparison`` is a report (used by the weekly prop retrain); ``beats_line_gate``
is a hard pass/fail for residual models (model predicts actual - line).
"""

from __future__ import annotations

import numpy as np

from app.services.ml.promote_gate import line_comparison  # noqa: F401 (re-export)

MIN_GATE_ROWS = 150
MIN_SLOPE_T = 1.645  # one-sided 95%


def beats_line_gate(
    pred_resid,
    actual,
    line,
    *,
    min_rows: int = MIN_GATE_ROWS,
    min_slope_t: float = MIN_SLOPE_T,
) -> dict:
    """Pass only with enough rows, MAE no worse than the line's, and a positive,
    significant slope. ``pred_resid`` is the predicted actual - line."""
    line_arr = np.asarray(line, dtype=float)
    out = line_comparison(
        line_arr + np.asarray(pred_resid, dtype=float), actual, line_arr
    )
    reasons = []
    if out["n"] < min_rows:
        reasons.append("too_few_rows")
    if not out["beats_line"]:
        reasons.append("worse_than_line")
    slope, t = out["slope"], out["slope_t"]
    if slope is None or t is None or slope <= 0 or t < min_slope_t:
        reasons.append("edge_not_predictive")
    out["failed"] = reasons
    out["passes"] = not reasons
    return out
