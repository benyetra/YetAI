"""Tests for QB pass-yards O/U classifier."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_features import FEATURE_NAMES
from app.services.etl.nfl.qb_ou_classifier import (
    build_ou_feature_row,
    filter_real_ou_training_rows,
    is_real_ou_line,
    predict_over_probability,
    recommendation_from_over_prob,
    train_qb_ou_classifier,
)
from app.services.etl.nfl.qb_betting import generate_betting_recommendation


def test_build_ou_feature_row():
    feats = {name: 0.0 for name in FEATURE_NAMES}
    feats["tier_yards"] = 260.0
    row = build_ou_feature_row(feats, 240.5)
    assert row["ou_line"] == 240.5
    assert row["yards_minus_line"] == 19.5


def test_build_ou_feature_row_prefers_projected_yards():
    feats = {name: 0.0 for name in FEATURE_NAMES}
    feats["tier_yards"] = 260.0
    feats["ml_shadow_yards"] = 275.0
    row = build_ou_feature_row(feats, 250.0)
    assert row["yards_minus_line"] == 25.0


def test_is_real_ou_line_rejects_tier_anchor():
    assert is_real_ou_line(ou_line=250.0, tier_yards=250.0) is False
    assert is_real_ou_line(ou_line=250.5, tier_yards=250.0) is False
    assert is_real_ou_line(ou_line=265.5, tier_yards=250.0) is True
    assert is_real_ou_line(ou_line=265.5, tier_yards=250.0, line_is_real=False) is False


def test_filter_real_ou_training_rows():
    df = pd.DataFrame(
        [
            {"ou_line": 250.0, "tier_yards": 250.0, "line_is_real": 0.0},
            {"ou_line": 265.5, "tier_yards": 250.0, "line_is_real": 1.0},
            {"ou_line": 240.0, "tier_yards": 250.0, "line_is_real": 1.0},
        ]
    )
    actuals = pd.Series([260.0, 280.0, 240.0])
    kept, y = filter_real_ou_training_rows(df, actuals)
    # row0 fake line dropped; row2 push (|0|<0.5) dropped; row1 kept
    assert len(kept) == 1
    assert float(kept.iloc[0]["ou_line"]) == 265.5
    assert len(y) == 1


def test_train_ou_classifier_smoke():
    n = 80
    rng = np.random.default_rng(0)
    rows = []
    labels = []
    for i in range(n):
        feats = {name: 0.0 for name in FEATURE_NAMES}
        feats["tier_yards"] = 220 + rng.normal(0, 20)
        line = 225.0
        row = build_ou_feature_row(feats, line)
        rows.append(row)
        # Label correlated with yards_minus_line
        labels.append(1 if row["yards_minus_line"] > 0 else 0)
    # Ensure both classes
    labels[0] = 0
    labels[1] = 1
    model, meta = train_qb_ou_classifier(pd.DataFrame(rows), pd.Series(labels))
    prob = predict_over_probability(
        model, rows[2], 225.0, feature_order=meta["features"]
    )
    assert 0.0 <= prob <= 1.0
    assert meta["holdout_brier"] >= 0
    assert meta.get("real_line_only") is True


def test_recommendation_from_over_prob():
    assert recommendation_from_over_prob(0.62)["recommendation"] == "OVER"
    assert recommendation_from_over_prob(0.35)["recommendation"] == "UNDER"
    assert recommendation_from_over_prob(0.52)["recommendation"] == "PASS"
    # Tightened default min_edge=0.10 → 0.58 still PASS
    assert recommendation_from_over_prob(0.58)["recommendation"] == "PASS"


def test_betting_recommendation_ml_disagreement_passes():
    # Yards OVER (~7.4%) but ML UNDER → PASS when edge < strong 12%
    out = generate_betting_recommendation(260.0, 242.0, 0.8, over_probability=0.35)
    assert out["recommendation"] == "PASS"


def test_betting_recommendation_ml_disagreement_passes_even_on_strong_yards_edge():
    # ~16.7% yards OVER vs ML UNDER — previously leaked OVER when |edge| >= 12
    out = generate_betting_recommendation(280.0, 240.0, 0.8, over_probability=0.35)
    assert out["recommendation"] == "PASS"
    assert "disagrees" in out["reason"].lower() or "disagree" in out["reason"].lower()


def test_betting_recommendation_ml_agreement():
    out = generate_betting_recommendation(270.0, 240.0, 0.8, over_probability=0.7)
    assert out["recommendation"] == "OVER"
    assert "ML agrees" in out["reason"]


def test_betting_recommendation_requires_higher_confidence():
    out = generate_betting_recommendation(270.0, 240.0, 0.68, over_probability=0.7)
    assert out["recommendation"] == "PASS"
    assert "Low confidence" in out["reason"]
