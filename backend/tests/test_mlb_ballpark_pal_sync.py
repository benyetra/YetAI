from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock


class FakeBallparkPalClient:
    def games(self, slate_date):
        assert slate_date == "2026-08-05"
        return {"items": [{"gameId": 776345, "teamAwayId": 108, "teamHomeId": 136}]}

    def projections_averages(self, game_id):
        assert game_id == 776345
        return {
            "batters": [{"playerId": 42, "teamId": 108, "hits": 1.1}],
            "pitchers": [{"playerId": 99, "teamId": 136, "strikeouts": 6.4}],
            "teams": [{"teamId": 108, "runs": 4.3}],
        }

    def projections_probabilities(self, game_id):
        assert game_id == 776345
        return [
            {
                "marketKey": "batter_hits",
                "probability": 61.2,
                "subject": {"type": "player", "id": 42},
            }
        ]

    def parkfactors(self, slate_date):
        assert slate_date == "2026-08-05"
        return [{"gameId": 776345, "runsPercent": 18}]

    def parkfactors_hitters(self, *, date):
        assert date == "2026-08-05"
        return [{"gameId": 776345, "playerId": 42, "homeRuns": 1.12}]

    def matchups(self, slate_date, *, starters):
        assert slate_date == "2026-08-05"
        assert starters is True
        return [
            {
                "gameId": 776345,
                "batterId": 42,
                "pitcherId": 99,
                "strikeoutProbability": 23.5,
            }
        ]


def test_sync_fetches_and_upserts_slate(monkeypatch):
    monkeypatch.setenv("BALLPARK_PAL_ENABLED", "1")
    monkeypatch.setenv("BALLPARK_PAL_API_KEY", "test-key")

    calls = {"games": [], "players": [], "park": [], "matchups": []}
    monkeypatch.setattr(
        "app.services.ballpark_pal.store.upsert_game_snapshot",
        lambda *args, **kwargs: calls["games"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        "app.services.ballpark_pal.store.upsert_player_projs",
        lambda *args: calls["players"].append(args) or len(args[3]),
    )
    monkeypatch.setattr(
        "app.services.ballpark_pal.store.upsert_park_factors",
        lambda *args: calls["park"].append(args) or len(args[3]),
    )
    monkeypatch.setattr(
        "app.services.ballpark_pal.store.upsert_matchups",
        lambda *args: calls["matchups"].append(args) or len(args[3]),
    )

    session = MagicMock()
    from app.services.ballpark_pal.sync import sync_ballpark_pal_slate

    result = sync_ballpark_pal_slate(
        date(2026, 8, 5), client=FakeBallparkPalClient(), session=session
    )

    assert result == {
        "status": "ok",
        "games": 1,
        "players": 3,
        "park_factors": 2,
        "matchups": 1,
    }
    assert len(calls["games"]) == 1
    assert {row["role"] for row in calls["players"][0][3]} == {
        "batter",
        "pitcher",
        "team",
    }
    assert (
        calls["players"][0][3][0]["selected_probs"]["batter_hits"]["probability"]
        == 61.2
    )
    assert len(calls["park"]) == 2
    assert calls["matchups"][0][3][0]["probs"]["strikeoutProbability"] == 23.5
    session.commit.assert_called_once_with()


def test_sync_skipped_when_disabled(monkeypatch):
    monkeypatch.setenv("BALLPARK_PAL_ENABLED", "0")
    monkeypatch.delenv("BALLPARK_PAL_API_KEY", raising=False)

    from app.services.ballpark_pal.sync import sync_ballpark_pal_slate

    out = sync_ballpark_pal_slate(date(2026, 8, 5))

    assert out == {"status": "skipped", "reason": "disabled"}


def test_sync_soft_fails_when_games_fetch_fails(monkeypatch):
    monkeypatch.setenv("BALLPARK_PAL_ENABLED", "1")
    monkeypatch.setenv("BALLPARK_PAL_API_KEY", "test-key")
    client = MagicMock()
    client.games.return_value = None
    session = MagicMock()

    from app.services.ballpark_pal.sync import sync_ballpark_pal_slate

    out = sync_ballpark_pal_slate(date(2026, 8, 5), client=client, session=session)

    assert out == {"status": "error", "error": "games_fetch_failed"}
    session.rollback.assert_called_once_with()
