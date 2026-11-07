"""Season-scoped NFL team PPG (Phase A spreads/totals form fix)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.etl.nfl._team_ppg import (
    MIN_SEASON_GAMES_FOR_PPG,
    compute_team_ppg_stats,
    nfl_season_id_for_date,
)


@dataclass(frozen=True)
class _Actual:
    game_date: date
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int


def _game(
    d: date,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
) -> _Actual:
    return _Actual(d, home, away, home_score, away_score)


def test_nfl_season_id_spans_calendar_year():
    assert nfl_season_id_for_date(date(2025, 9, 7)) == 2025
    assert nfl_season_id_for_date(date(2026, 1, 12)) == 2025
    assert nfl_season_id_for_date(date(2026, 9, 10)) == 2026


def test_season_filter_differs_from_multi_year_blend():
    """2023–25 seed + 2026 form must not equal the unfiltered career mush."""
    actuals = [
        # Multi-year seed: Chiefs average ~20 PPG for / 20 against
        _game(date(2023, 10, 1), "Kansas City Chiefs", "Denver Broncos", 20, 20),
        _game(date(2024, 10, 1), "Kansas City Chiefs", "Denver Broncos", 20, 20),
        _game(date(2025, 10, 1), "Kansas City Chiefs", "Denver Broncos", 20, 20),
        # 2026 form: Chiefs average 30 PPG for / 10 against (≥ min season games)
        _game(date(2026, 9, 14), "Kansas City Chiefs", "Denver Broncos", 30, 10),
        _game(date(2026, 9, 21), "Buffalo Bills", "Kansas City Chiefs", 10, 30),
        _game(date(2026, 9, 28), "Kansas City Chiefs", "Las Vegas Raiders", 30, 10),
        _game(date(2026, 10, 5), "Detroit Lions", "Kansas City Chiefs", 10, 30),
    ]
    assert (
        len([a for a in actuals if a.game_date.year == 2026])
        >= MIN_SEASON_GAMES_FOR_PPG
    )

    all_time = compute_team_ppg_stats(actuals)
    season_2026 = compute_team_ppg_stats(actuals, season=2026)

    assert all_time["Kansas City Chiefs"] != season_2026["Kansas City Chiefs"]
    assert season_2026["Kansas City Chiefs"] == (30.0, 10.0)
    # Unfiltered blend is pulled toward the multi-year 20/20 mush.
    assert all_time["Kansas City Chiefs"][0] < 30.0
    assert all_time["Kansas City Chiefs"][1] > 10.0


def test_early_season_falls_back_to_prior_year():
    """Fewer than min in-season games → use prior season PPG."""
    actuals = [
        _game(date(2025, 10, 5), "Buffalo Bills", "Miami Dolphins", 28, 14),
        _game(date(2025, 10, 12), "New England Patriots", "Buffalo Bills", 10, 35),
        _game(date(2025, 10, 19), "Buffalo Bills", "New York Jets", 31, 17),
        _game(date(2025, 10, 26), "Houston Texans", "Buffalo Bills", 20, 24),
        # Only two 2026 games (below MIN_SEASON_GAMES_FOR_PPG)
        _game(date(2026, 9, 14), "Buffalo Bills", "Miami Dolphins", 7, 35),
        _game(date(2026, 9, 21), "New York Jets", "Buffalo Bills", 28, 10),
    ]
    stats = compute_team_ppg_stats(actuals, season=2026)
    # Prior-season Bills: 4 games, scored 28+35+31+24 = 118 → 29.5 for;
    # allowed 14+10+17+20 = 61 → 15.25 against.
    assert stats["Buffalo Bills"] == (29.5, 15.25)


def test_early_season_uses_current_when_no_prior():
    actuals = [
        _game(date(2026, 9, 14), "Expansion FC", "Legacy FC", 40, 10),
        _game(date(2026, 9, 21), "Legacy FC", "Expansion FC", 7, 35),
    ]
    stats = compute_team_ppg_stats(actuals, season=2026)
    assert stats["Expansion FC"] == (37.5, 8.5)
