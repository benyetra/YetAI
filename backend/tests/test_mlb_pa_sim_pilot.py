"""Tests for PA-level simulation pilot (Phase 7 — non-production)."""

from datetime import date
from unittest.mock import MagicMock

from app.services.etl.mlb.profiles.pa_sim_pilot import simulate_game_pa_pilot


def test_pa_sim_pilot_runs_quick():
    store = MagicMock()
    pitcher_snap = MagicMock()
    pitcher_snap.profile = {"usage": {"FF": 0.7, "SL": 0.3}}
    batter_snap = MagicMock()
    batter_snap.profile = {
        "whiff_by_pitch": {"FF": 0.25, "SL": 0.28},
        "barrel_rate_by_pitch": {"FF": 0.08, "SL": 0.06},
    }
    store.get_pitcher.return_value = pitcher_snap
    store.get_batter.return_value = batter_snap

    result = simulate_game_pa_pilot(
        store,
        home_lineup=[1, 2, 3, 4, 5, 6, 7, 8, 9],
        away_lineup=[11, 12, 13, 14, 15, 16, 17, 18, 19],
        home_pitcher_id=100,
        away_pitcher_id=200,
        as_of_date=date(2024, 7, 4),
        n_sims=500,
        seed=7,
    )

    assert result.n_sims == 500
    assert 0.0 <= result.home_win_prob <= 1.0
    assert result.home_runs_mean >= 0.0
    assert result.runtime_sec >= 0.0
