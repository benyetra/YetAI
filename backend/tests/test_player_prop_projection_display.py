"""Unit tests for player prop display enrichment."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.player_prop_projection_display import (
    attach_mlb_batter_team_opponent,
    attach_team_opponent_fields,
    enrich_nba_prop_row,
    enrich_nhl_prop_row,
    enrich_strikeout_display_row,
    enrich_wnba_prop_row,
    prop_confidence_pct,
    value_tier_for_play,
)


def test_prop_confidence_scales_with_edge():
    assert prop_confidence_pct(1.5, "points") == 50.0
    assert prop_confidence_pct(3.0, "points") == 100.0


def test_value_tier_strong_on_double_threshold():
    assert value_tier_for_play("OVER", 2.1, 1.0) == "strong"
    assert value_tier_for_play("OVER", 1.2, 1.0) == "lean"
    assert value_tier_for_play(None, 2.0, 1.0) is None


def test_enrich_nba_prop_row_adds_confidence_and_tier():
    row = enrich_nba_prop_row(
        {
            "player_name": "Test",
            "projected_points": 28.0,
            "fanduel_line": 25.5,
            "fanduel_over_under": "o",
        },
        "points",
    )
    assert row["edge"] == 2.5
    assert row["recommendation"] == "OVER"
    assert row["pick_confidence"] == 83.3
    assert row["value_tier"] == "strong"


def test_enrich_wnba_prop_row_preserves_recommendation():
    row = enrich_wnba_prop_row(
        {
            "projected_points": 15.0,
            "market_line": 13.5,
            "recommendation": "OVER",
        },
        "points",
    )
    assert row["edge"] == 1.5
    assert row["confidence_score"] == 50.0
    assert row["value_tier"] == "lean"


def test_enrich_nhl_prop_row_uses_edge_category():
    row = enrich_nhl_prop_row(
        {
            "predicted_saves": 32.0,
            "saves_line": 28.5,
            "betting_recommendation": "OVER 28.5",
            "edge_category": "HIGH",
            "confidence": 88.0,
        },
        "saves",
    )
    assert row["recommendation"] == "OVER"
    assert row["value_tier"] == "strong"


def test_enrich_strikeout_display_row_value_tier():
    row = enrich_strikeout_display_row(
        {
            "k_edge": 1.6,
            "pick_confidence": 72.0,
            "yetai_pick": "over",
        }
    )
    assert row["value_tier"] == "strong"
    assert row["confidence_score"] == 72.0


def test_attach_team_opponent_fields_normalizes_mlb_aliases():
    rows = attach_team_opponent_fields(
        [{"player_name": "Judge", "team": "NYY", "opponent": "BOS"}]
    )
    assert rows[0]["team_name"] == "NYY"
    assert rows[0]["opponent_team_name"] == "BOS"


def test_attach_mlb_batter_team_opponent_joins_hitter():
    from datetime import datetime

    db = MagicMock()
    hitter = SimpleNamespace(
        player_id="592450",
        team="NYY",
        opponent="BOS",
        game_time=datetime(2026, 8, 5, 19, 0, 0),
    )

    query = MagicMock()
    db.query.return_value = query
    query.filter.return_value = query
    query.all.return_value = [hitter]

    rows = attach_mlb_batter_team_opponent(
        db,
        [
            {
                "batter_id": 592450,
                "batter_name": "Judge",
                "date": date(2026, 8, 5),
                "projected_hits": 2,
            }
        ],
    )
    assert rows[0]["team_name"] == "NYY"
    assert rows[0]["opponent_team_name"] == "BOS"
