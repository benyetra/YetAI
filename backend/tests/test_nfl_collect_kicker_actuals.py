"""Tests for kicker actuals matching helpers."""

from __future__ import annotations

from types import SimpleNamespace

from app.services.etl.nfl.collect_kicker_actuals import (
    _LEAGUE_PRIOR_FG,
    _find_prediction,
    _match_kicker_name,
)


def test_match_kicker_abbreviated_name():
    pred = SimpleNamespace(kicker_player_name="Matt Prater")
    assert _match_kicker_name(pred, "m.prater")


def test_find_prediction_falls_back_to_prior():
    pred, source, projected = _find_prediction(
        kicker_name="Nobody Kicker",
        kicker_id="00-000",
        game_date=__import__("datetime").date(2025, 10, 5),
        historical=[],
        current=[],
    )
    assert pred is None
    assert source is None
    assert projected == _LEAGUE_PRIOR_FG
