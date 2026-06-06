"""MLB admin fallbacks from pred_game_projections and strikeout projections."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.mlb_admin_odds_fallback import (
    bookmakers_from_game_projection,
    event_id_for_projection,
    games_from_pred_game_projections,
    mlb_player_props_from_projections,
)


def test_bookmakers_from_game_projection_builds_h2h_spread_totals():
    row = SimpleNamespace(
        home_team="Philadelphia Phillies",
        away_team="Colorado Rockies",
        market_spread=-1.5,
        market_home_ml=-150,
        market_away_ml=130,
        market_total=8.5,
        updated_at=None,
        created_at=None,
    )
    bookmakers = bookmakers_from_game_projection(row)
    assert len(bookmakers) == 1
    keys = {m["key"] for m in bookmakers[0]["markets"]}
    assert keys == {"spreads", "h2h", "totals"}


def test_event_id_for_projection_slugifies_teams():
    row = SimpleNamespace(
        date=date(2026, 6, 5),
        home_team="Philadelphia Phillies",
        away_team="Colorado Rockies",
    )
    assert (
        event_id_for_projection(row)
        == "mlb-2026-06-05-Colorado-Rockies-at-Philadelphia-Phillies"
    )


def test_mlb_player_props_from_projections_returns_strikeouts():
    from app.models.predictions_models import (
        GameProjections,
        Pitcher,
        StrikeoutProjections,
    )

    projection = SimpleNamespace(
        date=date(2026, 6, 5),
        game_id=42,
        home_team="Philadelphia Phillies",
        away_team="Colorado Rockies",
    )
    strikeout_row = SimpleNamespace(
        pitcher_id="123",
        pitcher_name="Test Pitcher",
        fanduel_line=6.5,
    )
    pitcher_row = SimpleNamespace(
        pitcher_id="123",
        name="Test Pitcher",
        fanduel_point=6.5,
        fanduel_price=-115,
    )

    db = MagicMock()

    def query_side_effect(model):
        chain = MagicMock()
        if model is GameProjections:
            chain.filter.return_value.order_by.return_value.all.return_value = [
                projection
            ]
        elif model is StrikeoutProjections:
            chain.filter.return_value.all.return_value = [strikeout_row]
        elif model is Pitcher:
            chain.filter.return_value.all.return_value = [pitcher_row]
        else:
            chain.filter.return_value.all.return_value = []
        return chain

    db.query.side_effect = query_side_effect

    event_id = "mlb-2026-06-05-Colorado-Rockies-at-Philadelphia-Phillies"
    payload = mlb_player_props_from_projections(db, event_id=event_id)
    assert payload is not None
    assert "pitcher_strikeouts" in payload["markets"]
    assert payload["markets"]["pitcher_strikeouts"]["players"][0]["line"] == 6.5


def test_games_from_pred_game_projections_filters_rows_without_markets(monkeypatch):
    row_with_markets = SimpleNamespace(
        date=date(2026, 6, 5),
        game_time=None,
        home_team="Team A",
        away_team="Team B",
        market_spread=-1.5,
        market_home_ml=-120,
        market_away_ml=100,
        market_total=9.0,
        updated_at=None,
        created_at=None,
    )
    row_without_markets = SimpleNamespace(
        date=date(2026, 6, 6),
        game_time=None,
        home_team="Team C",
        away_team="Team D",
        market_spread=None,
        market_home_ml=None,
        market_away_ml=None,
        market_total=None,
        updated_at=None,
        created_at=None,
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return [row_with_markets, row_without_markets]

    class FakeSession:
        def query(self, model):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(
        "app.core.database.SessionLocal",
        lambda: FakeSession(),
    )

    games = games_from_pred_game_projections()
    assert len(games) == 1
    assert games[0]["home_team"] == "Team A"
