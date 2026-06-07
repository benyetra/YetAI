"""Tests for point-in-time WNBA team stats."""

from __future__ import annotations

from datetime import date

from app.services.etl.wnba.ml_training.team_stats_as_of import (
    DEFAULT_LOOKBACK_DAYS,
    TeamStatsCache,
    pace_and_efficiency_as_of,
)


def test_pace_and_efficiency_uses_only_games_before_as_of():
    cache = TeamStatsCache(
        team_name_to_id={"indiana fever": 1},
        by_team={
            1: [
                (
                    date(2024, 5, 1),
                    {"pace": 78.0, "offensive_rating": 100.0, "defensive_rating": 99.0},
                ),
                (
                    date(2024, 6, 1),
                    {
                        "pace": 82.0,
                        "offensive_rating": 104.0,
                        "defensive_rating": 101.0,
                    },
                ),
                (
                    date(2024, 7, 1),
                    {
                        "pace": 99.0,
                        "offensive_rating": 120.0,
                        "defensive_rating": 115.0,
                    },
                ),
            ]
        },
        max_games=15,
    )

    stats = pace_and_efficiency_as_of(cache, "Indiana Fever", date(2024, 6, 15))
    assert stats["pace"] == 80.0  # mean of May + June, not July
    assert stats["offensive_rating"] == 102.0

    stats_on_day = pace_and_efficiency_as_of(cache, "Indiana Fever", date(2024, 6, 1))
    assert stats_on_day["pace"] == 78.0


def test_default_lookback_covers_prior_season_games():
    assert DEFAULT_LOOKBACK_DAYS >= 365
