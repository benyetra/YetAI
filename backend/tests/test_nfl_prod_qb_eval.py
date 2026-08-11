"""Smoke tests for prod QB eval promote gate constants."""

from scripts.nfl_prod_qb_eval import _PROMOTE_LIFT, _mae
import numpy as np


def test_promote_gate_is_ten_percent():
    assert _PROMOTE_LIFT == 0.10


def test_mae_helper():
    assert abs(_mae(np.array([10.0, 20.0]), np.array([12.0, 18.0])) - 2.0) < 1e-9
