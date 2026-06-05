"""Admin game-lines odds enrichment for bet-entry pickers."""

from types import SimpleNamespace

from app.services.admin_game_lines_odds import (
    enrich_games_with_pred_lines,
    game_has_betting_markets,
    games_from_pred_lines,
)


def test_game_has_betting_markets_true_when_spreads_present():
    game = {
        "bookmakers": [{"markets": [{"key": "spreads", "outcomes": [{"name": "A"}]}]}]
    }
    assert game_has_betting_markets(game) is True


def test_game_has_betting_markets_false_when_empty():
    assert game_has_betting_markets({"bookmakers": []}) is False


def test_enrich_attaches_consensus_from_row(monkeypatch):
    row = SimpleNamespace(
        game_date=__import__("datetime").date(2026, 6, 4),
        game_time=None,
        odds_api_event_id="evt-1",
        home_team_name="Indiana Fever",
        away_team_name="Atlanta Dream",
        spread_home=-1.5,
        spread_away=1.5,
        spread_home_odds=-110,
        spread_away_odds=-110,
        moneyline_home=-120,
        moneyline_away=100,
        total=170.0,
        over_odds=-110,
        under_odds=-110,
        last_updated=None,
    )

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def order_by(self, *args):
            return self

        def first(self):
            return row

    class FakeSession:
        def query(self, model):
            return FakeQuery()

        def close(self):
            pass

    monkeypatch.setattr(
        "app.core.database.SessionLocal",
        lambda: FakeSession(),
    )

    games = [
        {
            "id": "evt-1",
            "home_team": "Indiana Fever",
            "away_team": "Atlanta Dream",
            "bookmakers": [],
        }
    ]
    out = enrich_games_with_pred_lines("basketball_wnba", games)
    assert game_has_betting_markets(out[0])


def test_games_from_pred_lines_unknown_sport_returns_empty():
    assert games_from_pred_lines("soccer_epl") == []
