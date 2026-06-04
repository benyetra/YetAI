"""WNBA admin fallbacks from pred_wnba_game_lines and prop projections."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.wnba_admin_odds_fallback import (
    bookmakers_from_game_line,
    wnba_player_props_from_projections,
)


def test_bookmakers_from_game_line_builds_spread_h2h_totals():
    row = SimpleNamespace(
        home_team_name="Minnesota Lynx",
        away_team_name="Golden State Valkyries",
        spread_home=-4.5,
        spread_away=4.5,
        spread_home_odds=-110,
        spread_away_odds=-110,
        moneyline_home=-180,
        moneyline_away=150,
        total=162.5,
        over_odds=-108,
        under_odds=-112,
        last_updated=None,
    )
    bookmakers = bookmakers_from_game_line(row)
    assert len(bookmakers) == 1
    keys = {m["key"] for m in bookmakers[0]["markets"]}
    assert keys == {"spreads", "h2h", "totals"}
    spreads = next(m for m in bookmakers[0]["markets"] if m["key"] == "spreads")
    assert len(spreads["outcomes"]) == 2


def test_wnba_player_props_from_projections_filters_by_event():
    from datetime import date

    from app.models.predictions_models import WNBAGameLines, WNBAPointsProjections

    line = SimpleNamespace(
        odds_api_event_id="evt-1",
        game_date=date(2026, 6, 4),
        home_team_name="Minnesota Lynx",
        away_team_name="Golden State Valkyries",
    )
    prop_row = SimpleNamespace(
        player_id=1,
        player_name="Player A",
        market_line=18.5,
        opponent_team_name="Golden State Valkyries",
    )

    db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is WNBAGameLines:
            chain.filter.return_value.order_by.return_value.first.return_value = line
        elif model is WNBAPointsProjections:
            chain.filter.return_value.all.return_value = [prop_row]
        else:
            chain.filter.return_value.all.return_value = []
        return chain

    db.query.side_effect = query_side_effect

    payload = wnba_player_props_from_projections(db, event_id="evt-1")
    assert payload is not None
    assert "player_points" in payload["markets"]
    assert payload["markets"]["player_points"]["players"][0]["line"] == 18.5
