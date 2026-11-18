"""NHL: the morning run projects only today's games; the pregame refresh is keyed to start
time; one live goalie row per (game_date, team)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import NHLGoaliePredictions
from app.services.etl.nhl import daily_predictions as dp

TODAY = date(2026, 11, 14)


def _g(gid, utc, state="FUT"):
    return {"id": gid, "gameState": state, "startTimeUTC": utc}


def utc(h, m=0, day=14):
    return datetime(2026, 11, day, tzinfo=timezone.utc) + timedelta(hours=h, minutes=m)


def test_morning_run_projects_only_todays_games():
    week = {
        "gameWeek": [
            {"games": [_g(1, "2026-11-14T18:00:00Z"), _g(2, "2026-11-15T00:00:00Z")]},
            {"games": [_g(3, "2026-11-15T18:00:00Z")]},  # tomorrow noon ET
            {"games": [_g(4, "2026-11-20T00:00:00Z")]},
        ]
    }
    seen = {}

    def goalies(games, events):
        seen["games"] = [g["id"] for g in games]
        return 0

    with (
        patch.object(dp, "now_eastern") as now,
        patch.object(dp.NHLAPIClient, "get_schedule", return_value=week),
        patch.object(dp, "get_nhl_events_from_odds_api", return_value=[]),
        patch.object(dp, "update_nhl_stats", return_value=True),
        patch.object(dp, "generate_goalie_predictions", side_effect=goalies),
        patch.object(dp, "generate_player_predictions", return_value=0),
        patch.object(dp, "generate_team_totals_predictions", return_value=0),
        patch.object(dp.time, "sleep"),
    ):
        now.return_value.date.return_value = TODAY
        out = dp._run_daily_core()
    # 1 is 1pm ET today; 2 is 7pm ET today (00:00Z Nov 15); 3 and 4 are later days.
    assert seen["games"] == [1, 2]
    assert out["games_scheduled"] == 2


GAMES = [
    _g(1, "2026-11-14T17:30:00Z"),  # 12:30 ET matinee
    _g(2, "2026-11-15T00:00:00Z"),  # 19:00 ET
    _g(3, "2026-11-15T03:00:00Z"),  # 22:00 ET
    _g(4, "2026-11-14T15:00:00Z", state="LIVE"),
]


def _ids(now):
    return [g["id"] for g in dp.games_to_refresh(GAMES, TODAY, now)]


def test_matinee_refreshed_at_1045():
    assert _ids(utc(15, 45)) == [1]  # 10:45 ET: 12:30 in window, 19:00 is 8h away


def test_evening_game_refreshed_at_1645_and_started_matinee_skipped():
    # 16:45 ET: the 12:30 game started, 19:00 is 2h15 away, 22:00 is 5h15 away.
    assert _ids(utc(21, 45)) == [2]


def test_late_game_refreshed_at_1845_and_window_edge_inclusive():
    assert _ids(utc(23, 45)) == [2, 3]  # 18:45 ET: 19:00 and 22:00 (3h15 exactly)


def test_started_by_clock_is_skipped_even_if_state_is_fut():
    assert _ids(utc(0, 5, day=15)) == [3]  # 19:05 ET: the 19:00 game has started


def test_every_game_gets_a_refresh_within_3h_of_start():
    # Beat hours 10,12,14,16,18,20 at :45 ET (UTC-5).
    beats = [utc(h + 5, 45) for h in (10, 12, 14, 16, 18, 20)]
    for g in GAMES[:3]:
        assert any(g["id"] in _ids(b) for b in beats), g["id"]


@pytest.fixture
def session(monkeypatch):
    eng = create_engine("sqlite://")
    NHLGoaliePredictions.__table__.create(eng)
    s = sessionmaker(bind=eng)()
    return s


def _row(goalie_id, scratch=False, team_id=23):
    return NHLGoaliePredictions(
        game_date=TODAY,
        goalie_id=goalie_id,
        goalie_name="G",
        team_id=team_id,
        team_name="T",
        opponent_team_id=3,
        opponent_team_name="O",
        predicted_saves=25.0,
        predicted_shots_against=27.0,
        predicted_save_pct=0.9,
        was_scratch=scratch,
    )


def test_unique_index_one_live_row_but_scratched_history_allowed(session):
    session.add_all([_row(1, scratch=True), _row(2)])
    session.commit()
    session.add(_row(3, scratch=True))  # more history is fine
    session.add(_row(9, team_id=24))  # other team is fine
    session.commit()
    session.add(_row(4))  # second live row for the same team/date
    with pytest.raises(IntegrityError):
        session.commit()
