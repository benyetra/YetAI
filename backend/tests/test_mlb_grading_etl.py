"""MLB-10/H-8 lookback and MLB-11 strikeout push grading."""

import sys
from datetime import date
from unittest.mock import MagicMock, patch

sys.modules.setdefault("app.services.etl.mlb.strikeouts", MagicMock())

from app.services.etl.mlb import daily_projection_update as k_mod
from app.services.etl.mlb import pipeline


def test_run_actuals_phase_grades_every_lookback_date():
    days = [date(2026, 5, 21), date(2026, 5, 22), date(2026, 5, 23)]
    with (
        patch("app.services.etl.grading_window.grading_dates", return_value=days),
        patch(
            "app.services.etl.mlb.game_projection_pipeline.run_store_game_actuals"
        ) as g,
        patch(
            "app.services.etl.mlb.daily_projection_update.run_store_strikeout_actuals"
        ) as k,
        patch(
            "app.services.etl.mlb.daily_batter_projection.run_store_batter_actuals"
        ) as b,
    ):
        out = pipeline.run_actuals_phase()
    for fn in (g, k, b):
        assert [c.args[0] for c in fn.call_args_list] == days
    assert out["dates"] == [d.isoformat() for d in days]


def _push_setup(strikeouts, line, pick):
    projection = MagicMock(
        fanduel_line=line,
        fanduel_over_under=pick,
        projected_strikeouts=5.0,
        projected_innings_pitched=6.0,
        projected_at_bats=22.0,
    )
    existing = MagicMock()
    db = MagicMock()

    def q(model):
        m = MagicMock()
        m.filter_by.return_value.first.return_value = (
            projection if model is k_mod.StrikeoutProjections else existing
        )
        return m

    db.query.side_effect = q
    return db, existing


def _run_k(strikeouts, line, pick):
    db, existing = _push_setup(strikeouts, line, pick)
    with (
        patch.object(k_mod, "db_session", db),
        patch.object(
            k_mod, "fetch_days_pitchers", return_value=[{"pitcher_id": 1, "name": "A"}]
        ),
        patch.object(k_mod, "fetch_pitcher_game_logs", return_value=[]),
        patch.object(
            k_mod,
            "calculate_metrics_actuals_v_projections",
            return_value=(6.0, strikeouts, 22, 1, 4),
        ),
    ):
        k_mod.store_actuals(date(2026, 5, 21))
    return existing.correct_prediction


def test_strikeout_push_is_not_graded_as_under():
    assert _run_k(5.0, 5.0, "under") is None
    assert _run_k(5.0, 5.0, "over") is None


def test_strikeout_non_push_still_graded():
    assert _run_k(7.0, 5.5, "over") is True
    assert _run_k(7.0, 5.5, "under") is False
