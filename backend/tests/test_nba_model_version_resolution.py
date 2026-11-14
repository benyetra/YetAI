"""C4 (resolve the prop model version once per run) and C7 (spread fallback stamp)."""

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nba import (
    generate_steals_predictions as steals,
    generate_three_pt_made_predictions as threes,
    spread_projector as nsp,
)


def _players(n=3):
    return [
        SimpleNamespace(
            player_id=i,
            player_name=f"P{i}",
            team_name="A",
            opponent_team_name="B",
            opponent_team_id=2,
        )
        for i in range(n)
    ]


@pytest.mark.parametrize("mod", [steals, threes])
def test_prop_version_resolved_once_not_per_player(mod, monkeypatch):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    monkeypatch.setattr(mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(mod, "now_eastern", lambda: datetime(2026, 11, 13, 19, 0))
    monkeypatch.setattr(mod, "active_players_not_started", lambda d, t: _players())
    monkeypatch.setattr(mod, "_is_injured", lambda *a, **k: (False, None))
    monkeypatch.setattr(mod, "build_features", lambda **k: {"f": 1})
    monkeypatch.setattr(mod, "predict", lambda stat, f: 2.0)
    monkeypatch.setattr(
        mod, "get_event_id_for_game", lambda *a, **k: None, raising=False
    )
    calls = []
    monkeypatch.setattr(
        mod, "resolve_nba_prop_model_version", lambda s: calls.append(s) or "xgb-1"
    )
    mod.run()
    assert len(calls) == 1


def _run_spread(monkeypatch, loaded_version):
    mock_db = MagicMock(name="Session")
    game = MagicMock()
    game.game_date = date(2026, 5, 21)
    game.home_team_id, game.away_team_id = 1, 2
    game.home_team_name, game.away_team_name = "Boston Celtics", "New York Knicks"
    game.spread_home, game.total = -4.5, 220.5
    game.game_time = datetime(2099, 1, 1)
    mock_db.query.return_value.order_by.return_value.all.return_value = []
    mock_db.query.return_value.all.return_value = []
    mock_db.query.return_value.filter.return_value.all.return_value = [game]
    monkeypatch.setattr(nsp, "SessionLocal", lambda: mock_db)
    monkeypatch.setattr(nsp, "_load_elos", lambda db: {})
    monkeypatch.setattr(nsp, "model_available", lambda: True)
    monkeypatch.setattr(nsp, "build_game_features", lambda *a, **k: {"x": 1.0})
    monkeypatch.setattr(nsp, "predict_margin", lambda f: 3.0)
    monkeypatch.setattr(nsp, "get_model_version", lambda: loaded_version)
    with patch.object(nsp, "upsert_many") as um:
        nsp.run()
    return um.call_args[0][2][0]["model_version"]


def test_spread_without_metadata_version_uses_s3_last_modified(monkeypatch):
    seen = {}

    def fake_date(key, **kw):
        seen["key"] = key
        return "20261101"

    monkeypatch.setattr(nsp, "s3_object_version_date", fake_date)
    assert _run_spread(monkeypatch, None) == "xgb-20261101"
    assert seen["key"] == "nba/ml_models/xgb_spread.pkl"


def test_spread_manifest_version_still_wins(monkeypatch):
    monkeypatch.setattr(nsp, "s3_object_version_date", lambda *a, **k: "20261101")
    assert _run_spread(monkeypatch, "xgb-202611130900") == "xgb-202611130900"


def test_spread_unversioned_only_when_s3_date_unavailable(monkeypatch):
    monkeypatch.setattr(nsp, "s3_object_version_date", lambda *a, **k: None)
    assert _run_spread(monkeypatch, None) == "ml-unversioned"
