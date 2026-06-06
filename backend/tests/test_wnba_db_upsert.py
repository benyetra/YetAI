from unittest.mock import MagicMock

from app.services.etl.wnba._db_upsert import upsert_many
from app.models.predictions_models import (
    WNBARecentGames,
    WNBATeamRoster,
    WNBATodayActivePlayers,
)


def test_upsert_many_noop_on_empty():
    session = MagicMock()
    assert (
        upsert_many(session, WNBATeamRoster, [], conflict_keys=["team_id", "player_id"])
        == 0
    )
    session.execute.assert_not_called()


def test_upsert_many_executes_insert_statement():
    session = MagicMock()
    rows = [
        {
            "team_id": 1,
            "player_id": 10,
            "player_name": "Test Player",
            "last_updated": None,
            "position": "G",
        }
    ]
    count = upsert_many(
        session,
        WNBATeamRoster,
        rows,
        conflict_keys=["team_id", "player_id"],
    )
    assert count == 1
    session.execute.assert_called_once()


def test_upsert_many_dedupes_duplicate_conflict_keys():
    """Postgres rejects ON CONFLICT when the same key appears twice in one batch."""
    session = MagicMock()
    rows = [
        {
            "player_id": 99,
            "game_date": "2026-06-06",
            "player_name": "First",
            "team_id": 1,
        },
        {
            "player_id": 99,
            "game_date": "2026-06-06",
            "player_name": "Second",
            "team_id": 2,
        },
    ]
    count = upsert_many(
        session,
        WNBATodayActivePlayers,
        rows,
        conflict_keys=["player_id", "game_date"],
    )
    assert count == 1
    session.execute.assert_called_once()


def test_upsert_many_normalizes_inconsistent_row_keys():
    """Mixed batches must not raise CompileError on nullable shooting columns."""
    session = MagicMock()
    rows = [
        {
            "player_id": 1,
            "game_date": "2021-05-01",
            "opponent_team_id": 2,
            "true_shooting_percentage": 0.55,
        },
        {
            "player_id": 2,
            "game_date": "2021-05-01",
            "opponent_team_id": 2,
            # missing true_shooting_percentage — common for DNP / zero-attempt rows
        },
    ]
    count = upsert_many(
        session,
        WNBARecentGames,
        rows,
        conflict_keys=["player_id", "game_date"],
    )
    assert count == 2
    session.execute.assert_called_once()
