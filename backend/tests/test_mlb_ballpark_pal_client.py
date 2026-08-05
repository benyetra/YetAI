from pathlib import Path
from unittest.mock import MagicMock, patch

FIX = Path(__file__).parent / "fixtures" / "ballpark_pal"


def _load(name: str) -> dict:
    import json

    return json.loads((FIX / name).read_text())


def test_games_parses_data_items():
    from app.services.ballpark_pal.client import BallparkPalClient

    payload = {
        "meta": {"asOf": "2026-08-05T12:00:00Z", "requestId": "r1"},
        "data": {"items": [{"gameId": 776345, "teamAwayId": 108, "teamHomeId": 136}]},
    }
    client = BallparkPalClient(api_key="test_key", session=MagicMock())
    resp = MagicMock(status_code=200)
    resp.json.return_value = payload
    resp.headers = {}
    client._session.get.return_value = resp
    out = client.games("2026-08-05")
    assert out is not None
    assert out["items"][0]["gameId"] == 776345


def test_unauthorized_returns_none_not_raise():
    from app.services.ballpark_pal.client import BallparkPalClient

    client = BallparkPalClient(api_key="bad", session=MagicMock())
    resp = MagicMock(status_code=401)
    resp.json.return_value = _load("error_unauthorized.json")
    resp.headers = {}
    client._session.get.return_value = resp
    assert client.games("2026-08-05") is None


def test_429_malformed_retry_after_does_not_raise():
    from app.services.ballpark_pal.client import BallparkPalClient

    client = BallparkPalClient(api_key="test_key", session=MagicMock())
    resp429 = MagicMock(status_code=429)
    resp429.headers = {"Retry-After": "not-a-number"}
    resp200 = MagicMock(status_code=200)
    resp200.headers = {}
    resp200.json.return_value = {
        "meta": {"asOf": "2026-08-05T12:00:00Z", "requestId": "r1"},
        "data": {"items": []},
    }
    client._session.get.side_effect = [resp429, resp200]
    with patch("app.services.ballpark_pal.client.time.sleep"):
        out = client.games("2026-08-05")
    assert out is not None
    assert out["items"] == []


def test_disabled_without_key(monkeypatch):
    monkeypatch.delenv("BALLPARK_PAL_API_KEY", raising=False)
    monkeypatch.setenv("BALLPARK_PAL_ENABLED", "1")
    from app.services.ballpark_pal.config import (
        ballpark_pal_enabled,
        get_ballpark_pal_api_key,
    )

    assert get_ballpark_pal_api_key() is None
    assert ballpark_pal_enabled() is False
