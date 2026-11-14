"""Adversarial probes for the odds snapshot store and price maths."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import OddsLineSnapshot as S
from app.services import odds_math as om
from app.services import odds_snapshots as snaps

T0 = datetime(2026, 11, 14, 12, 0)
START = datetime(2026, 11, 14, 23, 0)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    S.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def row(
    book="fanduel",
    line=5.5,
    over=-110,
    under=-110,
    event="e1",
    who="A B",
    market="player_points",
    start=START,
):
    return {
        "sport": "basketball_nba",
        "event_id": event,
        "commence_time": start,
        "game_date": date(2026, 11, 14),
        "home_team": "H",
        "away_team": "A",
        "market": market,
        "book": book,
        "player_name": who,
        "player_key": snaps.player_key(who),
        "line": line,
        "over_price": over,
        "under_price": under,
        "home_price": None,
        "away_price": None,
        "book_updated_at": None,
    }


def count(db):
    return db.query(S).count()


def test_move_and_move_back_then_unchanged(db):
    snaps.record_rows(db, [row(line=5.5)], T0)
    snaps.record_rows(db, [row(line=6.5)], T0 + timedelta(minutes=1))
    snaps.record_rows(db, [row(line=5.5)], T0 + timedelta(minutes=2))
    r = snaps.record_rows(db, [row(line=5.5)], T0 + timedelta(minutes=3))
    assert (count(db), r["inserted"]) == (3, 0)
    last = db.query(S).order_by(S.id.desc()).first()
    assert last.last_seen_at == T0 + timedelta(minutes=3)


def test_two_lines_one_book_then_one_drops(db):
    snaps.record_rows(db, [row(line=5.5), row(line=6.5)], T0)
    snaps.record_rows(db, [row(line=5.5), row(line=6.5)], T0 + timedelta(minutes=1))
    assert count(db) == 2
    snaps.record_rows(db, [row(line=5.5)], T0 + timedelta(minutes=2))
    assert count(db) == 3
    idx = snaps.closing_index(
        db, date(2026, 11, 14), date(2026, 11, 14), ["player_points"]
    )
    (rows,) = idx.values()
    assert [r.line for r in rows] == [5.5]


def test_bulk_two_events_and_started_skipped(db):
    rows = [
        row(event="e1"),
        row(event="e2"),
        row(event="e3", start=T0 - timedelta(hours=1)),
    ]
    r = snaps.record_rows(db, rows, T0)
    assert r["inserted"] == 2
    r = snaps.record_rows(db, rows, T0 + timedelta(minutes=5))
    assert (r["inserted"], r["touched"]) == (0, 2)


def test_none_vs_zero_price_distinct(db):
    snaps.record_rows(db, [row(under=None)], T0)
    r = snaps.record_rows(db, [row(under=0)], T0 + timedelta(minutes=1))
    assert r["inserted"] == 1


def test_best_quote_negative_vs_positive_and_one_sided():
    qs = [
        om.Quote("a", 5.5, -105, -115),
        om.Quote("b", 5.5, +100, -120),
        om.Quote("c", 5.5, None, -110),
    ]
    assert om.best_quote(qs, "o").book == "b"
    assert om.best_quote(qs, "u").book == "c"


def test_best_quote_single_book_and_zero_price():
    b = om.best_quote([om.Quote("a", 5.5, -110, -110)], "o")
    assert b.book == "a" and b.fair_prob == pytest.approx(0.5)
    assert om.best_quote([om.Quote("a", 5.5, 0, 0)], "o") is None


def test_best_quote_tie_prefers_fanduel_then_key():
    qs = [
        om.Quote("zz", 5.5, -110, -110),
        om.Quote("fanduel", 5.5, -110, -110),
        om.Quote("aa", 5.5, -110, -110),
    ]
    assert om.best_quote(qs, "o").book == "fanduel"
    qs = [om.Quote("ab", 5.5, -110, -110), om.Quote("a", 5.5, -110, -110)]
    assert om.best_quote(qs, "o").book == "a"


def test_best_quote_pinnacle_never_best_but_in_consensus():
    qs = [om.Quote("pinnacle", 5.5, +120, -140), om.Quote("fanduel", 5.5, -110, -110)]
    assert om.best_quote(qs, "o").book == "fanduel"


def test_best_quote_projection_constraint():
    qs = [om.Quote("a", 4.5, -110, -110), om.Quote("b", 6.5, -110, -110)]
    assert om.best_quote(qs, "u", projection=5.0).line == 6.5
    assert om.best_quote(qs, "o", projection=5.0).line == 4.5
    assert om.best_quote(qs, "o", projection=6.5).line in (4.5, 6.5)
    assert om.best_quote([om.Quote("a", 6.5, -110, -110)], "u", projection=6.5) is None


def test_prob_clv_under_sign_and_median_price():
    close = [om.Quote("a", 5.5, -150, +130)]  # close favours over
    assert om.prob_clv("o", 5.5, -110, close) > 0
    assert om.prob_clv("u", 5.5, -110, close) < 0
    assert om.median_price([]) is None
    assert om.median_price([0, None]) is None


# ---- apply_fanduel_to_projection: a failed refresh must not leave a quote for the other side
import json
from pathlib import Path
from types import SimpleNamespace

from app.services.etl.nba import _fanduel_lines as fdl

_EV = json.loads(
    (
        Path(__file__).parent
        / "fixtures/odds_api/nba_event_props_6cb4c8feeadd57aa6ab46ebdee60818a.json"
    ).read_text()
)["body"]
_TEAMS = ("New Orleans Pelicans", "Denver Nuggets")


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p


def _apply(row, projection, status=200):
    fdl.clear_cache()

    def fake(url, *, params=None, **_):
        if url.endswith("/events"):
            return _Resp(
                200, [{"id": _EV["id"], "home_team": _TEAMS[0], "away_team": _TEAMS[1]}]
            )
        return _Resp(status, _EV if status == 200 else None)

    import pytest as _p

    mp = _p.MonkeyPatch()
    mp.setattr(fdl.settings, "ODDS_API_KEY", "k", raising=False)
    mp.setattr(fdl, "sync_odds_get", fake)
    try:
        return fdl.apply_fanduel_to_projection(
            row,
            team_name=_TEAMS[0],
            opponent_team_name=_TEAMS[1],
            player_name="Zion Williamson",
            market="player_points",
            projection=projection,
        )
    finally:
        mp.undo()
        fdl.clear_cache()


def test_failed_refresh_flipping_side_drops_best_of_old_side():
    row = SimpleNamespace(
        fanduel_line=20.5,
        fanduel_over_under="o",
        fanduel_price=-130,
        best_book="draftkings",
        best_line=20.5,
        best_price=-105,
        projected_at=None,
    )
    assert _apply(row, 15.0, status=500) is False  # projection now below the line
    assert row.fanduel_over_under == "u"
    assert row.best_price is None  # the stored -105 was the OVER price
