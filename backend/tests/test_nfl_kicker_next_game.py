"""Kickers are projected for their next game, once, with its real kickoff."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.etl.nfl import kickers
from app.services.etl.nfl.collect_kicker_actuals import _find_prediction
from app.services.etl.nfl.venues import surface_type, venue_type


def _event(date_str, week):
    return {"date": date_str, "week": {"number": week}}


def test_upcoming_events_drop_games_already_played_this_week():
    # Tuesday after the Week 9 game: the helper's "current week" is still 9.
    events = [
        _event("2026-11-08T18:00Z", 9),
        _event("2026-11-22T18:00Z", 11),
        _event("2026-11-15T18:00Z", 10),
    ]
    upcoming = kickers.upcoming_events(events, now_utc=datetime(2026, 11, 10, 9, 30))
    assert [e["week"]["number"] for e in upcoming] == [10, 11]


def test_upcoming_events_skip_unreadable_dates():
    events = [{"date": "TBD"}, _event("2026-11-15T18:00Z", 10)]
    upcoming = kickers.upcoming_events(events, now_utc=datetime(2026, 11, 10))
    assert len(upcoming) == 1


def test_event_kickoff_is_converted_to_eastern():
    # Thanksgiving night game: 01:20 UTC Friday is 8:20 PM ET Thursday.
    kickoff = kickers.event_kickoff_eastern(_event("2026-11-27T01:20Z", 12))
    assert kickoff == datetime(2026, 11, 26, 20, 20)
    assert kickers.event_kickoff_eastern({"date": None}) is None


def test_venue_lookup_knows_sponsor_named_roofs_and_turf():
    assert venue_type("AT&T Stadium") == "dome"  # retractable
    assert venue_type("Ford Field") == "dome"
    assert venue_type("Caesars Superdome") == "dome"
    assert venue_type("Lambeau Field") == "outdoor"
    assert venue_type(None) == "outdoor"
    assert surface_type("MetLife Stadium") == "turf"
    assert surface_type("Arrowhead Stadium") == "grass"


def _save_payload(**overrides):
    payload = {
        "player_id": "42",
        "name": "Test Kicker",
        "team_id": 12,
        "team_name": "Chiefs",
        "venue_name": "Mercedes-Benz Stadium",
        "opponent_name": "Falcons",
        "game_time": datetime(2026, 11, 15, 13, 0),
        "projected_field_goals": 1.6,
        "venue_type": "dome",
        "surface_type": "turf",
    }
    payload.update(overrides)
    return payload


def test_rerun_updates_the_games_row_instead_of_keeping_the_first(monkeypatch):
    existing = SimpleNamespace(predicted_fg_made=1.2, game_date=None)
    added = []
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = existing
    session.add.side_effect = added.append
    monkeypatch.setattr(kickers, "db_session", session)

    kickers.save_kicker_data(_save_payload(projected_field_goals=2.1))

    assert existing.predicted_fg_made == 2.1
    assert existing.game_date == datetime(2026, 11, 15, 13, 0)
    assert existing.roof_type == "dome"
    assert not [o for o in added if o.__class__.__name__ == "KickerPredictions"]


def _pred(game_date, fgs, player_id="42", name="Test Kicker"):
    return SimpleNamespace(
        kicker_player_id=player_id,
        kicker_player_name=name,
        game_date=game_date,
        predicted_fg_made=fgs,
    )


def test_grading_uses_the_row_for_that_game_not_last_weeks():
    game_day = date(2026, 11, 15)
    historical = [
        _pred(datetime(2026, 11, 8, 13, 0), 1.1),  # previous week's game
        _pred(datetime(2026, 11, 15, 13, 0), 2.3),  # this game
        _pred(datetime(2026, 11, 22, 13, 0), 0.9),  # next week's
    ]
    pred, source, projected = _find_prediction(
        kicker_name="Test Kicker",
        kicker_id="42",
        game_date=game_day,
        historical=historical,
        current=[],
    )
    assert source == "historical"
    assert projected == 2.3


def test_grading_legacy_rows_takes_the_latest_made_before_the_game():
    # Legacy rows are dated the day after the run that wrote them.
    game_day = date(2026, 11, 15)
    historical = [
        _pred(datetime(2026, 11, 6, 4, 30), 1.0),
        _pred(datetime(2026, 11, 14, 4, 30), 1.5),
        _pred(datetime(2026, 11, 16, 4, 30), 1.8),  # Sunday-morning run
        _pred(datetime(2026, 11, 17, 4, 30), 9.9),  # written after the game
    ]
    _, _, projected = _find_prediction(
        kicker_name="Test Kicker",
        kicker_id="42",
        game_date=game_day,
        historical=historical,
        current=[],
    )
    assert projected == 1.8


def test_grading_ignores_rows_too_old_or_for_other_kickers():
    _, source, _ = _find_prediction(
        kicker_name="Test Kicker",
        kicker_id="42",
        game_date=date(2026, 11, 15),
        historical=[
            _pred(datetime(2026, 10, 25, 13, 0), 2.0),
            _pred(datetime(2026, 11, 15, 13, 0), 2.0, player_id="7", name="Other Guy"),
        ],
        current=[],
    )
    assert source is None
