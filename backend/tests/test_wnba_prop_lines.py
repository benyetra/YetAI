"""Tests for WNBA Odds API player-prop line attachment."""

from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba._prop_lines import (
    EDGE_THRESHOLDS,
    attach_prop_market_fields,
    lookup_wnba_event_id,
    resolve_wnba_event_id,
)


def test_lookup_wnba_event_id_matches_stored_game():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        ("evt-lynx-gsv", "Minnesota Lynx", "Golden State Valkyries"),
        ("evt-fever-dream", "Indiana Fever", "Atlanta Dream"),
    ]
    eid = lookup_wnba_event_id(
        db,
        date(2026, 6, 4),
        "Golden State Valkyries",
        "Minnesota Lynx",
    )
    assert eid == "evt-lynx-gsv"


def test_resolve_wnba_event_id_prefers_db_over_events_api():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        ("evt-db", "Indiana Fever", "Atlanta Dream"),
    ]
    with patch(
        "app.services.etl.wnba._prop_lines.get_event_id_for_game",
        return_value="evt-live",
    ) as live:
        eid = resolve_wnba_event_id(
            db, date(2026, 6, 4), "Indiana Fever", "Atlanta Dream"
        )
    assert eid == "evt-db"
    live.assert_not_called()


def test_attach_prop_market_fields_sets_line_and_over():
    row = {
        "market_line": None,
        "edge": None,
        "recommendation": "NO_PLAY",
    }
    db = MagicMock()
    with patch(
        "app.services.etl.wnba._prop_lines.fetch_fanduel_prop_for_player",
        return_value=(18.5, "o"),
    ) as fetch:
        attached = attach_prop_market_fields(
            row,
            db=db,
            game_date=date(2026, 6, 4),
            team_name="Indiana Fever",
            opponent_team_name="Atlanta Dream",
            player_name="Caitlin Clark",
            stat="points",
            projected=22.0,
            event_id="evt-1",
        )
    assert attached is True
    assert row["market_line"] == 18.5
    assert row["edge"] == 3.5
    assert row["recommendation"] == "OVER"
    fetch.assert_called_once()
    assert fetch.call_args.kwargs["event_id"] == "evt-1"
    assert "draftkings" in fetch.call_args.kwargs["bookmakers"]


def test_attach_prop_market_fields_no_play_when_edge_below_threshold():
    row = {"market_line": None, "edge": None, "recommendation": "NO_PLAY"}
    db = MagicMock()
    with patch(
        "app.services.etl.wnba._prop_lines.fetch_fanduel_prop_for_player",
        return_value=(8.0, "o"),
    ):
        attach_prop_market_fields(
            row,
            db=db,
            game_date=date(2026, 6, 4),
            team_name="Minnesota Lynx",
            opponent_team_name="Golden State Valkyries",
            player_name="Napheesa Collier",
            stat="assists",
            projected=8.3,
            event_id="evt-2",
        )
    assert row["market_line"] == 8.0
    assert row["edge"] == 0.3
    assert row["recommendation"] == "NO_PLAY"
    assert EDGE_THRESHOLDS["assists"] == 0.5


def test_attach_prop_market_fields_leaves_row_when_no_line():
    row = {"market_line": None, "recommendation": "NO_PLAY"}
    db = MagicMock()
    with patch(
        "app.services.etl.wnba._prop_lines.fetch_fanduel_prop_for_player",
        return_value=(None, None),
    ):
        assert (
            attach_prop_market_fields(
                row,
                db=db,
                game_date=date(2026, 6, 4),
                team_name="Indiana Fever",
                opponent_team_name="Atlanta Dream",
                player_name="Unknown Player",
                stat="points",
                projected=10.0,
                event_id="evt-1",
            )
            is False
        )
    assert row["market_line"] is None
