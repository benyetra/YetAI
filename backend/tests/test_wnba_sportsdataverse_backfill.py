from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import backfill_wnba_sportsdataverse as sdv
from app.services.etl.wnba._player_id_cache import (
    cache_key,
    normalize_player_name,
    resolve_player_id,
)


def test_normalize_player_name_strips_punctuation():
    assert normalize_player_name("A'ja Wilson") == "aja wilson"


def test_resolve_player_id_from_cache():
    caches = {2024: {cache_key(1611661319, "A'ja Wilson"): 1629477}}
    pid = resolve_player_id(
        season=2024,
        team_id=1611661319,
        athlete_display_name="A'ja Wilson",
        caches=caches,
    )
    assert pid == 1629477


def test_run_requires_player_id_cache_by_default():
    with patch.object(sdv, "cache_path") as cp:
        cp.return_value.exists.return_value = False
        result = sdv.run(seasons=[2024], require_cache=True)
    assert result["status"] == "error"
    assert result["reason"] == "missing_player_id_cache"


def test_row_to_upsert_handles_pandas_na():
    import pandas as pd

    row = {
        "game_date": date(2024, 5, 16),
        "points": pd.NA,
        "field_goals_attempted": None,
        "minutes": 12.0,
        "assists": 1,
        "rebounds": 2,
    }
    out = sdv._row_to_upsert(
        row,
        player_id=100,
        opponent_team_id=200,
        home_game=False,
    )
    assert out["points"] is None
    assert out["fg_attempts"] is None
    assert out["minutes"] == 12.0


def test_row_to_upsert_derives_shooting():
    row = {
        "game_date": date(2024, 5, 16),
        "points": 20,
        "field_goals_made": 7,
        "field_goals_attempted": 15,
        "three_point_field_goals_made": 2,
        "three_point_field_goals_attempted": 5,
        "free_throws_made": 4,
        "free_throws_attempted": 5,
        "minutes": 30.0,
        "assists": 3,
        "rebounds": 5,
        "turnovers": 1,
        "steals": 0,
        "blocks": 0,
        "fouls": 2,
        "plus_minus": 4,
        "offensive_rebounds": 1,
        "defensive_rebounds": 4,
    }
    out = sdv._row_to_upsert(
        row,
        player_id=100,
        opponent_team_id=200,
        home_game=True,
    )
    assert out["player_id"] == 100
    assert out["effective_field_goal_percentage"] is not None
    assert "usage_percentage" not in out
