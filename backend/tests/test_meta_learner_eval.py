import numpy as np
import pytest

from app.services.etl.mlb.meta_learner_eval import (
    META_BRIER_LIFT_MIN,
    compare_meta_learner_vs_game_ensemble,
    evaluate_meta_vs_baseline,
    recommend_production_use,
    run_offline_fixture_comparison,
    synthetic_offline_rows,
)


def test_evaluate_meta_vs_baseline_metrics():
    y = [1, 0, 1, 0]
    p_game = [0.6, 0.4, 0.55, 0.45]
    p_meta = [0.7, 0.3, 0.8, 0.2]
    out = evaluate_meta_vs_baseline(y, p_game, p_meta)
    assert out["n"] == 4
    assert out["brier_meta"] < out["brier_game"]
    assert out["brier_lift_game_minus_meta"] > 0


def test_recommend_production_use_meta_better():
    rows = synthetic_offline_rows("meta_better")
    result = compare_meta_learner_vs_game_ensemble(rows)
    assert result["brier_lift_game_minus_meta"] >= META_BRIER_LIFT_MIN
    assert recommend_production_use(result) is True
    assert result["recommend_production_use"] is True
    assert result["recommendation"] == "use_meta_learner"


def test_recommend_production_use_meta_worse():
    rows = synthetic_offline_rows("meta_worse")
    result = compare_meta_learner_vs_game_ensemble(rows)
    assert result["brier_lift_game_minus_meta"] < 0
    assert recommend_production_use(result) is False
    assert result["recommend_production_use"] is False
    assert result["recommendation"] == "skip_meta_learner"


def test_recommend_production_use_meta_equal():
    rows = synthetic_offline_rows("meta_equal")
    result = compare_meta_learner_vs_game_ensemble(rows)
    assert result["brier_lift_game_minus_meta"] == pytest.approx(0.0, abs=1e-6)
    assert recommend_production_use(result) is False
    assert result["recommend_production_use"] is False


def test_compare_accepts_metrics_dict():
    y = np.array([1, 0, 1])
    p_game = np.array([0.5, 0.5, 0.5])
    p_meta = np.array([0.9, 0.1, 0.9])
    result = compare_meta_learner_vs_game_ensemble(
        {"y_true": y, "p_game": p_game, "p_meta": p_meta}
    )
    assert result["n"] == 3
    assert recommend_production_use(result) is True


def test_run_offline_fixture_comparison():
    out = run_offline_fixture_comparison("meta_better")
    assert out["recommend_production_use"] is True


def test_empty_rows_raises():
    with pytest.raises(ValueError, match="at least one row"):
        evaluate_meta_vs_baseline([], [], [])
