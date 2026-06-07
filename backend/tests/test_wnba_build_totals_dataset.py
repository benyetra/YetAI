"""Tests for WNBA totals training dataset builder."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from app.models.predictions_models import (
    WNBAGameLines,
    WNBASpreadActuals,
    WNBATotalsActuals,
    WNBATotalsProjections,
)
from app.services.etl.wnba.ml_training import build_totals_dataset as btd
from app.services.etl.wnba.ml_training import team_stats_as_of as tsa


def test_build_uses_spread_actuals_when_totals_empty():
    spread = SimpleNamespace(
        game_date=date(2024, 6, 1),
        home_team_name="Indiana Fever",
        away_team_name="Connecticut Sun",
        home_score=82,
        away_score=78,
        actual_total=None,
    )
    proj_dict = {
        "heuristic_total": 160.0,
        "projected_total": 160.0,
        "base_projection": 158.0,
        "expected_pace": 80.0,
        "home_offensive_rating": 102.0,
        "away_offensive_rating": 101.0,
        "home_defensive_rating": 100.0,
        "away_defensive_rating": 101.0,
        "injury_adjustment": 0.0,
        "rest_adjustment": 0.0,
        "venue_adjustment": 0.0,
        "form_adjustment": 0.0,
        "total_adjustment": 0.0,
        "market_total": 159.5,
    }

    mock_db = MagicMock()
    totals_q = MagicMock()
    totals_q.filter.return_value = totals_q
    totals_q.order_by.return_value = totals_q
    totals_q.all.return_value = []

    spread_q = MagicMock()
    spread_q.filter.return_value = spread_q
    spread_q.order_by.return_value = spread_q
    spread_q.all.return_value = [spread]

    proj_q = MagicMock()
    proj_q.filter.return_value = proj_q
    proj_q.all.return_value = []

    line_q = MagicMock()
    line_q.filter.return_value = line_q
    line_q.all.return_value = []

    mock_db.query.side_effect = lambda model: {
        WNBATotalsActuals: totals_q,
        WNBASpreadActuals: spread_q,
        WNBATotalsProjections: proj_q,
        WNBAGameLines: line_q,
    }[model]

    with patch.object(btd, "SessionLocal", return_value=mock_db):
        with patch.object(btd.tsa, "build_cache", return_value=tsa.TeamStatsCache()):
            with patch.object(
                btd, "_fast_heuristic_projection", return_value=proj_dict
            ) as replay:
                X, y, dates, stats = btd.build(date(2024, 5, 1), date(2024, 12, 31))

    replay.assert_called_once()
    assert len(X) == 1
    assert float(y.iloc[0]) == 0.0
    assert dates.iloc[0] == date(2024, 6, 1)
    assert stats["fast_replay"] == 1
    assert stats["stored_projections"] == 0


def test_build_prefers_stored_projection():
    actual = SimpleNamespace(
        game_date=date(2024, 6, 1),
        home_team_name="Indiana Fever",
        away_team_name="Connecticut Sun",
        home_score=85,
        away_score=80,
        actual_total=165,
    )
    stored = SimpleNamespace(
        game_date=date(2024, 6, 1),
        home_team_name="Indiana Fever",
        away_team_name="Connecticut Sun",
        projected_total=162.0,
        factors={"ml_shadow": {"heuristic_total": 162.0}},
        base_projection=160.0,
        expected_pace=80.0,
        home_offensive_rating=102.0,
        away_offensive_rating=101.0,
        home_defensive_rating=100.0,
        away_defensive_rating=101.0,
        injury_adjustment=0.0,
        rest_adjustment=0.0,
        venue_adjustment=0.0,
        form_adjustment=0.0,
        total_adjustment=2.0,
        market_total=161.0,
    )

    mock_db = MagicMock()
    totals_q = MagicMock()
    totals_q.filter.return_value = totals_q
    totals_q.order_by.return_value = totals_q
    totals_q.all.return_value = [actual]

    proj_q = MagicMock()
    proj_q.filter.return_value = proj_q
    proj_q.all.return_value = [stored]

    line_q = MagicMock()
    line_q.filter.return_value = line_q
    line_q.all.return_value = []

    mock_db.query.side_effect = lambda model: {
        WNBATotalsActuals: totals_q,
        WNBATotalsProjections: proj_q,
        WNBAGameLines: line_q,
    }[model]

    with patch.object(btd, "SessionLocal", return_value=mock_db):
        with patch.object(btd.tsa, "build_cache", return_value=tsa.TeamStatsCache()):
            with patch.object(btd, "_fast_heuristic_projection") as replay:
                X, y, dates, stats = btd.build(date(2024, 5, 1), date(2024, 12, 31))

    replay.assert_not_called()
    assert len(X) == 1
    assert float(y.iloc[0]) == 3.0
    assert stats["stored_projections"] == 1
    assert stats["fast_replay"] == 0
