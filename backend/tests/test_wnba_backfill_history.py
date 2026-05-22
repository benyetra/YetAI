from datetime import date
from unittest.mock import MagicMock, patch

from app.services.etl.wnba import backfill_wnba_history as bw


def test_backfill_one_season_writes_one_row_per_player_game(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.backfill_wnba_history.SessionLocal", lambda: mock_db
    )

    # One game, two box-score rows (one per player)
    games_payload = [
        {
            "GAME_ID": "1022500001",
            "GAME_DATE": "2025-05-16",
            "TEAM_ID": 1611661315,
            "MATCHUP": "NYL vs. LVA",
        }
    ]
    boxscore_payload = [
        {
            "PLAYER_ID": 100,
            "PLAYER_NAME": "P1",
            "TEAM_ID": 1611661315,
            "MIN": "30:00",
            "PTS": 20,
            "AST": 5,
            "REB": 7,
            "STL": 1,
            "BLK": 1,
            "FG3M": 2,
            "FG3A": 5,
            "FGM": 7,
            "FGA": 15,
            "FG_PCT": 0.467,
            "FG3_PCT": 0.4,
            "FT_PCT": 0.8,
            "FTM": 4,
            "FTA": 5,
            "OREB": 2,
            "DREB": 5,
            "TOV": 2,
            "PF": 3,
            "PLUS_MINUS": 5,
        },
        {
            "PLAYER_ID": 200,
            "PLAYER_NAME": "P2",
            "TEAM_ID": 1611661319,
            "MIN": "25:00",
            "PTS": 12,
            "AST": 3,
            "REB": 4,
            "STL": 0,
            "BLK": 0,
            "FG3M": 1,
            "FG3A": 3,
            "FGM": 4,
            "FGA": 10,
            "FG_PCT": 0.4,
            "FG3_PCT": 0.333,
            "FT_PCT": 1.0,
            "FTM": 3,
            "FTA": 3,
            "OREB": 1,
            "DREB": 3,
            "TOV": 1,
            "PF": 2,
            "PLUS_MINUS": -5,
        },
    ]

    with (
        patch(
            "app.services.etl.wnba.backfill_wnba_history._fetch_games_for_season"
        ) as gf,
        patch("app.services.etl.wnba.backfill_wnba_history._fetch_boxscore") as bf,
        patch(
            "app.services.etl.wnba.backfill_wnba_history.upsert_many",
            side_effect=lambda _db, _model, rows, **kwargs: len(rows),
        ),
    ):
        gf.return_value = games_payload
        bf.return_value = boxscore_payload
        result = bw.run(seasons=["2025"])

    assert result["status"] == "ok"
    assert result["rows_written"] == 2


def test_backfill_skips_games_with_no_boxscore(monkeypatch):
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.backfill_wnba_history.SessionLocal", lambda: mock_db
    )
    with (
        patch(
            "app.services.etl.wnba.backfill_wnba_history._fetch_games_for_season"
        ) as gf,
        patch("app.services.etl.wnba.backfill_wnba_history._fetch_boxscore") as bf,
    ):
        gf.return_value = [
            {
                "GAME_ID": "x",
                "GAME_DATE": "2025-05-16",
                "TEAM_ID": 1,
                "MATCHUP": "A vs B",
            }
        ]
        bf.return_value = []
        with patch("app.services.etl.wnba.backfill_wnba_history.upsert_many") as um:
            result = bw.run(seasons=["2025"])
    assert result["rows_written"] == 0
    um.assert_not_called()


def test_backfill_idempotent_on_rerun(monkeypatch):
    """Re-running upserts the same player-game rows without inflating row counts."""
    mock_db = MagicMock(name="Session")
    monkeypatch.setattr(
        "app.services.etl.wnba.backfill_wnba_history.SessionLocal", lambda: mock_db
    )
    games_payload = [
        {
            "GAME_ID": "1",
            "GAME_DATE": "2025-05-16",
            "TEAM_ID": 1611661315,
            "MATCHUP": "NYL vs. LVA",
        },
        {
            "GAME_ID": "1",
            "GAME_DATE": "2025-05-16",
            "TEAM_ID": 1611661319,
            "MATCHUP": "LVA @ NYL",
        },
    ]
    boxscore_payload = [
        {
            "PLAYER_ID": 100,
            "PLAYER_NAME": "P1",
            "TEAM_ID": 1611661315,
            "MIN": "30:00",
            "PTS": 20,
            "AST": 5,
            "REB": 7,
            "STL": 1,
            "BLK": 1,
            "FG3M": 2,
            "FG3A": 5,
            "FGM": 7,
            "FGA": 15,
            "FG_PCT": 0.467,
            "FG3_PCT": 0.4,
            "FT_PCT": 0.8,
            "FTM": 4,
            "FTA": 5,
            "OREB": 2,
            "DREB": 5,
            "TOV": 2,
            "PF": 3,
            "PLUS_MINUS": 5,
        },
    ]
    with (
        patch(
            "app.services.etl.wnba.backfill_wnba_history._fetch_games_for_season"
        ) as gf,
        patch("app.services.etl.wnba.backfill_wnba_history._fetch_boxscore") as bf,
        patch(
            "app.services.etl.wnba.backfill_wnba_history.upsert_many",
            side_effect=lambda _db, _model, rows, **kwargs: len(rows),
        ) as um,
    ):
        gf.return_value = games_payload
        bf.return_value = boxscore_payload
        r1 = bw.run(seasons=["2025"])
        r2 = bw.run(seasons=["2025"])
    assert r1["rows_written"] == 1
    assert r2["rows_written"] == 1
    assert um.call_count == 2
