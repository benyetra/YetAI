"""generate_goalie_predictions: name-matched lines, upsert per (date, team), stale cleanup."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import NHLGoalie, NHLGoaliePredictions
from app.services.etl.nhl import daily_predictions as dp
from app.services.etl.nhl.confirm_starters import (
    GoalieStarterContext,
    SlateStarterSummary,
)

D = date(2026, 11, 13)
GAME = {
    "id": 1,
    "homeTeam": {"id": 23, "abbrev": "VAN", "placeName": {"default": "Vancouver"}},
    "awayTeam": {"id": 3, "abbrev": "NYR", "placeName": {"default": "New York"}},
}
EVENTS = [
    {"id": "ev1", "away_team": "New York Rangers", "home_team": "Vancouver Canucks"}
]
PRED = {
    "predicted_saves": 27.0,
    "predicted_shots_against": 29.0,
    "predicted_save_pct": 0.91,
    "confidence": 80.0,
}


def _line_payload(name="Leevi Merilainen", point=24.5):
    return {
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_total_saves",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": name,
                                "price": -115,
                                "point": point,
                            },
                            {
                                "name": "Under",
                                "description": name,
                                "price": -105,
                                "point": point,
                            },
                        ],
                    }
                ],
            }
        ]
    }


def _slot(goalie_id=8482447, name="L. Meriläinen", predict=True, reason=None):
    return GoalieStarterContext(
        game_id=1,
        game_date=D,
        game_time=None,
        is_home=True,
        team_id=23,
        team_name="Vancouver",
        opponent_team_id=3,
        opponent_team_name="New York",
        goalie_id=goalie_id,
        goalie_name=name,
        starter_confirmed=True,
        confidence=95.0,
        should_predict=predict,
        prediction_skipped_reason=reason,
        method="confirmed",
        source="espn",
        full_name="Leevi Meriläinen",
    )


@pytest.fixture
def run(monkeypatch):
    session = sessionmaker(bind=_engine())()
    monkeypatch.setattr(dp, "db_session", session)
    monkeypatch.setattr(dp, "predict_goalie_saves", lambda **kw: dict(PRED))
    state = {"payload": _line_payload(), "markets": []}

    def odds(event_id, home, away, markets=None):
        state["markets"].append(markets)
        from app.services.etl.nhl.generate_daily_predictions import (
            get_goalie_saves_odds_for_event as real,
        )

        with patch(
            "app.services.etl.nhl.generate_daily_predictions._fetch_nhl_event_odds_payload",
            return_value=state["payload"],
        ):
            return real(event_id, home, away)

    monkeypatch.setattr(dp, "get_goalie_saves_odds_for_event", odds)

    def go(slot, payload="keep", **kw):
        if payload != "keep":
            state["payload"] = payload
        monkeypatch.setattr(
            dp,
            "build_slate_starter_context",
            lambda games: SlateStarterSummary.from_slots([slot]),
        )
        n = dp.generate_goalie_predictions([GAME], EVENTS, **kw)
        return n, session.query(NHLGoaliePredictions).all()

    go.state = state
    return go


def _engine():
    eng = create_engine("sqlite://")
    NHLGoaliePredictions.__table__.create(eng)
    return eng


def test_first_run_matches_line_by_full_name(run):
    n, rows = run(_slot())
    assert n == 1 and len(rows) == 1
    r = rows[0]
    assert (r.goalie_id, r.saves_line, r.over_odds, r.under_odds) == (
        8482447,
        24.5,
        -115,
        -105,
    )
    assert r.line_available is True
    assert r.betting_recommendation == "OVER 24.5"  # 27.0 vs 24.5
    assert r.features_used["starter_confirmation"]["full_name"] == "Leevi Meriläinen"


def test_rerun_without_line_keeps_line_and_does_not_duplicate(run):
    run(_slot())
    n, rows = run(_slot(), payload={})
    assert len(rows) == 1
    r = rows[0]
    assert (r.saves_line, r.over_odds, r.under_odds) == (24.5, -115, -105)
    assert r.line_available is True
    assert r.betting_recommendation == "OVER 24.5"


def test_starter_change_updates_row_and_drops_old_line(run):
    run(_slot())
    n, rows = run(_slot(goalie_id=8480947, name="K. Lankinen"), payload={})
    assert len(rows) == 1
    assert rows[0].goalie_id == 8480947 and rows[0].saves_line is None
    assert rows[0].line_available is False


def test_skip_deletes_stale_other_goalie_but_keeps_same_goalie(run):
    run(_slot())
    # Same goalie skipped (e.g. no model data): row untouched.
    _, rows = run(_slot(predict=False, reason="no_db_goalie"))
    assert len(rows) == 1
    # Different known goalie skipped: the old starter's row is stale.
    _, rows = run(
        _slot(
            goalie_id=8480947, name="K. Lankinen", predict=False, reason="no_db_goalie"
        )
    )
    assert rows == []
    # Unknown starter (no id): nothing to delete, nothing written.
    run(_slot())
    _, rows = run(
        _slot(goalie_id=None, name=None, predict=False, reason="starter_unconfirmed")
    )
    assert len(rows) == 1


def test_markets_passed_to_odds(run):
    run(_slot(), odds_markets="player_total_saves")
    assert run.state["markets"] == ["player_total_saves"]


def test_find_goalie_line_initial_fallback():
    lines = {"Leevi Merilainen": {"line": 24.5}}
    assert dp.find_goalie_line(lines, None, "L. Meriläinen") == {"line": 24.5}
    assert dp.find_goalie_line(lines, "Leevi Meriläinen", "x") == {"line": 24.5}
    assert dp.find_goalie_line(lines, None, "K. Merilainen") == {}
    assert dp.find_goalie_line({}, "A B", "A. B") == {}


def test_opponent_strength_fallback_has_four_values(monkeypatch):
    """No team-stats row: league averages, same 4-tuple the model unpacks."""
    from unittest.mock import MagicMock

    from app.services.etl.nhl import goalie_saves_model as gsm

    fake = MagicMock()
    fake.query.return_value.filter_by.return_value.first.return_value = None
    monkeypatch.setattr(gsm, "db_session", fake)
    assert gsm.get_opponent_offensive_strength("Vancouver") == (3.0, 0.10, 1.0, 3.0)
