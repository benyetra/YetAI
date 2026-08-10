"""Offline regression gates for NFL anytime-TD quick backtest (no network/DB)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.etl.nfl.anytime_td_backtest import (
    DEFAULT_GATE_BASELINES,
    DEFAULT_METRICS_PATH,
    QUICK_SYNTHETIC_ROWS,
    compute_brier_score,
    compute_metrics,
    passes_gate,
    run_quick_backtest,
    score_synthetic_rows,
)

FIXTURE_METRICS = DEFAULT_METRICS_PATH


def test_compute_brier_score_on_fixed_rows():
    rows = [
        {"td_probability": 0.6, "scored_anytime_td": True},
        {"td_probability": 0.2, "scored_anytime_td": False},
    ]
    brier, n = compute_brier_score(rows)
    assert n == 2
    assert brier == pytest.approx((0.4**2 + 0.2**2) / 2)


def test_compute_metrics_includes_baseline_brier():
    metrics = compute_metrics(QUICK_SYNTHETIC_ROWS)
    assert metrics["n_graded"] == len(QUICK_SYNTHETIC_ROWS)
    assert "brier" in metrics
    assert "baseline_brier" in metrics
    assert metrics["brier"] <= metrics["baseline_brier"]


def test_run_quick_backtest_matches_synthetic_sample():
    out = run_quick_backtest()
    assert out["preset"] == "quick"
    assert out["metrics"]["n_graded"] == len(QUICK_SYNTHETIC_ROWS)
    assert passes_gate(out["metrics"], out["gate"])


def test_passes_gate_fails_when_brier_too_high():
    metrics = {"brier": 0.30, "baseline_brier": 0.20, "n_graded": 10}
    assert passes_gate(metrics, DEFAULT_GATE_BASELINES) is False


def test_passes_gate_fails_when_n_graded_too_low():
    metrics = {"brier": 0.10, "baseline_brier": 0.20, "n_graded": 1}
    baselines = {**DEFAULT_GATE_BASELINES, "min_n_graded": 4}
    assert passes_gate(metrics, baselines) is False


def test_passes_gate_fails_when_baseline_brier_missing():
    metrics = {"brier": 0.10, "n_graded": 10}
    assert passes_gate(metrics, DEFAULT_GATE_BASELINES) is False


def test_passes_gate_passes_when_model_beats_baseline():
    metrics = {"brier": 0.18, "baseline_brier": 0.22, "n_graded": 8}
    assert passes_gate(metrics, DEFAULT_GATE_BASELINES) is True


def test_score_synthetic_rows_builds_graded_rows():
    rows = score_synthetic_rows(QUICK_SYNTHETIC_ROWS)
    assert len(rows) == len(QUICK_SYNTHETIC_ROWS)
    assert all("td_probability" in r and "scored_anytime_td" in r for r in rows)


def test_committed_metrics_artifact_passes_gate():
    import json

    payload = json.loads(FIXTURE_METRICS.read_text(encoding="utf-8"))
    assert passes_gate(payload["metrics"], payload.get("gate", DEFAULT_GATE_BASELINES))


def test_committed_metrics_artifact_regression():
    import json

    payload = json.loads(FIXTURE_METRICS.read_text(encoding="utf-8"))
    metrics = payload["metrics"]
    # Quick smoke artifact OR walk-forward artifact both must pass gate.
    assert metrics["n_graded"] >= DEFAULT_GATE_BASELINES["min_n_graded"]
    assert "brier" in metrics
    assert "baseline_brier" in metrics


def test_walk_forward_on_injectable_weekly_records():
    """Synthetic multi-week walk-forward (no nflverse) grades weeks > 1."""
    from app.services.etl.nfl.anytime_td_backtest import run_walk_forward_backtest

    weekly = []
    for week in (1, 2, 3):
        weekly.append(
            {
                "player_id": "rb1",
                "player_display_name": "RB One",
                "position": "RB",
                "recent_team": "KC",
                "opponent_team": "BUF",
                "week": week,
                "targets": 2,
                "carries": 15,
                "rushing_tds": 1 if week in (1, 3) else 0,
                "receiving_tds": 0,
                "target_share": 0.1,
            }
        )
        weekly.append(
            {
                "player_id": "wr1",
                "player_display_name": "WR One",
                "position": "WR",
                "recent_team": "KC",
                "opponent_team": "BUF",
                "week": week,
                "targets": 8,
                "carries": 0,
                "rushing_tds": 0,
                "receiving_tds": 1 if week == 2 else 0,
                "target_share": 0.28,
            }
        )

    out = run_walk_forward_backtest(
        seasons=(2024,),
        start_week=2,
        end_week=3,
        weekly_by_season={2024: weekly},
        pbp_by_season={2024: []},
    )
    assert out["preset"] == "walk_forward"
    assert out["metrics"]["n_graded"] >= 2
    assert "brier" in out["metrics"]
    assert "top20_hit_rate" in out["metrics"]
    assert "by_position" in out["metrics"]
