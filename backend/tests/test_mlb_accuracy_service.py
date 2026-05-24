"""Tests for mlb_accuracy_service pure compute functions.

The shapes returned here feed the AccuracySummary cards on the MLB
predictions page. We test the maths against synthetic row dicts so the
test suite stays DB-free.
"""

from __future__ import annotations

import pytest

from app.services import mlb_accuracy_service as svc


# ---------------------------------------------------------------------------
# Pitcher K O/U accuracy
# ---------------------------------------------------------------------------


def _strikeout_row(pitcher_id, projected_k, fd_line, fd_ou, actual_k=None):
    return {
        "pitcher_id": pitcher_id,
        "projected_strikeouts": projected_k,
        "fanduel_line": fd_line,
        "fanduel_over_under": fd_ou,
        "actual_strikeouts": actual_k,
    }


def test_strikeout_ou_call_correct_when_over_pick_beats_line():
    """Pick 'over', line 5.5, actual 7 → correct."""
    rows = [_strikeout_row("p1", 6.5, 5.5, "over", actual_k=7.0)]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["total"] == 1
    assert out["correct"] == 1
    assert out["accuracy"] == pytest.approx(1.0)
    assert out["push"] == 0


def test_strikeout_ou_call_wrong_when_over_pick_under_line():
    """Pick 'over', line 5.5, actual 4 → wrong."""
    rows = [_strikeout_row("p1", 7.0, 5.5, "over", actual_k=4.0)]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["correct"] == 0
    assert out["total"] == 1


def test_strikeout_ou_call_under_pick():
    """Pick 'under', line 5.5, actual 4 → correct. Line 5.5 actual 7 → wrong."""
    rows = [
        _strikeout_row("p1", 4.0, 5.5, "under", actual_k=4.0),
        _strikeout_row("p2", 4.5, 5.5, "under", actual_k=7.0),
    ]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["total"] == 2
    assert out["correct"] == 1


def test_strikeout_ou_push_doesnt_count():
    """actual == line → push; not counted as correct or incorrect."""
    rows = [_strikeout_row("p1", 6.0, 6.0, "over", actual_k=6.0)]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["total"] == 0
    assert out["push"] == 1
    assert out["correct"] == 0


def test_strikeout_ou_skips_rows_without_actual():
    """A pitcher without an actual yet doesn't count for or against."""
    rows = [
        _strikeout_row("p1", 6.0, 5.5, "over", actual_k=7.0),
        _strikeout_row("p2", 6.0, 5.5, "over", actual_k=None),
    ]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["total"] == 1
    assert out["correct"] == 1


def test_strikeout_ou_skips_rows_without_line_or_pick():
    rows = [
        _strikeout_row("p1", 6.0, None, "over", actual_k=7.0),
        _strikeout_row("p2", 6.0, 5.5, None, actual_k=7.0),
        _strikeout_row("p3", 6.0, 5.5, "over", actual_k=7.0),
    ]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["total"] == 1


def test_strikeout_ou_mae_averages_absolute_errors_across_rows_with_actuals():
    """MAE = mean(|projected - actual|) over rows where actual exists."""
    rows = [
        _strikeout_row("p1", 6.0, 5.5, "over", actual_k=7.0),  # |6-7| = 1
        _strikeout_row("p2", 4.0, 5.5, "under", actual_k=4.0),  # |4-4| = 0
        _strikeout_row("p3", 5.0, 5.5, "under", actual_k=None),  # skipped
    ]
    out = svc.compute_pitcher_ko_ou(rows)
    assert out["mae"] == pytest.approx(0.5)


def test_strikeout_ou_empty_input():
    out = svc.compute_pitcher_ko_ou([])
    assert out == {
        "total": 0,
        "correct": 0,
        "push": 0,
        "accuracy": None,
        "mae": None,
    }


# ---------------------------------------------------------------------------
# Hits accuracy
# ---------------------------------------------------------------------------


def test_hits_success_rate_actual_hits_at_least_one():
    """A batter we projected for hits is a success if they got at least 1."""
    rows = [
        {"projected_hits": 2, "actual_hits": 1},
        {"projected_hits": 1, "actual_hits": 0},
        {"projected_hits": 1, "actual_hits": 3},
    ]
    out = svc.compute_hits(rows)
    assert out["projected_batters"] == 3
    assert out["hits_made"] == 2
    assert out["success_rate"] == pytest.approx(2 / 3)


def test_hits_ignores_rows_with_zero_projected():
    """Don't count batters we didn't actually project as 'predictions'."""
    rows = [
        {"projected_hits": 0, "actual_hits": 1},
        {"projected_hits": 1, "actual_hits": 1},
    ]
    out = svc.compute_hits(rows)
    assert out["projected_batters"] == 1
    assert out["hits_made"] == 1


def test_hits_empty():
    out = svc.compute_hits([])
    assert out == {
        "projected_batters": 0,
        "hits_made": 0,
        "success_rate": None,
    }


# ---------------------------------------------------------------------------
# HRs accuracy
# ---------------------------------------------------------------------------


def test_homers_success_rate():
    rows = [
        {"projected_homers": 1, "actual_homers": 1},
        {"projected_homers": 1, "actual_homers": 0},
        {"projected_homers": 1, "actual_homers": 0},
        {"projected_homers": 1, "actual_homers": 2},
    ]
    out = svc.compute_homers(rows)
    assert out["projected_batters"] == 4
    assert out["hr_hit"] == 2
    assert out["success_rate"] == pytest.approx(0.5)


def test_homers_skips_rows_without_actuals_recorded():
    """Rows where actual_homers is None (actuals not yet computed) drop out."""
    rows = [
        {"projected_homers": 1, "actual_homers": None},
        {"projected_homers": 1, "actual_homers": 1},
    ]
    out = svc.compute_homers(rows)
    assert out["projected_batters"] == 1
    assert out["hr_hit"] == 1
