"""Failing tests for season Elo reseeding."""

from datetime import date
from types import SimpleNamespace

import pytest

from app.services.etl._spread_model import (
    WNBA_CONFIG,
    load_elos_from_actuals,
    reseed_elos,
    season_id_for_date,
)


def _game(d: date, home: str, away: str, hs: int, aws: int):
    return SimpleNamespace(
        game_date=d,
        home_team_name=home,
        away_team_name=away,
        home_score=hs,
        away_score=aws,
    )


def test_season_id_wnba_is_calendar_year_from_may():
    assert season_id_for_date(date(2025, 5, 1), cfg=WNBA_CONFIG) == 2025
    assert season_id_for_date(date(2025, 10, 15), cfg=WNBA_CONFIG) == 2025
    # Pre-May dates belong to prior calendar season id
    assert season_id_for_date(date(2025, 4, 1), cfg=WNBA_CONFIG) == 2024


def test_reseed_elos_blends_prior_with_league_mean():
    elos = {"A": 1600.0, "B": 1400.0}
    reseeds = reseed_elos(elos, cfg=WNBA_CONFIG)
    mean = 1500.0
    assert reseeds["A"] == pytest.approx(0.75 * 1600 + 0.25 * mean)
    assert reseeds["B"] == pytest.approx(0.75 * 1400 + 0.25 * mean)


def test_load_elos_reseeds_between_seasons():
    # End of 2024: A dominates B
    games = [
        _game(date(2024, 6, 1), "A", "B", 90, 70),
        _game(date(2024, 6, 2), "A", "B", 88, 72),
        _game(date(2024, 6, 3), "A", "B", 85, 75),
    ]
    mid = load_elos_from_actuals(games, cfg=WNBA_CONFIG)
    a_end_2024 = mid["A"]
    b_end_2024 = mid["B"]
    assert a_end_2024 > b_end_2024

    # First 2025 game should reseed before update
    games.append(_game(date(2025, 5, 15), "A", "B", 80, 80))
    final = load_elos_from_actuals(games, cfg=WNBA_CONFIG)

    mean_2024 = (a_end_2024 + b_end_2024) / 2
    a_seed = 0.75 * a_end_2024 + 0.25 * mean_2024
    b_seed = 0.75 * b_end_2024 + 0.25 * mean_2024
    # After reseed, gap must shrink vs end of prior season
    assert abs(final["A"] - final["B"]) < abs(a_end_2024 - b_end_2024)
    # Seeded values themselves regress toward the mean
    assert abs(a_seed - mean_2024) < abs(a_end_2024 - mean_2024)
    assert abs(b_seed - mean_2024) < abs(b_end_2024 - mean_2024)
    # Final ratings stay near the reseeded band (HCA moves them a bit on a tie)
    assert abs(final["A"] - a_seed) < 20.0
    assert abs(final["B"] - b_seed) < 20.0
