"""Tests for MLB batter actuals grading (pred_projected_* columns)."""

import sys
from datetime import date
from unittest.mock import MagicMock, patch

# hits.py imports strikeouts at module load (pulls sklearn + model artifact).
sys.modules.setdefault(
    "app.services.etl.mlb.strikeouts",
    MagicMock(),
)

from app.services.etl.mlb import daily_batter_projection as mod


def test_store_actuals_updates_projected_hits_and_homers_columns():
    target = date(2026, 5, 21)
    hit_row = MagicMock(
        batter_id=608070,
        batter_name="José Ramírez",
        projected_hits=10,
        actual_hits=0,
    )
    homer_row = MagicMock(
        batter_id=608070,
        batter_name="José Ramírez",
        projected_homers=2,
        actual_homers=0,
    )

    mock_db = MagicMock()
    hit_query = MagicMock()
    hit_query.filter_by.return_value.all.return_value = [hit_row]
    homer_query = MagicMock()
    homer_query.filter_by.return_value.all.return_value = [homer_row]
    actual_query = MagicMock()
    actual_query.filter_by.return_value.first.return_value = None

    def query_side_effect(model):
        if model is mod.ProjectedHits:
            return hit_query
        if model is mod.ProjectedHomers:
            return homer_query
        return actual_query

    mock_db.query.side_effect = query_side_effect

    with (
        patch.object(mod, "db_session", mock_db),
        patch.object(
            mod, "get_game_log_date", return_value=[{"game_date": "2026-05-21"}]
        ),
        patch.object(
            mod,
            "calculate_metrics_actuals_v_projections",
            return_value=(2, 1),
        ),
    ):
        mod.store_actuals(target)

    assert hit_row.actual_hits == 2
    assert homer_row.actual_homers == 1
    mock_db.commit.assert_called_once()


def test_store_actuals_skips_when_no_game_log_for_date():
    hit_row = MagicMock(
        batter_id=1,
        batter_name="Test Player",
        projected_hits=8,
    )
    mock_db = MagicMock()
    hit_query = MagicMock()
    hit_query.filter_by.return_value.all.return_value = [hit_row]
    homer_query = MagicMock()
    homer_query.filter_by.return_value.all.return_value = []

    def query_side_effect(model):
        if model is mod.ProjectedHits:
            return hit_query
        if model is mod.ProjectedHomers:
            return homer_query
        return MagicMock()

    mock_db.query.side_effect = query_side_effect

    with (
        patch.object(mod, "db_session", mock_db),
        patch.object(mod, "get_game_log_date", return_value=[]),
        patch.object(
            mod,
            "calculate_metrics_actuals_v_projections",
            return_value=(None, None),
        ),
    ):
        mod.store_actuals(date(2026, 5, 21))

    assert not hasattr(hit_row, "actual_hits") or hit_row.actual_hits != 2
    mock_db.commit.assert_called_once()
