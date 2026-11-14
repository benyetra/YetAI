"""NBA pregame close capture: once per event, only inside the lead window."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import OddsLineSnapshot
from app.services import odds_snapshots as snaps
from app.services.etl.nba import close_capture as cc

FIX = Path(__file__).parent / "fixtures" / "odds_api"
EID = "6cb4c8feeadd57aa6ab46ebdee60818a"
NOW = datetime(2026, 11, 14, 23, 50)  # naive UTC


def _ev(eid, start):
    return {"id": eid, "commence_time": start.strftime("%Y-%m-%dT%H:%M:%SZ")}


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(engine)
    Session = sessionmaker(bind=engine)
    monkeypatch.setattr("app.core.database.SessionLocal", Session)
    payload = json.loads((FIX / f"nba_event_props_{EID}.json").read_text())["body"]
    calls = []

    def fake_get(url, **kw):
        calls.append((url, kw))
        # What the sync_odds_get snapshot hook would store.
        db = Session()
        snaps.record_rows(db, snaps.parse_payload("basketball_nba", payload), NOW)
        db.close()
        return SimpleNamespace(ok=True, headers={"x-requests-last": "2"})

    monkeypatch.setattr(cc, "sync_odds_get", fake_get)
    monkeypatch.delenv("NBA_CLOSE_CAPTURE_ENABLED", raising=False)
    return SimpleNamespace(
        calls=calls,
        set_events=lambda e: monkeypatch.setattr(cc, "_get_events", lambda s: e),
    )


def test_captures_once_in_window(env):
    env.set_events(
        [
            _ev(EID, datetime(2026, 11, 15, 0, 10)),  # 20 min away
            _ev("far", datetime(2026, 11, 15, 2, 0)),  # ~2 h away
            _ev("started", datetime(2026, 11, 14, 23, 0)),  # already started
        ]
    )
    r = cc.run(NOW)
    assert (r["captured"], r["skipped_already"], r["events_seen"], r["credits"]) == (
        1,
        0,
        3,
        2,
    )
    url, kw = env.calls[0]
    assert url.endswith(f"/events/{EID}/odds")
    assert kw["params"]["markets"] == "player_rebounds,player_assists"
    assert (
        kw["params"]["oddsFormat"] == "american"
        and kw["caller"] == "etl.nba.close_capture"
    )
    r2 = cc.run(datetime(2026, 11, 15, 0, 0))  # next beat, still in window
    assert (r2["captured"], r2["skipped_already"]) == (0, 1) and len(env.calls) == 1


def test_disabled(env, monkeypatch):
    monkeypatch.setenv("NBA_CLOSE_CAPTURE_ENABLED", "0")
    assert cc.run(NOW) == {"status": "disabled"} and not env.calls
