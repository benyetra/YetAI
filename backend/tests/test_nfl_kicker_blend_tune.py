"""Tests for NFL kicker blend walk-forward and distance imputation."""

from __future__ import annotations

from app.services.etl.nfl.kicker_blend_tune import (
    impute_kick_distance,
    walk_forward_blend_weight,
)


def test_impute_kick_distance_from_kicker_avg():
    dist = impute_kick_distance({"name": "J.Smith", "avg_distance": 42.5}, {})
    assert dist == 42.5


def test_impute_kick_distance_from_game_context():
    dist = impute_kick_distance(
        {"name": "J.Smith"},
        {},
        game_context={"kick_distance": 48.0},
    )
    assert dist == 48.0


def test_walk_forward_prefers_ml_when_ml_closer():
    records = []
    for i in range(12):
        records.append(
            {
                "statistical_fgs": 1.5,
                "ml_fgs": 2.0,
                "actual_fg_made": 2.0,
            }
        )
    w = walk_forward_blend_weight(records, weight_grid=[0.0, 0.35, 0.7])
    assert w >= 0.35


def test_walk_forward_prefers_stat_when_stat_closer():
    records = []
    for i in range(12):
        records.append(
            {
                "statistical_fgs": 2.0,
                "ml_fgs": 1.0,
                "actual_fg_made": 2.0,
            }
        )
    w = walk_forward_blend_weight(records, weight_grid=[0.0, 0.35, 0.7])
    assert w <= 0.35
