"""Tests for QB pass-yards O/U classifier."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.etl.nfl.qb_features import FEATURE_NAMES
from app.services.etl.nfl.qb_ou_classifier import (
    build_ou_feature_row,
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


def test_recommendation_from_over_prob():
    assert recommendation_from_over_prob(0.62)["recommendation"] == "OVER"
    assert recommendation_from_over_prob(0.35)["recommendation"] == "UNDER"
    assert recommendation_from_over_prob(0.52)["recommendation"] == "PASS"


def test_betting_recommendation_ml_disagreement_passes():
    # Strong yards OVER but ML says UNDER → PASS when edge < 10%
    out = generate_betting_recommendation(260.0, 245.0, 0.8, over_probability=0.35)
    # edge ~6.1% < 10 strong → PASS on disagreement
    assert out["recommendation"] == "PASS"


def test_betting_recommendation_ml_agreement():
    out = generate_betting_recommendation(270.0, 240.0, 0.8, over_probability=0.7)
    assert out["recommendation"] == "OVER"
    assert "ML agrees" in out["reason"]
