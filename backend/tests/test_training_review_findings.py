"""Review-1 findings: gate and step edge cases that used to pass or crash."""

import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from app.services.ml.promote_gate import promote_gate

rng = np.random.default_rng(0)


def _arrays(n=400):
    actual = rng.normal(20, 5, n)
    line = actual + rng.normal(0, 4, n)
    pred = actual + rng.normal(0, 2, n)
    dates = pd.date_range("2026-01-01", periods=n // 10).repeat(10)
    return pred, actual, line, dates


def test_nat_date_does_not_crash_gate():
    pred, actual, line, dates = _arrays()
    dates = pd.Series(dates)
    dates.iloc[3] = pd.NaT  # factorize -> -1 -> bincount raises
    champ = pred + rng.normal(0, 3, len(pred))
    out = promote_gate(pred, actual, line, dates=dates.to_numpy(), champion_pred=champ)
    assert out["status"] in ("pass", "rejected_by_champion")


def test_all_nan_champion_must_not_pass_silently():
    pred, actual, line, dates = _arrays()
    out = promote_gate(
        pred, actual, line, dates=dates, champion_pred=np.full(len(pred), np.nan)
    )
    # Today: status "pass", reason "champion_not_comparable" -> a broken live model
    # (all-NaN predictions) lets any line-beating candidate through the champion check.
    assert out["champion"]["comparable"] is False
    assert not out["passes"] or out["reason"] != "champion_not_comparable"


def test_retrain_step_exit0_without_result_json_is_red(tmp_path):
    """A trainer that exits 0 but prints no result JSON ends the step green."""
    backend = Path(__file__).resolve().parents[1]
    r = subprocess.run(
        ["bash", str(backend / "scripts/retrain_step.sh"), "m", "echo", "hello"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
