from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import _boxscore_fetch as bf


def test_fetch_traditional_boxscore_passes_timeout():
    with patch(
        "app.services.etl.wnba._boxscore_fetch.boxscoretraditionalv2.BoxScoreTraditionalV2"
    ) as cls:
        instance = MagicMock()
        instance.get_normalized_dict.return_value = {"PlayerStats": []}
        cls.return_value = instance
        bf.fetch_traditional_boxscore("1022400001", profile="backfill")
    cls.assert_called_once_with(game_id="1022400001", timeout=(20, 120))


def test_advanced_fields_maps_usg_ortg_pace():
    adv = {
        "USG_PCT": 0.25,
        "AST_PCT": 0.15,
        "OFF_RATING": 110.0,
        "DEF_RATING": 98.0,
        "PACE": 95.5,
        "POSS": 42,
        "NET_RATING": 12.0,
        "EFG_PCT": 0.55,
        "TS_PCT": 0.6,
    }
    fields = bf.advanced_fields_from_row(adv)
    assert fields["usage_percentage"] == 0.25
    assert fields["assist_percentage"] == 0.15
    assert fields["offensive_rating"] == 110.0
    assert fields["defensive_rating"] == 98.0
    assert fields["pace"] == 95.5
    assert "effective_field_goal_percentage" not in fields
    assert "true_shooting_percentage" not in fields


def test_player_game_row_derives_efg_from_traditional_not_advanced():
    trad = {
        "PLAYER_ID": 100,
        "TEAM_ID": 1,
        "PTS": 20,
        "FGM": 7,
        "FGA": 15,
        "FG3M": 2,
        "FG3A": 5,
        "FG_PCT": 0.467,
        "FG3_PCT": 0.4,
        "FTM": 4,
        "FTA": 5,
        "FT_PCT": 0.8,
        "MIN": "30:00",
        "OREB": 1,
        "DREB": 4,
        "REB": 5,
        "AST": 3,
        "TOV": 2,
        "STL": 1,
        "BLK": 0,
        "PF": 2,
        "PLUS_MINUS": 4,
    }
    adv = {"USG_PCT": 0.3, "EFG_PCT": 0.99, "TS_PCT": 0.99}
    row = bf.player_game_row_from_boxscore(
        trad,
        game_date=date(2025, 5, 16),
        opponent_team_id=2,
        home_game=True,
        adv_row=adv,
    )
    assert row["usage_percentage"] == 0.3
    assert row["minutes"] == 30.0
    assert abs(row["effective_field_goal_percentage"] - (7 + 0.5 * 2) / 15) < 1e-6
    assert row["effective_field_goal_percentage"] != 0.99
