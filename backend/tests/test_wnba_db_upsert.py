from unittest.mock import MagicMock

from app.services.etl.wnba._db_upsert import upsert_many
from app.models.predictions_models import WNBATeamRoster


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
