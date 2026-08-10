from app.services.etl.nfl.team_names import normalize_team_name
from app.services.etl.nfl.update_game_lines import (
    SPORT,
    _parse_odds,
    normalize_game_teams,
)


def test_sport_key_is_nfl():
    assert SPORT == "americanfootball_nfl"


def test_normalize_game_teams_uses_canonical_names():
    home, away = normalize_game_teams("LA Rams", "Washington Football Team")
    assert home == "Los Angeles Rams"
    assert away == "Washington Commanders"
    assert normalize_team_name("LA Rams") == home


def test_parse_odds_extracts_spread_and_total():
    odds_data = {
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "spreads",
                        "outcomes": [
                            {
                                "name": "Kansas City Chiefs",
                                "point": -3.5,
                                "price": -110,
                            },
                            {"name": "Baltimore Ravens", "point": 3.5, "price": -110},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "point": 47.5, "price": -105},
                            {"name": "Under", "point": 47.5, "price": -115},
                        ],
                    },
                ],
            }
        ]
    }
    parsed = _parse_odds(odds_data, "Kansas City Chiefs", "Baltimore Ravens")
    assert parsed["spread_home"] == -3.5
    assert parsed["total"] == 47.5
    assert parsed["bookmaker"] == "FanDuel"
