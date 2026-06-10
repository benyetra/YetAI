"""Unit tests for player prop display enrichment."""

from app.services.player_prop_projection_display import (
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
