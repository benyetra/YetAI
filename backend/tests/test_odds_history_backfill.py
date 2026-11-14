"""Backfill tool: plan numbers, resumable fetch with cost guards, replay load. No network."""

import copy
import json
import logging
from argparse import Namespace
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import OddsLineSnapshot
from app.services import odds_snapshots as snaps
from scripts import odds_history_backfill as bf

FIX = Path(__file__).parent / "fixtures" / "odds_api"
EID = "e989d01a7b748cf7e0c892b5259ea99d"  # BOS @ SAS, tip 2026-03-11T00:10Z
KEY = "SECRETKEY123"


def _fix():
    return json.loads((FIX / "nba_historical_event_odds_2026-03-10.json").read_text())


def _args(**kw):
    base = dict(
        date_from="2025-11-01",
        date_to="2026-04-12",
        markets="player_rebounds,player_assists",
        snapshots="T-600,T-360,T-5",
        bookmakers=bf.DEFAULT_BOOKS,
        floor=25000,
        rate=1000,
        max_calls=None,
    )
    return Namespace(**{**base, **kw})


def _games(per_date=3, dates=("2026-03-10", "2026-03-11")):
    return [
        {"date": date.fromisoformat(d), "home": f"Team{d[-2:]}{i}"}
        for d in dates
        for i in range(per_date)
    ]


# ---------- plan / estimate ----------


def test_plan_credits_hand_computed():
    # 2 dates x 3 games x 3 snapshots = 18 odds calls; 10 x 2 markets x 1 region = 20 each
    # = 360, plus 2 events calls = 362.
    c = bf.plan_credits(_games(), 2, 3, 1)
    assert (c["events_calls"], c["odds_calls"], c["odds_credits"], c["total"]) == (
        2,
        18,
        360,
        362,
    )
    assert bf.plan_credits(_games(), 2, 3, bf.regions_for(11))["total"] == 722  # x2 + 2
    assert bf.regions_for(10) == 1 and bf.regions_for(11) == 2


def test_menu_and_marginals_hand_computed():
    a = _args(date_from="2026-03-10", date_to="2026-03-11")
    # 6 games, 2 dates, 1 region. minimum: 2 + 10*2*6*2 = 242; recommended: 2 + 360 = 362;
    # full: 2 + 10*3*6*3 = 542; chosen = recommended. Budget 400 - floor 100 = 300.
    rows = {
        r[0].split(": ")[1].split(" ")[0] + r[0][:5]: r
        for r in bf.menu(_games(), a, 400, 100)
    }
    assert rows["minimumrange"][4:] == (242, True)
    assert rows["recommendedrange"][4:] == (362, False)
    assert rows["fullrange"][4:] == (542, False)
    assert rows["chosenrange"][4] == 362
    m = dict(bf.marginals(_games(), a))
    assert m["+player_points"] == 10 * 6 * 3  # 180
    assert m["+1 snapshot"] == 10 * 2 * 6  # 120
    assert m["+1 region"] == 360


def test_norm_team():
    assert bf.norm_team("Los Angeles Clippers") == "LA Clippers"
    assert bf.norm_team("Boston Celtics") == "Boston Celtics"


# ---------- parse_historical ----------


def test_parse_historical_real_fixture():
    body = _fix()["body"]
    ts, rows = snaps.parse_historical("basketball_nba", body)
    assert ts == datetime(2026, 3, 10, 18, 5, 37)
    assert rows == snaps.parse_event("basketball_nba", body["data"])
    assert {r["book"] for r in rows} == {
        "fanduel",
        "draftkings",
        "pinnacle",
        "betrivers",
    }
    assert all(
        r["over_price"] is not None and r["under_price"] is not None for r in rows
    )
    assert all(r["player_key"] for r in rows)
    assert snaps.parse_historical(
        "basketball_nba", {"timestamp": "2026-03-10T18:05:37Z", "data": []}
    ) == (
        datetime(2026, 3, 10, 18, 5, 37),
        [],
    )
    assert snaps.parse_historical("basketball_nba", None) == (None, [])


# ---------- fetch ----------


class FakeAPI:
    """Stands in for requests.get; serves the fixture for odds, an event list for events."""

    def __init__(self, last=None, remaining=99000, statuses=None, empty=False):
        self.calls = []
        self.last, self.remaining = last, remaining
        self.statuses = list(statuses or [])
        self.empty = empty

    def __call__(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        if self.statuses:
            st = self.statuses.pop(0)
            if st == 429:
                return self._resp(429, {}, "0")
        if "/events/" in url:
            body = _fix()["body"]
            if self.empty:
                body = {**body, "data": {}}
            n = 0 if self.empty else 1  # fixture has one market
            cost = str(self.last if self.last is not None else 10 * n)
            return self._resp(200, body, cost)
        ev = {
            "id": EID,
            "home_team": "San Antonio Spurs",
            "commence_time": "2026-03-11T00:10:00Z",
        }
        return self._resp(200, {"timestamp": "x", "data": [ev]}, "1")

    def _resp(self, code, body, cost):
        self.remaining -= int(cost)
        r = Namespace(
            status_code=code,
            headers={
                "x-requests-last": cost,
                "x-requests-used": "1",
                "x-requests-remaining": str(self.remaining),
            },
        )
        r.json = lambda: body
        return r


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        api = FakeAPI(**kw)
        monkeypatch.setattr(bf.requests, "get", api)
        monkeypatch.setattr(
            bf.time, "sleep", lambda s: api.__dict__.setdefault("slept", []).append(s)
        )
        return api

    return install


GAME = [{"date": date(2026, 3, 10), "home": "San Antonio Spurs"}]


def _fetch(tmp_path, **kw):
    a = _args(markets="player_rebounds", snapshots="T-360,T-5", **kw)
    return bf.run_fetch(GAME, tmp_path, a, KEY)


def test_fetch_files_resume_and_no_key(tmp_path, fake, caplog):
    api = fake()
    caplog.set_level(logging.DEBUG)
    assert _fetch(tmp_path) == 0
    assert len(api.calls) == 3  # 1 events + 2 odds
    names = sorted(p.name for p in tmp_path.rglob("*.json"))
    assert names == ["2026-03-10.json", f"{EID}__T-360.json", f"{EID}__T-5.json"]
    rec = json.loads(
        (tmp_path / "odds" / "2026-03-10" / f"{EID}__T-5.json").read_text()
    )
    assert (
        rec["params"]["date"] == "2026-03-11T00:05:00Z"
        and "apiKey" not in rec["params"]
    )
    assert set(rec["headers"]) == set(bf.HEADERS)
    assert KEY not in "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert KEY not in caplog.text
    assert all(c[1]["apiKey"] == KEY for c in api.calls)
    assert len((tmp_path / "calls.csv").read_text().splitlines()) == 3
    assert (tmp_path / "unmatched.csv").read_text().strip() == "date,kind,home_team"
    assert _fetch(tmp_path) == 0 and len(api.calls) == 3  # second run: 0 new calls


def test_fetch_floor_stop(tmp_path, fake):
    api = fake(
        remaining=25011
    )  # events costs 1 -> 25010; odds expected 10 -> 25000 ok; next 24990 < floor
    assert _fetch(tmp_path) == 3
    assert len(api.calls) == 2  # events + first odds, then stop


def test_fetch_cost_mismatch_stop(tmp_path, fake):
    api = fake(last=30)  # body has 1 market -> expected 10, header says 30
    assert _fetch(tmp_path) == 4
    assert len(api.calls) == 2


def test_fetch_429_retry_then_success(tmp_path, fake):
    api = fake(statuses=[200, 429, 429, 200])
    assert _fetch(tmp_path) == 0
    assert [x for x in api.slept if x >= 1] == [2, 4]
    assert len(list(tmp_path.glob("odds/*/*.json"))) == 2


def test_fetch_empty_body_accepted_and_max_calls(tmp_path, fake):
    api = fake(empty=True)
    assert _fetch(tmp_path) == 0  # cost 0 == 10 * 0 markets
    assert len(list(tmp_path.glob("odds/*/*.json"))) == 2
    api2 = fake()
    t2 = tmp_path / "b"
    assert (
        bf.run_fetch(
            GAME,
            t2,
            _args(markets="player_rebounds", snapshots="T-360,T-5", max_calls=2),
            KEY,
        )
        == 0
    )
    assert len(api2.calls) == 2


# ---------- load ----------


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _put(d: Path, rec: dict, tag: str):
    p = d / "odds" / "2026-03-10" / f"{EID}__{tag}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rec))


def test_load_idempotent_and_chronological(tmp_path, db):
    rec = _fix()
    _ts, base = snaps.parse_historical("basketball_nba", rec["body"])
    _put(tmp_path, rec, "T-360")
    c = bf.load_dir(db, tmp_path, apply=False)
    assert (c["files"], c["inserted"]) == (1, len(base)) and db.query(
        OddsLineSnapshot
    ).count() == 0
    c = bf.load_dir(db, tmp_path, apply=True)
    assert c["inserted"] == len(base) and db.query(OddsLineSnapshot).count() == len(
        base
    )
    c = bf.load_dir(db, tmp_path, apply=True)
    assert (c["inserted"], c["touched"], c["already_loaded"]) == (0, 0, 1)

    # later snapshot, one line moved: others touched, moved one inserted at the later time
    rec2 = copy.deepcopy(rec)
    rec2["body"]["timestamp"] = "2026-03-10T23:55:10Z"
    bk = rec2["body"]["data"]["bookmakers"][0]
    who = bk["markets"][0]["outcomes"][0]["description"]
    for o in bk["markets"][0]["outcomes"]:  # move every line of one player at one book
        if o["description"] == who:
            o["point"] += 1
    n_moved = sum(1 for r in base if r["book"] == bk["key"] and r["player_name"] == who)
    _put(tmp_path, rec2, "T-5")
    later = datetime(2026, 3, 10, 23, 55, 10)
    c = bf.load_dir(db, tmp_path, apply=True)
    assert (c["loaded"], c["already_loaded"]) == (1, 1)
    # moved rows inserted at the later time; every other identity only touched
    assert c["inserted"] == n_moved and c["touched"] == len(base) - n_moved
    new = [r for r in db.query(OddsLineSnapshot) if r.first_seen_at == later]
    assert len(new) == n_moved and all(r.player_name == who for r in new)
    assert db.query(OddsLineSnapshot).count() == len(base) + n_moved


def test_load_after_commence_inserts_nothing(tmp_path, db):
    rec = _fix()
    rec["body"]["timestamp"] = "2026-03-11T00:20:00Z"  # tip 00:10Z
    _put(tmp_path, rec, "T-5")
    c = bf.load_dir(db, tmp_path, apply=True)
    assert db.query(OddsLineSnapshot).count() == 0 and c["inserted"] == 0


def test_load_refuses_non_local_db():
    with pytest.raises(bf.Stop) as e:
        bf.check_db_host("postgresql://u:p@prod.example.com:5432/db", False)
    assert e.value.code == 2
    bf.check_db_host("postgresql://u:p@localhost:5432/db", False)
    bf.check_db_host("postgresql://u:p@prod.example.com/db", True)


def test_summary_and_games(db):
    from app.models.predictions_models import RecentGames, TeamOffenseStats

    rec = _fix()
    _ts, rows = snaps.parse_historical("basketball_nba", rec["body"])
    snaps.record_rows(db, rows, now=_ts)
    out = bf.summarize(db)
    assert any("pinnacle" in line and "2026-03" in line for line in out)
    assert "median distinct snapshot times per event 1" in out[-1]

    engine = db.get_bind()
    RecentGames.__table__.create(engine)
    TeamOffenseStats.__table__.create(engine)
    db.add(TeamOffenseStats(team_id=7, team_name="Los Angeles Clippers"))
    db.add_all(
        [
            RecentGames(
                player_id=i,
                game_date=date(2026, 3, 10),
                opponent_team_id=7,
                home_game=hg,
            )
            for i, hg in ((1, False), (2, False), (3, True))
        ]
    )
    db.commit()
    assert bf.load_games(db, date(2026, 3, 1), date(2026, 3, 31)) == [
        {"date": date(2026, 3, 10), "home": "LA Clippers"}
    ]
