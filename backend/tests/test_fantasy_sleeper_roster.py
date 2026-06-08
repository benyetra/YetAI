"""Tests for Sleeper roster helpers used by trade analyzer routes."""

from app.services.fantasy_sleeper_roster import format_sleeper_player_row
from app.services.fantasy_trade_value import calculate_deterministic_trade_value


def test_format_sleeper_player_row_respects_scoring_type():
    player = {
        "first_name": "Test",
        "last_name": "Receiver",
        "position": "WR",
        "team": "KC",
        "age": 26,
    }
    ppr_row = format_sleeper_player_row("wr-42", player, scoring_type="ppr")
    standard_row = format_sleeper_player_row("wr-42", player, scoring_type="standard")

    assert ppr_row["trade_value"] == calculate_deterministic_trade_value(
        player, scoring_type="ppr"
    )
    assert standard_row["trade_value"] == calculate_deterministic_trade_value(
        player, scoring_type="standard"
    )
    assert ppr_row["trade_value"] != standard_row["trade_value"]
    assert ppr_row["name"] == "Test Receiver"
    assert ppr_row["position"] == "WR"
