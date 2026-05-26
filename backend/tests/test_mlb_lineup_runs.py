"""Tests for lineup-weighted Monte Carlo run adjustments (Phase 5)."""

from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.mlb.monte_carlo import TeamRunRates
from app.services.etl.mlb.profiles.lineup_runs import (
    attach_lineup_features_for_mc,
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


def test_attach_lineup_features_for_mc_populates_lineups(monkeypatch):
    monkeypatch.setenv("MLB_PROFILES_ENABLED", "1")
    game = {
        "home_id": 119,
        "away_id": 121,
        "home_pitcher_id": 10,
        "away_pitcher_id": 20,
    }
    features: dict = {}

    with patch(
        "app.services.etl.mlb.lineup_utils.projected_lineup",
        side_effect=lambda tid: [tid * 10 + i for i in range(9)],
    ):
        attach_lineup_features_for_mc(game, features)

    assert len(features["home_lineup"]) == 9
    assert len(features["away_lineup"]) == 9
    assert features["home_pitcher_id"] == 10
    assert features["away_pitcher_id"] == 20


def test_maybe_adjust_applies_with_lineups(monkeypatch):
    monkeypatch.setenv("MLB_PROFILES_ENABLED", "1")
    base = TeamRunRates(home_mu=4.5, away_mu=4.2)
    features = {
        "home_lineup": [1, 2, 3],
        "away_lineup": [4, 5, 6],
        "home_pitcher_id": 10,
        "away_pitcher_id": 20,
        "game_id": 777001,
    }

    with patch(
        "app.services.etl.mlb.profiles.lineup_runs.ProfileStore"
    ) as mock_store_cls:
        mock_store = MagicMock()
        mock_store_cls.return_value = mock_store
        with patch(
            "app.services.etl.mlb.profiles.lineup_runs.expected_runs_from_lineup"
        ) as mock_exp:
            mock_exp.return_value = (
                TeamRunRates(home_mu=4.7, away_mu=4.0),
                {"lineup_weighted": True, "home_run_adj": 0.2, "away_run_adj": -0.2},
            )
            rates, meta = maybe_adjust_rates_from_lineups(
                features, base, date(2024, 6, 1), db=MagicMock()
            )

    assert rates.home_mu == 4.7
    assert meta is not None
    assert meta["lineup_weighted"] is True
