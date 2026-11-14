"""Snapshot store: parse real Odds API payloads, dedupe, closing / at-time reads."""

import copy
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import OddsLineSnapshot
from app.services import odds_snapshots as snaps

FIX = Path(__file__).parent / "fixtures" / "odds_api"
EVENT_ID = "6cb4c8feeadd57aa6ab46ebdee60818a"  # DEN @ NOP, 2026-11-15T00:10Z


def _event():
    return json.loads((FIX / f"nba_event_props_{EVENT_ID}.json").read_text())["body"]


def _lines():
    return json.loads((FIX / "nba_game_lines_2026-11-14.json").read_text())["body"]


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_parse_event_props_every_book_both_prices():
    rows = snaps.parse_payload("basketball_nba", _event())
    books = {r["book"] for r in rows}
    assert len(books) >= 5 and "fanduel" in books and "draftkings" in books
    r = next(
        r
        for r in rows
        if r["book"] == "fanduel" and r["market"] == "player_points" and r["line"]
    )
    assert r["over_price"] is not None and r["under_price"] is not None
    assert r["player_key"] == snaps.player_key(r["player_name"])
    assert r["commence_time"] == datetime(2026, 11, 15, 0, 10)
    assert r["game_date"] == date(2026, 11, 14)  # Eastern date
    assert {r["market"] for r in rows} >= {"player_steals", "player_blocks"}


def test_parse_game_lines():
    rows = snaps.parse_payload("basketball_nba", _lines())
    ev = _lines()[0]
    mine = [r for r in rows if r["event_id"] == ev["id"] and r["book"] == "fanduel"]
    by_m = {r["market"]: r for r in mine}
    assert set(by_m) == {"h2h", "spreads", "totals"}
    assert by_m["h2h"]["line"] is None and by_m["h2h"]["home_price"] is not None
    assert by_m["spreads"]["line"] is not None and by_m["spreads"]["away_price"]
    assert by_m["totals"]["over_price"] and by_m["totals"]["under_price"]
    assert all(r["player_key"] == "" for r in mine)


def test_dedupe_change_and_reads(db):
    t0 = datetime(2026, 11, 14, 20, 45)
    first = snaps.record_rows(db, snaps.parse_payload("basketball_nba", _event()), t0)
    n = db.query(OddsLineSnapshot).count()
    assert first["inserted"] == n > 0

    # Identical fetch: nothing inserted, every row touched.
    again = snaps.record_rows(
        db, snaps.parse_payload("basketball_nba", _event()), t0 + timedelta(hours=1)
    )
    assert again == {"inserted": 0, "touched": n}
    assert db.query(OddsLineSnapshot).count() == n

    # One FanDuel line moves by a point: exactly one new observation.
    ev = copy.deepcopy(_event())
    fd = next(b for b in ev["bookmakers"] if b["key"] == "fanduel")
    mkt = next(m for m in fd["markets"] if m["key"] == "player_rebounds")
    who = mkt["outcomes"][0]["description"]
    old_line = mkt["outcomes"][0]["point"]
    for o in mkt["outcomes"]:
        if o["description"] == who:
            o["point"] = old_line + 1
    t2 = t0 + timedelta(hours=3)  # 23:45 UTC, before the 00:10 tip
    moved = snaps.record_rows(db, snaps.parse_payload("basketball_nba", ev), t2)
    assert moved["inserted"] == 1
    assert db.query(OddsLineSnapshot).count() == n + 1

    # A fetch after tip-off with yet another line must not become the close.
    for o in mkt["outcomes"]:
        if o["description"] == who:
            o["point"] = old_line + 5
    snaps.record_rows(
        db, snaps.parse_payload("basketball_nba", ev), datetime(2026, 11, 15, 1, 0)
    )

    close = [
        r
        for r in snaps.closing_quotes(db, date(2026, 11, 14), "player_rebounds", who)
        if r.book == "fanduel"
    ]
    assert [r.line for r in close] == [old_line + 1]
    assert close[0].first_seen_at == t2
    assert len(snaps.closing_quotes(db, date(2026, 11, 14), "player_rebounds", who)) > 1

    # At projection time (between the fetches) the old line was in effect.
    at = snaps.quotes_at(
        db, date(2026, 11, 14), "player_rebounds", who, t0 + timedelta(hours=2)
    )
    fd_at = [r for r in at if r.book == "fanduel"]
    assert [r.line for r in fd_at] == [old_line]
    assert fd_at[0].last_seen_at == t0 + timedelta(hours=1)


def test_line_moving_back_is_a_new_observation(db):
    base = [
        {
            "sport": "basketball_nba",
            "event_id": "e1",
            "commence_time": datetime(2026, 11, 15, 0, 0),
            "game_date": date(2026, 11, 14),
            "home_team": "H",
            "away_team": "A",
            "market": "player_points",
            "player_name": "X Y",
            "player_key": "x y",
            "book": "fanduel",
            "book_updated_at": None,
            "line": 24.5,
            "over_price": -110,
            "under_price": -110,
        }
    ]
    t = datetime(2026, 11, 14, 12)
    snaps.record_rows(db, base, t)
    snaps.record_rows(db, [{**base[0], "line": 25.5}], t + timedelta(hours=1))
    out = snaps.record_rows(db, base, t + timedelta(hours=2))
    assert out["inserted"] == 1
    assert db.query(OddsLineSnapshot).count() == 3


def test_record_response_filters_endpoints(monkeypatch):
    seen = []
    monkeypatch.setattr(snaps, "record_rows", lambda db, rows, now=None: seen.append(1))
    url = (
        f"https://api.the-odds-api.com/v4/sports/basketball_nba/events/{EVENT_ID}/odds"
    )
    # Decimal odds, events lists and historical payloads are not recorded.
    assert snaps.record_response(url, {"oddsFormat": "decimal"}, _event()) is None
    assert (
        snaps.record_response(
            "https://api.the-odds-api.com/v4/sports/basketball_nba/events",
            {"oddsFormat": "american"},
            [],
        )
        is None
    )
    assert (
        snaps.record_response(
            "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds",
            {"oddsFormat": "american"},
            {"data": []},
        )
        is None
    )
    assert seen == []
    monkeypatch.setenv("ODDS_SNAPSHOTS_ENABLED", "0")
    assert snaps.record_response(url, {"oddsFormat": "american"}, _event()) is None
