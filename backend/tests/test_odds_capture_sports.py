"""Every ETL odds fetcher reaches sync_odds_get (american odds, odds endpoint) and its payload parses."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import OddsLineSnapshot
from app.services import odds_api_sync, odds_snapshots as snaps

FIX = Path(__file__).parent / "fixtures" / "odds_api"
LINES = json.loads((FIX / "nba_game_lines_2026-11-14.json").read_text())["body"]


def _event(sport, market, bk, outcomes, eid="ev1"):
    return {
        "id": eid,
        "sport_key": sport,
        "commence_time": "2026-11-15T00:10:00Z",
        "home_team": "H",
        "away_team": "A",
        "bookmakers": [
            {
                "key": bk,
                "title": bk,
                "markets": [
                    {
                        "key": market,
                        "last_update": "2026-11-14T20:00:00Z",
                        "outcomes": outcomes,
                    }
                ],
            }
        ],
    }


def _ou(player, point, over, under):
    return [
        {"name": "Over", "description": player, "price": over, "point": point},
        {"name": "Under", "description": player, "price": under, "point": point},
    ]


@pytest.fixture
def cap(monkeypatch):
    """Route requests.get through the real sync_odds_get + snapshot hook; collect rows."""
    engine = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(engine)
    monkeypatch.setattr("app.core.database.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(odds_api_sync, "guard_sync", lambda *a, **k: True)
    monkeypatch.setattr(odds_api_sync, "record_sync", lambda *a, **k: None)
    monkeypatch.setattr("app.services.odds_api_service.sport_in_season", lambda s: True)
    for k in ("ODDS_API_KEY",):
        monkeypatch.setenv(k, "k")
    box = SimpleNamespace(payload=None, calls=[], rows=[])

    def fake_get(url, params=None, **kw):
        box.calls.append((url, params))
        body = [{"id": "ev1"}] if url.endswith("/events") else box.payload
        return SimpleNamespace(
            ok=True,
            status_code=200,
            headers={"x-requests-last": "1"},
            json=lambda: body,
            text="",
        )

    monkeypatch.setattr(odds_api_sync.requests, "get", fake_get)
    orig = snaps.record_rows
    monkeypatch.setattr(
        snaps,
        "record_rows",
        lambda db, rows, now=None: (box.rows.extend(rows), orig(db, rows, now))[1],
    )
    return box


def _check(cap, sport, market, *, line=True):
    odds = [c for c in cap.calls if not c[0].endswith("/events")]
    assert odds and all(p["oddsFormat"] == "american" for _, p in odds)
    got = [r for r in cap.rows if r["sport"] == sport and r["market"] == market]
    assert got, (sport, market)
    return got


@pytest.mark.parametrize(
    "sport,mod",
    [
        ("basketball_nba", "nba"),
        ("americanfootball_nfl", "nfl"),
    ],
)
def test_bulk_game_lines(cap, sport, mod):
    import importlib

    m = importlib.import_module(f"app.services.etl.{mod}.update_game_lines")
    cap.payload = [{**e, "sport_key": sport} for e in LINES]
    assert m._fetch_bulk_odds()
    for url, _ in cap.calls:
        assert f"/sports/{m.SPORT}/odds" in url
    assert _check(cap, m.SPORT, "totals")
    assert _check(cap, m.SPORT, "h2h")


def test_wnba_game_lines(cap):
    from app.services.etl.wnba import update_game_lines as m

    cap.payload = LINES
    assert m._odds_get(
        f"{m.SPORT}/odds",
        params={
            "regions": "us",
            "markets": "h2h,spreads,totals",
            "oddsFormat": "american",
        },
    )
    assert _check(cap, m.SPORT, "spreads")


def test_nhl_event_odds(cap, monkeypatch):
    from app.services.etl.nhl import generate_daily_predictions as g

    monkeypatch.setattr(g, "ODDS_API_KEY", "k")
    g._nhl_event_odds_cache.clear()
    cap.payload = {
        **_event(
            "icehockey_nhl",
            "player_total_saves",
            "draftkings",
            _ou("Goalie G", 27.5, -115, -105),
        ),
    }
    cap.payload["bookmakers"][0]["markets"] += [
        {"key": "player_shots_on_goal", "outcomes": _ou("Skater S", 2.5, 110, -130)},
        {
            "key": "totals",
            "outcomes": [
                {"name": "Over", "price": -110, "point": 6.0},
                {"name": "Under", "price": -110, "point": 6.0},
            ],
        },
    ]
    assert g._fetch_nhl_event_odds_payload("ev1")
    saves = _check(cap, "icehockey_nhl", "player_total_saves")[0]
    assert (saves["line"], saves["over_price"], saves["under_price"]) == (
        27.5,
        -115,
        -105,
    )
    assert _check(cap, "icehockey_nhl", "player_shots_on_goal")
    assert _check(cap, "icehockey_nhl", "totals")[0]["line"] == 6.0


def test_nfl_qb_pass_yds(cap):
    from app.services.etl.nfl import qb_betting as m

    cap.payload = _event(
        "americanfootball_nfl",
        "player_pass_yds",
        "fanduel",
        _ou("QB One", 250.5, -110, -110),
    )
    assert m.get_nfl_games_and_lines()
    assert _check(cap, "americanfootball_nfl", "player_pass_yds")[0]["line"] == 250.5


def test_nfl_reception_yds(cap):
    from app.services.etl.nfl import recv_yds_betting as m

    cap.payload = _event(
        "americanfootball_nfl",
        "player_reception_yds",
        "fanduel",
        _ou("WR One", 70.5, -115, -105),
    )
    assert m.fetch_reception_yds_lines()
    assert (
        _check(cap, "americanfootball_nfl", "player_reception_yds")[0]["over_price"]
        == -115
    )


def test_nfl_anytime_td_yes_no(cap):
    from app.services.etl.nfl import anytime_td_betting as m

    cap.payload = _event(
        "americanfootball_nfl",
        "player_anytime_td",
        "fanduel",
        [
            {"name": "Yes", "description": "RB One", "price": 110},
            {"name": "No", "description": "RB One", "price": -140},
        ],
    )
    m.fetch_anytime_td_odds()
    r = _check(cap, "americanfootball_nfl", "player_anytime_td")[0]
    assert (r["line"], r["over_price"], r["under_price"]) == (None, 110, -140)
