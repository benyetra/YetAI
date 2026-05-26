"""Backtest starter pitcher ID resolution from boxscore."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.services.etl.mlb.backtest.data_builder import HistoricalDataBuilder


def _game(home_pid=None, away_pid=None):
    return SimpleNamespace(
        game_id=717001,
        game_date="2024-09-15",
        home_pitcher_id=home_pid,
        away_pitcher_id=away_pid,
        home_id=119,
        away_id=120,
        home_name="LAD",
        away_name="SF",
        venue_name="Dodger Stadium",
    )


def _boxscore():
    return {
        "homePitchers": [543037, 999001],
        "awayPitchers": [605483],
        "ID543037": {"ip": "6.0", "k": 7},
        "ID999001": {"ip": "1.0", "k": 1},
        "ID605483": {"ip": "5.2", "k": 5},
        "homeBatters": [
            {"personId": 0, "name": "Home Batters"},
            *[{"personId": i} for i in range(1, 10)],
        ],
        "awayBatters": [
            {"personId": 0, "name": "Away Batters"},
            *[{"personId": i} for i in range(10, 19)],
        ],
    }


def test_starter_ids_from_boxscore_when_probables_missing():
    builder = HistoricalDataBuilder(cache_only=True)
    box = _boxscore()

    home_pid, away_pid, meta = builder._resolve_starter_ids(_game(), box)

    assert home_pid == 543037
    assert away_pid == 605483
    assert meta["home_from_boxscore"] is True
    assert meta["away_from_boxscore"] is True


def test_starter_ids_keep_schedule_probables():
    builder = HistoricalDataBuilder(cache_only=True)
    box = _boxscore()

    home_pid, away_pid, meta = builder._resolve_starter_ids(
        _game(home_pid=111, away_pid=222), box
    )

    assert home_pid == 111
    assert away_pid == 222
    assert meta["home_from_boxscore"] is False
    assert meta["away_from_boxscore"] is False


def test_reconstruct_lineup_reuses_boxscore():
    builder = HistoricalDataBuilder(cache_only=True)
    lineup = builder._reconstruct_lineup(717001, boxscore=_boxscore())

    assert lineup["home_lineup"] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert lineup["away_lineup"] == [10, 11, 12, 13, 14, 15, 16, 17, 18]


def test_reconstruct_pitcher_stats_from_game_log_splits():
    builder = HistoricalDataBuilder(cache_only=True)
    splits = [
        {
            "date": "2024-04-10",
            "stat": {
                "inningsPitched": "6.0",
                "earnedRuns": 2,
                "strikeOuts": 8,
                "baseOnBalls": 1,
                "hits": 4,
            },
        },
        {
            "date": "2024-05-20",
            "stat": {
                "inningsPitched": "5.0",
                "earnedRuns": 0,
                "strikeOuts": 6,
                "baseOnBalls": 2,
                "hits": 3,
            },
        },
        {
            "date": "2024-06-15",
            "stat": {
                "inningsPitched": "7.0",
                "earnedRuns": 1,
                "strikeOuts": 9,
                "baseOnBalls": 0,
                "hits": 5,
            },
        },
    ]

    with patch(
        "app.services.etl.mlb.backtest.data_builder.cached_api_call",
        return_value=splits,
    ):
        stats = builder._reconstruct_pitcher_stats(543037, 2024, date(2024, 6, 20))

    assert stats["n_starts"] == 3
    assert stats["ip"] == 18.0
    assert stats["k"] == 23
    assert stats["era"] > 0
    assert stats["last5_k9"] > 0
