"""Tests for WNBA Odds API player-prop line attachment."""

from unittest.mock import patch

from app.services.etl.wnba._prop_lines import (
    EDGE_THRESHOLDS,
    attach_prop_market_fields,
)


def test_attach_prop_market_fields_sets_line_and_over():
    row = {
        "market_line": None,
        "edge": None,
        "recommendation": "NO_PLAY",
    }
    with patch(
        "app.services.etl.wnba._prop_lines.fetch_fanduel_prop_for_player",
        return_value=(18.5, "o"),
    ):
        attached = attach_prop_market_fields(
            row,
            team_name="Indiana Fever",
            opponent_team_name="Atlanta Dream",
            player_name="Caitlin Clark",
            stat="points",
            projected=22.0,
        )
    assert attached is True
    assert row["market_line"] == 18.5
    assert row["edge"] == 3.5
    assert row["recommendation"] == "OVER"


def test_attach_prop_market_fields_no_play_when_edge_below_threshold():
    row = {"market_line": None, "edge": None, "recommendation": "NO_PLAY"}
    with patch(
        "app.services.etl.wnba._prop_lines.fetch_fanduel_prop_for_player",
        return_value=(8.0, "o"),
    ):
        attach_prop_market_fields(
            row,
            team_name="Minnesota Lynx",
            opponent_team_name="Golden State Valkyries",
            player_name="Napheesa Collier",
            stat="assists",
            projected=8.3,
        )
    assert row["market_line"] == 8.0
    assert row["edge"] == 0.3
    assert row["recommendation"] == "NO_PLAY"
    assert EDGE_THRESHOLDS["assists"] == 0.5


def test_attach_prop_market_fields_leaves_row_when_no_line():
    row = {"market_line": None, "recommendation": "NO_PLAY"}
    with patch(
        "app.services.etl.wnba._prop_lines.fetch_fanduel_prop_for_player",
        return_value=(None, None),
    ):
        assert (
            attach_prop_market_fields(
                row,
                team_name="Indiana Fever",
                opponent_team_name="Atlanta Dream",
                player_name="Unknown Player",
                stat="points",
                projected=10.0,
            )
            is False
        )
    assert row["market_line"] is None
