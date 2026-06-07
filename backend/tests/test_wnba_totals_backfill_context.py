"""Tests for bulk WNBA totals backfill context."""

from __future__ import annotations

from datetime import date

from app.services.etl.wnba.ml_training.totals_backfill_context import (
    TotalsBackfillContext,
    form_adjustment_as_of,
    rest_adjustment_as_of,
    team_form_as_of,
)
from app.services.etl.wnba.ml_training import team_stats_as_of as tsa


def _sample_context() -> TotalsBackfillContext:
    return TotalsBackfillContext(
        stats_cache=tsa.TeamStatsCache(),
        team_name_to_id={"home": 1, "away": 2},
        team_player_ids={1: [101], 2: [201]},
        player_points_by_date={
            101: [
                (date(2024, 5, d), 10.0 + d) for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
            ],
            201: [(date(2024, 5, d), 12.0) for d in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)],
        },
        team_game_dates={
            1: [date(2024, 5, d) for d in range(1, 11)],
            2: [date(2024, 5, d) for d in range(1, 11)],
        },
    )


def test_rest_adjustment_detects_back_to_back():
    ctx = _sample_context()
    adj = rest_adjustment_as_of(ctx, "Home", "Away", date(2024, 5, 2))
    assert adj <= -2.0


def test_team_form_as_of_ignores_future_games():
    ctx = _sample_context()
    form_early = team_form_as_of(ctx, "Home", date(2024, 5, 6))
    form_late = team_form_as_of(ctx, "Home", date(2024, 5, 11))
    assert form_early != form_late


def test_form_adjustment_is_bounded():
    ctx = _sample_context()
    total = form_adjustment_as_of(ctx, "Home", "Away", date(2024, 5, 11))
    assert -10.0 <= total <= 10.0
