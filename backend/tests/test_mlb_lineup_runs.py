"""Tests for lineup-weighted Monte Carlo run adjustments (Phase 5)."""

from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.mlb.monte_carlo import TeamRunRates
from app.services.etl.mlb.profiles.lineup_runs import (
    expected_runs_from_lineup,
    maybe_adjust_rates_from_lineups,
)
from app.services.etl.mlb.profiles.matchup_k import MatchupResult


def test_expected_runs_from_lineup_adjusts_mus():
    store = MagicMock()
    base = TeamRunRates(home_mu=4.5, away_mu=4.2)

    with patch(
        "app.services.etl.mlb.profiles.lineup_runs.compute_lineup_k_matchup"
    ) as mock_k:
        with patch(
            "app.services.etl.mlb.profiles.lineup_runs.contact_matchup_score"
        ) as mock_c:
            mock_k.return_value = MatchupResult(factor=1.05, source="observed")
            mock_c.return_value = (0.1, {})

            rates, meta = expected_runs_from_lineup(
                store,
                [1, 2, 3],
                [4, 5, 6],
                home_pitcher_id=10,
                away_pitcher_id=20,
                as_of_date=date(2024, 6, 1),
                base_rates=base,
            )

    assert rates.home_mu != base.home_mu or rates.away_mu != base.away_mu
    assert meta["lineup_weighted"] is True
    assert meta["home_lineup_size"] == 3


def test_maybe_adjust_skips_without_lineups(monkeypatch):
    monkeypatch.setenv("MLB_PROFILES_ENABLED", "1")
    base = TeamRunRates(home_mu=4.0, away_mu=4.0)
    rates, meta = maybe_adjust_rates_from_lineups(
        {"home_pitcher_id": 1, "away_pitcher_id": 2},
        base,
        date(2024, 6, 1),
    )
    assert rates == base
    assert meta is None
