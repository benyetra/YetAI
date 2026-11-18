"""QB passing-yards calls must match the published number (F6)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.etl.nfl import qb_betting, qb_dynamic, qb_passing_yards_ml as ml

LINES = {
    "FanDuel": {
        "over": {"line": 250.5, "odds": -110},
        "under": {"line": 250.5, "odds": -110},
    }
}


def _qb(name="Josh Allen", yards=300.0):
    return SimpleNamespace(
        qb_player_name=name,
        game_date=datetime(2099, 1, 1),
        ou_line=None,
        over_odds=None,
        under_odds=None,
        best_over_book=None,
        best_under_book=None,
        predicted_passing_yards=yards,
        betting_recommendation=None,
        bet_size=None,
        edge_percentage=None,
        recommendation_reason=None,
        feature_importance={"features": {"x": 1}, "tier_yards": yards},
        model_confidence=0.9,
        prediction_interval_lower=250.0,
        prediction_interval_upper=350.0,
        prediction_method="tier_table",
        model_version="tier-v3",
    )


def _run_betting(monkeypatch, qbs, lines=None):
    session = MagicMock()
    q = session.query.return_value
    q.filter_by.return_value.all.return_value = qbs
    q.filter.return_value.all.return_value = []
    monkeypatch.setattr(qb_betting, "db_session", session)
    monkeypatch.setattr(qb_betting, "get_nfl_season", lambda: 2099)
    monkeypatch.setattr(qb_betting, "get_current_nfl_week", lambda s: 1)
    monkeypatch.setattr(qb_betting, "has_kicked_off", lambda k: False)
    monkeypatch.setattr(
        qb_betting,
        "get_nfl_games_and_lines",
        lambda: lines or {q.qb_player_name: LINES for q in qbs},
    )
    qb_betting._run_qb_betting_core()


def _ml_patches(monkeypatch, *, enabled, ml_yards=290.0, boom=False):
    monkeypatch.setattr(ml, "qb_ml_enabled", lambda: enabled)

    def predict(_f):
        if boom:
            raise RuntimeError("model gone")
        return ml_yards

    monkeypatch.setattr(ml, "predict_yards_ml_loaded", predict)
    monkeypatch.setattr(ml, "resolve_qb_model_version", lambda **k: "gbm-test")
    monkeypatch.setattr(ml, "_metadata", lambda: {})


def test_all_qbs_considered_beyond_32(monkeypatch):
    _ml_patches(monkeypatch, enabled=False)
    qbs = [_qb(f"QB Number{i}") for i in range(40)]
    _run_betting(monkeypatch, qbs)
    assert sum(q.ou_line == 250.5 for q in qbs) == 40
    # the query chain no longer has a .limit() in it
    assert not qb_betting.__dict__[
        "db_session"
    ].query.return_value.filter_by.return_value.limit.called


def test_flag_off_keeps_call_logic(monkeypatch):
    _ml_patches(monkeypatch, enabled=False, ml_yards=400.0)
    qb = _qb(yards=400.0)  # soft anchor (alpha .25) still leaves a >7% edge
    _run_betting(monkeypatch, [qb])
    assert qb.betting_recommendation == "OVER"
    assert qb.bet_size in {"MEDIUM", "LARGE"}


def test_ml_published_number_writes_no_call(monkeypatch):
    _ml_patches(monkeypatch, enabled=True, ml_yards=330.0)  # huge edge vs 250.5
    qb = _qb()
    _run_betting(monkeypatch, [qb])
    assert qb.predicted_passing_yards == 330.0
    assert qb.betting_recommendation == "PASS"
    assert qb.bet_size is None and qb.edge_percentage is None


def test_ml_exception_writes_no_call(monkeypatch):
    _ml_patches(monkeypatch, enabled=True, boom=True)
    qb = _qb(yards=330.0)  # tier yards would be a big OVER
    _run_betting(monkeypatch, [qb])
    assert qb.betting_recommendation == "PASS"
    assert qb.bet_size is None and qb.edge_percentage is None


def _dyn_session(existing):
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing
    return session


def _dyn_setup(monkeypatch, session, *, kickoff, new_yards=280.0):
    monkeypatch.setattr(qb_dynamic, "db_session", session)
    monkeypatch.setattr(qb_dynamic, "get_nfl_season", lambda: 2099)
    monkeypatch.setattr(qb_dynamic, "get_current_nfl_week", lambda s: 1)
    monkeypatch.setattr(qb_dynamic, "_load_weekly_qb_history", lambda s: [])
    monkeypatch.setattr(
        qb_dynamic,
        "get_dynamic_starting_qbs",
        lambda s, w: [
            {
                "name": "Josh Allen",
                "team_id": 2,
                "team_name": "Buffalo Bills",
                "team_abbr": "BUF",
                "player_id": "00-1",
                "is_backup": False,
                "injury_status": "Healthy",
                "hours_to_kickoff": None,
            }
        ],
    )
    monkeypatch.setattr(qb_dynamic, "get_game_kickoff", lambda *a: kickoff)
    monkeypatch.setattr(qb_dynamic, "get_team_opponent", lambda *a: "MIA")
    monkeypatch.setattr(
        qb_dynamic, "_resolve_game_date", lambda *a: datetime(2099, 1, 1)
    )
    monkeypatch.setattr(
        qb_dynamic,
        "predict_qb_passing_yards",
        lambda *a, **k: {"predicted_passing_yards": new_yards},
    )
    monkeypatch.setattr(
        qb_dynamic, "lookup_tier_base_yards", lambda n: new_yards, raising=False
    )
    build = MagicMock(return_value={"dynamic_tier_yards": new_yards})
    monkeypatch.setattr(qb_dynamic, "build_qb_prediction_context", build)
    monkeypatch.setattr(
        qb_dynamic,
        "enrich_qb_prediction_for_write",
        lambda tp, **k: {
            "predicted_passing_yards": tp["predicted_passing_yards"],
            "model_confidence": 0.8,
            "prediction_method": "tier_table",
            "model_version": "tier-v3",
            "feature_importance": {},
        },
    )
    return build


def _existing(yards):
    return SimpleNamespace(
        predicted_passing_yards=yards,
        betting_recommendation="OVER",
        bet_size="LARGE",
        edge_percentage=15.0,
        recommendation_reason="old",
        game_date=datetime(2099, 1, 1),
    )


@pytest.fixture(autouse=True)
def _tier_helpers(monkeypatch):
    import app.services.etl.nfl.qb_late_availability as la
    import app.services.etl.nfl.qb_tiers as tiers

    monkeypatch.setattr(tiers, "lookup_tier_base_yards", lambda n: 280.0)
    monkeypatch.setattr(la, "late_yard_adjustment", lambda **k: (k["base_yards"], {}))


def test_reprojection_that_changes_yards_clears_call(monkeypatch):
    row = _existing(300.0)
    _dyn_setup(monkeypatch, _dyn_session(row), kickoff=datetime(2099, 1, 1, 13, 0))
    qb_dynamic._run_qb_dynamic_core()
    assert row.predicted_passing_yards == 280.0
    assert row.betting_recommendation is None
    assert row.bet_size is None and row.edge_percentage is None
    assert row.recommendation_reason is None


def test_reprojection_with_same_yards_keeps_call(monkeypatch):
    row = _existing(280.0)
    _dyn_setup(monkeypatch, _dyn_session(row), kickoff=datetime(2099, 1, 1, 13, 0))
    qb_dynamic._run_qb_dynamic_core()
    assert row.betting_recommendation == "OVER"


def test_unknown_kickoff_freezes_after_known_game_date(monkeypatch):
    row = _existing(300.0)
    row.game_date = datetime.now() - timedelta(days=3)
    build = _dyn_setup(monkeypatch, _dyn_session(row), kickoff=None)
    qb_dynamic._run_qb_dynamic_core()
    build.assert_not_called()
    assert row.predicted_passing_yards == 300.0


def test_unknown_kickoff_future_game_still_updates(monkeypatch):
    row = _existing(300.0)
    _dyn_setup(monkeypatch, _dyn_session(row), kickoff=None)
    qb_dynamic._run_qb_dynamic_core()
    assert row.predicted_passing_yards == 280.0
