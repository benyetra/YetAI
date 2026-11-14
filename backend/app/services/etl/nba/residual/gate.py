"""Does a model beat the betting line? Pure numpy.

``line_comparison`` is a report (used by the weekly prop retrain); ``beats_line_gate``
is a hard pass/fail for residual models (model predicts actual - line).
"""

from __future__ import annotations

import numpy as np

MIN_GATE_ROWS = 150
MIN_SLOPE_T = 1.645  # one-sided 95%

_EMPTY = {
    "n": 0,
    "model_mae": None,
    "line_mae": None,
    "beats_line": None,
    "slope": None,
    "intercept": None,
    "slope_se": None,
    "slope_t": None,
    "corr": None,
    "side_n": 0,
    "side_hit_rate": None,
}


def line_comparison(pred, actual, line) -> dict:
    """Model vs line on rows where pred, actual and line are finite and line > 0.

    Slope is OLS of (actual - line) on (pred - line): 1 means the model's edge over
    the line is fully realised, 0 means it carries no information. Side hit rate:
    sign(pred - line) vs sign(actual - line), pushes and pred == line excluded."""
    p, a, ln = (np.asarray(x, dtype=float) for x in (pred, actual, line))
    ok = np.isfinite(p) & np.isfinite(a) & np.isfinite(ln) & (ln > 0)
    p, a, ln = p[ok], a[ok], ln[ok]
    out = dict(_EMPTY, n=int(ok.sum()))
    if out["n"] < 2:
        return out
    model_mae = float(np.mean(np.abs(a - p)))
    line_mae = float(np.mean(np.abs(a - ln)))
    x, y = p - ln, a - ln
    out.update(model_mae=model_mae, line_mae=line_mae, beats_line=model_mae <= line_mae)
    sxx = float(np.sum((x - x.mean()) ** 2))
    if sxx > 0:
        slope = float(np.sum((x - x.mean()) * (y - y.mean())) / sxx)
        intercept = float(y.mean() - slope * x.mean())
        resid = y - (intercept + slope * x)
        n = out["n"]
        se = float(np.sqrt(np.sum(resid**2) / (n - 2) / sxx)) if n > 2 else None
        out.update(slope=slope, intercept=intercept, slope_se=se)
        if se:
            out["slope_t"] = slope / se
        if np.std(y) > 0:
            out["corr"] = float(np.corrcoef(x, y)[0, 1])
    side = (x != 0) & (y != 0)
    out["side_n"] = int(side.sum())
    if side.any():
        out["side_hit_rate"] = float(np.mean(np.sign(x[side]) == np.sign(y[side])))
    return out


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
