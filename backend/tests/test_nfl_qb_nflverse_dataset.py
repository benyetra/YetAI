"""Smoke tests for offline nflverse QB dataset builder (no network in unit path)."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from app.services.etl.nfl.ml_training import build_qb_dataset_nflverse as mod


def test_build_from_nflverse_empty_when_no_weekly():
    with patch.object(mod, "_weekly_records", return_value=[]):
        feats, target, meta = mod.build_from_nflverse([2024])
    assert feats.empty
    assert target.empty
    assert meta.empty


def test_build_from_nflverse_leak_safe_form():
    history = [
        {
            "qb_player_id": "1",
            "qb_player_name": "Josh Allen",
            "season": 2024,
            "week": 1,
            "actual_passing_yards": 280.0,
            "recent_team": "BUF",
            "opponent_team": "MIA",
            "position": "QB",
            "passing_yards": 280.0,
            "passing_epa": 0.2,
            "attempts": 35.0,
            "sacks": 2.0,
        },
        {
            "qb_player_id": "1",
            "qb_player_name": "Josh Allen",
            "season": 2024,
            "week": 2,
            "actual_passing_yards": 300.0,
            "recent_team": "BUF",
            "opponent_team": "NYJ",
            "position": "QB",
            "passing_yards": 300.0,
            "passing_epa": 0.1,
            "attempts": 40.0,
            "sacks": 1.0,
        },
    ]
    with patch.object(mod, "_weekly_records", return_value=history):
        feats, target, meta = mod.build_from_nflverse([2024])
    assert len(feats) == 2
    assert list(target) == [280.0, 300.0]
    # Week 2 form should see week 1 prior
    assert feats.iloc[1]["rolling_yards_l3"] == 280.0
