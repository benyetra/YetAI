"""Multi-book prop quotes + best price on projection rows, driven by a real Odds API payload."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.etl.nba import _fanduel_lines as fdl

FIXTURE = Path(__file__).parent / "fixtures/odds_api"
EVENT = json.loads(
    (FIXTURE / "nba_event_props_6cb4c8feeadd57aa6ab46ebdee60818a.json").read_text()
)["body"]
EID = EVENT["id"]
TEAMS = ("New Orleans Pelicans", "Denver Nuggets")


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


@pytest.fixture
def calls(monkeypatch):
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "k", raising=False)
    seen: list[dict] = []

    def fake(url, *, params=None, **_):
        seen.append({"url": url, **(params or {})})
        if url.endswith("/events"):
            return _Resp([{"id": EID, "home_team": TEAMS[0], "away_team": TEAMS[1]}])
        return _Resp(EVENT)

    monkeypatch.setattr(fdl, "sync_odds_get", fake)
    yield seen
    fdl.clear_cache()


def _row():
    return SimpleNamespace(
        fanduel_line=None,
        fanduel_over_under=None,
        fanduel_price=None,
        best_book=None,
        best_line=None,
        best_price=None,
        projected_at=None,
    )


def _apply(row, player, market, projection):
    return fdl.apply_fanduel_to_projection(
        row,
        team_name=TEAMS[0],
        opponent_team_name=TEAMS[1],
        player_name=player,
        market=market,
        projection=projection,
    )


def test_prop_quotes_reads_many_books(calls):
    quotes = fdl.prop_quotes(fdl.NBA_SPORT, EID, "Zion Williamson", "player_points")
    assert len({q.book for q in quotes}) >= 5
    fd = [q for q in quotes if q.book == "fanduel"]
    assert [(q.line, q.over_price, q.under_price) for q in fd] == [(20.5, -130, 102)]
    # ballybet lists the Over only: one-sided quote, no under price
    bally = [q for q in quotes if q.book == "ballybet"]
    assert bally[0].over_price == -129 and bally[0].under_price is None
    assert calls[-1]["bookmakers"] == fdl.PROP_BOOKS


def test_get_fanduel_line_stays_fanduel_only(calls):
    line, price, flag = fdl.get_fanduel_line(
        fdl.NBA_SPORT, EID, "Herb Jones", "player_points", 9.0
    )
    assert (line, price, flag) == (7.5, -125.0, "o")  # FanDuel's, not the 8.5s


def test_best_price_where_books_disagree_on_line(calls):
    # Herb Jones points, projection 9.0 -> Over at every line. FanDuel/espnbet 7.5 @ -125, five
    # books at 8.5 (pinnacle never best). Consensus fair median 7.92 (sd 5.0 default for points
    # per MARKET_SD): P(over 7.5) = .526 -> EV = .526 * (1 + 100/125) - 1 = -.053;
    # P(over 8.5) = .465 -> at +100 EV = -.071. 7.5 @ -125 wins; fanduel/espnbet tie on
    # line+price, FanDuel breaks it.
    row = _row()
    assert _apply(row, "Herb Jones", "player_points", 9.0) is True
    assert (row.fanduel_line, row.fanduel_over_under, row.fanduel_price) == (
        7.5,
        "o",
        -125,
    )
    assert (row.best_book, row.best_line, row.best_price) == ("fanduel", 7.5, -125)
    assert row.projected_at is not None


def test_best_price_on_one_shared_line_is_highest_price(calls):
    # Zion: everyone 20.5 over, ballybet -129 .. draftkings -119; projection 23 -> over.
    row = _row()
    _apply(row, "Zion Williamson", "player_points", 23.0)
    # over prices at 20.5: fanduel -130, ... draftkings -119 (highest)
    assert (row.best_book, row.best_line, row.best_price) == ("draftkings", 20.5, -119)


def test_blocks_best_without_fanduel(calls):
    row = _row()
    assert _apply(row, "Nikola Jokic", "player_blocks", 1.8) is False
    assert row.fanduel_line is None  # FanDuel posts no blocks in this fixture
    assert row.best_book in {"ballybet", "hardrockbet"}
    assert row.best_line == 1.5


def test_steals_attached_with_fanduel(calls):
    row = _row()
    assert _apply(row, "Nikola Jokic", "player_steals", 1.9) is True
    assert (row.fanduel_line, row.fanduel_price, row.fanduel_over_under) == (
        1.5,
        128,
        "o",
    )
    assert row.best_book == "ballybet" and row.best_price == 145


def test_one_http_call_per_event_market(calls):
    for name in ("Herb Jones", "Zion Williamson", "Nikola Jokic"):
        _apply(_row(), name, "player_points", 15.0)
    odds = [c for c in calls if c["url"].endswith("/odds")]
    assert len(odds) == 1
    assert len([c for c in calls if c["url"].endswith("/events")]) == 1


def test_no_fresh_quotes_leaves_best_unchanged(monkeypatch):
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "", raising=False)
    row = _row()
    row.best_book, row.best_line, row.best_price = "draftkings", 5.5, -110
    assert _apply(row, "Nobody", "player_points", 5.0) is False
    assert (row.best_book, row.best_line, row.best_price) == ("draftkings", 5.5, -110)
    assert row.projected_at is not None


def test_mismatched_over_under_points_split_into_one_sided_quotes(monkeypatch):
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "k", raising=False)
    payload = {
        "bookmakers": [
            {
                "key": "betmgm",
                "markets": [
                    {
                        "key": "player_points",
                        "outcomes": [
                            {
                                "description": "A B",
                                "name": "Over",
                                "point": 10.5,
                                "price": -110,
                            },
                            {
                                "description": "A B",
                                "name": "Under",
                                "point": 11.5,
                                "price": -120,
                            },
                        ],
                    }
                ],
            }
        ]
    }
    monkeypatch.setattr(fdl, "sync_odds_get", lambda *a, **k: _Resp(payload))
    qs = fdl.prop_quotes(fdl.NBA_SPORT, "e", "A B", "player_points")
    assert [(q.line, q.over_price, q.under_price) for q in qs] == [
        (10.5, -110, None),
        (11.5, None, -120),
    ]
    fdl.clear_cache()
