"""One promote gate for every prop trainer: line evidence, beat-the-line, beat-the-champion.

A retrained model goes live only if (a) enough stored lines exist to judge it, (b) it is
no worse than the line on lined holdout rows (small tolerance), and (c) it beats the
current live model by more than holdout noise. Pure numpy; the S3 helpers at the bottom
record the outcome next to the model so a rejection is visible, not silent.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import boto3
import numpy as np
import pandas as pd

from app.services.ml import model_store

GATE_VERSION = "promote-gate-v1"
MIN_LINED_ROWS = 150  # below this the MAE gap to the line is mostly noise
MIN_LINED_DATES = 10  # rows within a day are correlated; need many independent days
LINE_TOLERANCE = 0.005  # 0.5%: a model this close to the line is not "losing" to it
MIN_CHAMPION_ROWS = (
    50  # fewer shared rows than this and the comparison is not meaningful
)
MIN_REL_GAIN = (
    0.005  # must beat the champion by 0.5% of its MAE, however quiet the data
)
NOISE_Z = 1.645  # ... and by this many bootstrap SEs (one-sided 95%)
N_BOOT = 1000  # date-cluster resamples for the gain's standard error

GATE_OUTCOMES = frozenset(
    {
        "rejected_by_champion",
        "rejected_by_line_gate",
        "no_line_evidence",
        "gate_failed",
        "below_baseline",
    }
)
OK_STATUSES = frozenset({"ok", "dry_run", "dry", "first_upload", "uploaded"})

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


def _boot_se(
    gain_rows: np.ndarray, groups: np.ndarray, n_boot: int, seed: int
) -> float:
    """SD of the mean per-row gain over resamples of whole groups (dates)."""
    g = int(groups.max()) + 1
    sums = np.bincount(groups, weights=gain_rows, minlength=g)
    counts = np.bincount(groups, minlength=g).astype(float)
    idx = np.random.default_rng(seed).integers(0, g, size=(n_boot, g))
    return float(np.std(sums[idx].sum(axis=1) / counts[idx].sum(axis=1)))


def _champion_block(p, a, ln, champ, groups, tol, min_rel_gain, noise_z, n_boot, seed):
    rows = np.isfinite(champ)
    n = int(rows.sum())
    out = {
        "comparable": n >= MIN_CHAMPION_ROWS,
        "n": n,
        "champion_mae": None,
        "candidate_mae": None,
        "line_mae": None,
        "gain": None,
        "rel_gain": None,
        "boot_se": None,
        "required_gain": None,
        "below_line": None,
    }
    if n == 0:
        return out
    ae_champ = np.abs(a[rows] - champ[rows])
    ae_cand = np.abs(a[rows] - p[rows])
    champ_mae, cand_mae = float(ae_champ.mean()), float(ae_cand.mean())
    line_mae = float(np.mean(np.abs(a[rows] - ln[rows])))
    out.update(
        champion_mae=champ_mae,
        candidate_mae=cand_mae,
        line_mae=line_mae,
        below_line=champ_mae > line_mae * (1 + tol),
    )
    if not out["comparable"]:
        return out
    gain = champ_mae - cand_mae
    se = _boot_se(ae_champ - ae_cand, groups[rows], n_boot, seed)
    out.update(
        gain=gain,
        rel_gain=gain / champ_mae if champ_mae > 0 else None,
        boot_se=se,
        required_gain=max(min_rel_gain * champ_mae, noise_z * se),
    )
    return out


def promote_gate(
    pred,
    actual,
    line,
    *,
    dates=None,
    champion_pred=None,
    min_slope_t: float | None = None,
    min_rows: int = MIN_LINED_ROWS,
    min_dates: int = MIN_LINED_DATES,
    line_tolerance: float = LINE_TOLERANCE,
    min_rel_gain: float = MIN_REL_GAIN,
    noise_z: float = NOISE_Z,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> dict:
    """Promote only with line evidence, no worse than the line, and a champion-beating gain.

    Arrays are aligned per holdout row; ``line`` NaN or <= 0 means no stored line.
    Checks run in order and the first failure sets ``status``; the champion block is
    filled either way so "both below the line" is on record."""
    p, a, ln = (np.asarray(x, dtype=float) for x in (pred, actual, line))
    ok = np.isfinite(p) & np.isfinite(a) & np.isfinite(ln) & (ln > 0)
    if dates is None:
        groups = np.arange(len(p))  # no dates: every row is its own cluster
    else:
        groups = pd.factorize(pd.Series(np.asarray(dates)))[0]
    n_dates = int(len(np.unique(groups[ok]))) if dates is not None else None

    lined = line_comparison(p, a, ln)
    line_limit = (
        lined["line_mae"] * (1 + line_tolerance)
        if lined["line_mae"] is not None
        else None
    )
    below = bool(lined["model_mae"] > line_limit) if line_limit is not None else None

    champion = champ_below = None
    if champion_pred is not None:
        champ = np.asarray(champion_pred, dtype=float)
        champion = _champion_block(
            p[ok], a[ok], ln[ok], champ[ok], groups[ok],
            line_tolerance, min_rel_gain, noise_z, n_boot, seed,
        )  # fmt: skip
        champ_below = champion["below_line"]

    status, reason = "pass", None
    if lined["n"] < min_rows:
        status, reason = "no_line_evidence", "too_few_lined_rows"
    elif n_dates is not None and n_dates < min_dates:
        status, reason = "no_line_evidence", "too_few_lined_dates"
    elif below:
        status, reason = "rejected_by_line_gate", "worse_than_line"
    elif min_slope_t is not None and (
        lined["slope"] is None
        or lined["slope_t"] is None
        or lined["slope"] <= 0
        or lined["slope_t"] < min_slope_t
    ):
        status, reason = "rejected_by_line_gate", "edge_not_predictive"
    elif champion is not None:
        if not champion["comparable"]:
            reason = "champion_not_comparable"
        elif champion["gain"] < champion["required_gain"]:
            status, reason = "rejected_by_champion", "gain_below_noise"

    return {
        "gate_version": GATE_VERSION,
        "passes": status == "pass",
        "status": status,
        "reason": reason,
        "n_holdout": int(len(p)),
        "n_lined": lined["n"],
        "n_lined_dates": n_dates,
        "lined": lined,
        "line_limit": line_limit,
        "candidate_below_line": below,
        "champion": champion,
        "champion_below_line": champ_below,
        "thresholds": {
            "min_rows": min_rows,
            "min_dates": min_dates,
            "line_tolerance": line_tolerance,
            "min_champion_rows": MIN_CHAMPION_ROWS,
            "min_rel_gain": min_rel_gain,
            "noise_z": noise_z,
            "n_boot": n_boot,
            "min_slope_t": min_slope_t,
        },
    }


def exit_code(status) -> int:
    """0 for a healthy run or an honest gate outcome; 1 for errors and anything unknown."""
    return 0 if status in OK_STATUSES or status in GATE_OUTCOMES else 1


def format_gate_line(label: str, gate: dict) -> str:
    """One log line: line evidence, model vs line, champion comparison, verdict."""

    def f(v, nd=3):
        return "n/a" if v is None else f"{v:.{nd}f}"

    lined, champ = gate.get("lined") or {}, gate.get("champion") or {}
    reason = f" ({gate['reason']})" if gate.get("reason") else ""
    return (
        f"{label} gate: n_lined={gate.get('n_lined')} dates={gate.get('n_lined_dates')}"
        f" model_mae={f(lined.get('model_mae'))} line_mae={f(lined.get('line_mae'))}"
        f" side_hit={f(lined.get('side_hit_rate'))}"
        f" champion_mae={f(champ.get('champion_mae'))} gain={f(champ.get('gain'), 2)}"
        f" required={f(champ.get('required_gain'), 2)} -> {gate.get('status')}{reason}"
    )


def outcome_key(model_key: str) -> str:
    """``nba/ml_models/xgb_points.pkl`` -> ``nba/ml_models/xgb_points_gate.json``."""
    return f"{model_key.removesuffix('.pkl')}_gate.json"


def record_outcome(
    model_key: str,
    gate: dict,
    *,
    extra: dict | None = None,
    bucket: str = model_store.BUCKET,
    s3=None,
) -> str:
    """Write the gate result next to the model. Upload errors propagate on purpose."""
    s3 = s3 or boto3.client("s3")
    key = outcome_key(model_key)
    body = {
        **gate,
        **(extra or {}),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    s3.put_object(Bucket=bucket, Key=key, Body=json.dumps(body, default=str).encode())
    return key


def read_outcome(
    model_key: str, *, bucket: str = model_store.BUCKET, s3=None
) -> dict | None:
    """The last recorded gate outcome for ``model_key``, or None."""
    raw = model_store.get_bytes(
        s3 or boto3.client("s3"), bucket, outcome_key(model_key)
    )
    return json.loads(raw) if raw is not None else None
