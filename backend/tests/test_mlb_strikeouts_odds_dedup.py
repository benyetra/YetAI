"""Tests for the per-event memoization of MLB strikeout book lines.

Both starting pitchers in a game share one Odds API ``event_id`` and the
``pitcher_strikeouts`` event-odds response already contains every pitcher, so
``get_book_line`` must reuse a single HTTP response per event within a run
instead of spending a credit per pitcher.
"""

from __future__ import annotations

from app.services.etl.mlb import strikeouts as so


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _odds_payload():
    def outcome(pitcher, name, point):
        return {"description": pitcher, "name": name, "point": point, "price": -115}

    return {
        "bookmakers": [
            {
                "key": "fanduel",
                "title": "FanDuel",
                "markets": [
                    {
                        "key": "pitcher_strikeouts",
                        "outcomes": [
                            outcome("Gerrit Cole", "Over", 6.5),
                            outcome("Gerrit Cole", "Under", 6.5),
                            outcome("Zack Wheeler", "Over", 7.5),
                            outcome("Zack Wheeler", "Under", 7.5),
                        ],
                    }
                ],
            }
        ]
    }


def test_book_line_lookup_is_memoized_per_event(monkeypatch):
    """Two pitchers sharing an event_id trigger exactly one HTTP call."""
    so.clear_strikeout_odds_cache()
    monkeypatch.setattr(so, "ODDS_API_KEY", "test-key", raising=False)
    calls: list[str] = []

    def fake_sync_get(url, *, params=None, headers=None, caller="sync", timeout=30, raise_for_status=True):
        calls.append(url)
        return _FakeResp(_odds_payload())

    monkeypatch.setattr(
        "app.services.odds_api_sync.sync_odds_get", fake_sync_get
    )

    home = so.get_book_line("evt-1", "Gerrit Cole")
    away = so.get_book_line("evt-1", "Zack Wheeler")

    assert len(calls) == 1
    assert home == (6.5, -115, -115)
    assert away == (7.5, -115, -115)

    so.clear_strikeout_odds_cache()


def test_clear_cache_forces_refetch(monkeypatch):
    so.clear_strikeout_odds_cache()
    monkeypatch.setattr(so, "ODDS_API_KEY", "test-key", raising=False)
    calls: list[str] = []

    def fake_sync_get(url, *, params=None, headers=None, caller="sync", timeout=30, raise_for_status=True):
        calls.append(url)
        return _FakeResp(_odds_payload())

    monkeypatch.setattr(
        "app.services.odds_api_sync.sync_odds_get", fake_sync_get
    )

    so.get_book_line("evt-1", "Gerrit Cole")
    so.clear_strikeout_odds_cache()
    so.get_book_line("evt-1", "Gerrit Cole")

    assert len(calls) == 2

    so.clear_strikeout_odds_cache()
