from unittest.mock import MagicMock, patch

from app.models.predictions_models import WNBAPlayerInjuryStatus, WNBATeamRoster
from app.services.etl.wnba import update_injury_status as uis


def _make_session_with_roster(player_id: int, player_name: str):
    mock_db = MagicMock(name="Session")
    roster = MagicMock()
    roster.player_id = player_id
    roster.player_name = player_name
    mock_db.query.return_value.filter.return_value.first.return_value = roster
    return mock_db, roster


def test_run_matches_roster_and_normalizes_status(monkeypatch):
    mock_db, _ = _make_session_with_roster(123, "A'ja Wilson")
    mock_db.query.return_value.filter.return_value.all.return_value = []
    monkeypatch.setattr(
        "app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = (
            [
                {
                    "player_name": "A'ja Wilson",
                    "team_name": "Las Vegas Aces",
                    "status": "Day-To-Day",
                    "injury_type": "ankle",
                },
            ],
            True,
        )
        with patch("app.services.etl.wnba.update_injury_status.upsert_many") as um:
            result = uis.run()

    assert result["matched"] == 1
    assert result["unmatched"] == 0
    assert result["cleared"] == 0
    row = um.call_args[0][2][0]
    assert row["player_id"] == 123
    assert row["status"] == "questionable"  # Day-To-Day → questionable
    assert row["injury_type"] == "ankle"


def test_run_skips_unmatched_player(monkeypatch):
    mock_db = MagicMock(name="Session")
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_db.query.return_value.filter.return_value.all.return_value = []
    monkeypatch.setattr(
        "app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = (
            [
                {
                    "player_name": "Unknown Player",
                    "team_name": "X",
                    "status": "Out",
                    "injury_type": None,
                },
            ],
            True,
        )
        result = uis.run()

    assert result["matched"] == 0
    assert result["unmatched"] == 1
    assert result["cleared"] == 0
    mock_db.execute.assert_not_called()


def test_unknown_status_defaults_to_out(monkeypatch):
    mock_db, _ = _make_session_with_roster(1, "P")
    mock_db.query.return_value.filter.return_value.all.return_value = []
    monkeypatch.setattr(
        "app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = (
            [
                {
                    "player_name": "P",
                    "team_name": "X",
                    "status": "Mystery",
                    "injury_type": None,
                }
            ],
            True,
        )
        with patch("app.services.etl.wnba.update_injury_status.upsert_many") as um:
            uis.run()

    assert um.call_args[0][2][0]["status"] == "out"


def test_clears_stale_injury_when_player_drops_off_feed(monkeypatch):
    mock_db, _ = _make_session_with_roster(1629477, "Sabrina Ionescu")
    stale = MagicMock()
    stale.player_id = 1629477
    stale.player_name = "Sabrina Ionescu"
    stale.status = "out"
    stale.injury_type = "ankle"

    query_mock = mock_db.query

    def query_side_effect(model):
        q = MagicMock()
        if model is WNBATeamRoster:
            q.filter.return_value.first.return_value = None
        elif model is WNBAPlayerInjuryStatus:
            q.filter.return_value.all.return_value = [stale]
        return q

    query_mock.side_effect = query_side_effect
    monkeypatch.setattr(
        "app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = ([], True)
        with patch("app.services.etl.wnba.update_injury_status.upsert_many"):
            result = uis.run()

    assert result["cleared"] == 1
    assert stale.status == "healthy"
    assert stale.injury_type is None
    assert stale.games_missed == 0
    mock_db.commit.assert_called_once()


def test_does_not_clear_on_espn_fetch_failure(monkeypatch):
    monkeypatch.setattr(
        "app.services.etl.wnba.update_injury_status.SessionLocal",
        lambda: (_ for _ in ()).throw(AssertionError("should not open db")),
    )

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = ([], False)
        result = uis.run()

    assert result["reason"] == "espn_fetch_failed"
    assert result["cleared"] == 0


def test_keeps_injured_player_when_still_on_feed(monkeypatch):
    mock_db, roster = _make_session_with_roster(1629477, "Sabrina Ionescu")
    still_injured = MagicMock()
    still_injured.player_id = roster.player_id
    still_injured.player_name = "Sabrina Ionescu"
    still_injured.status = "out"

    query_mock = mock_db.query

    def query_side_effect(model):
        q = MagicMock()
        if model is WNBATeamRoster:
            q.filter.return_value.first.return_value = roster
        elif model is WNBAPlayerInjuryStatus:
            q.filter.return_value.all.return_value = [still_injured]
        return q

    query_mock.side_effect = query_side_effect
    monkeypatch.setattr(
        "app.services.etl.wnba.update_injury_status.SessionLocal", lambda: mock_db
    )

    with patch("app.services.etl.wnba.update_injury_status.fetch_injuries") as fi:
        fi.return_value = (
            [
                {
                    "player_name": "Sabrina Ionescu",
                    "team_name": "New York Liberty",
                    "status": "Out",
                    "injury_type": "ankle",
                }
            ],
            True,
        )
        with patch("app.services.etl.wnba.update_injury_status.upsert_many"):
            result = uis.run()

    assert result["cleared"] == 0
    assert still_injured.status == "out"
