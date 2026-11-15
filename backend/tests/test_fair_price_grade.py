"""Shadow grader (SQLite): hand-computed CLV, line conversion, results, close notes, next
snapshot, idempotency, and equality with the backtest."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import FairPriceShadowFlag as F
from app.models.predictions_models import OddsLineSnapshot as S
from app.models.predictions_models import RecentGames
from app.services import odds_math
from app.services.fair_price import backtest as bt
from app.services.fair_price import grade, lines, shadow

NBA = "basketball_nba"
M = "player_rebounds"
C = datetime(2026, 11, 15, 0, 0)  # tip; US Eastern date 2026-11-14
GD = date(2026, 11, 14)
CLOSE = C - timedelta(minutes=5)
NOW = datetime(2026, 11, 15, 12, 0)
TODAY = date(2026, 11, 15)
OTHERS = ["draftkings", "betmgm", "caesars", "espnbet"]


@pytest.fixture
def db(monkeypatch):
    monkeypatch.delenv("FAIR_PRICE_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("FAIR_PRICE_EXCLUDED_BOOKS", raising=False)
    monkeypatch.delenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", raising=False)
    eng = create_engine("sqlite://")
    for t in (S, F, RecentGames):
        t.__table__.create(eng)
    with eng.begin() as c:
        for t in bt.NAME_TABLES:
            c.execute(text(f"CREATE TABLE {t} (player_id INTEGER, player_name TEXT)"))
        c.execute(text("INSERT INTO pred_team_roster VALUES (1, 'Player A')"))
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


def snap(db, book, o, u, first, last=None, *, line=6.5, pk="player a", commence=C):
    db.add(
        S(
            sport=NBA,
            event_id="ev1",
            commence_time=commence,
            game_date=GD,
            market=M,
            player_name="Player A",
            player_key=pk,
            book=book,
            line=line,
            over_price=o,
            under_price=u,
            book_updated_at=first,
            first_seen_at=first,
            last_seen_at=last or first,
        )
    )
    db.commit()


def others(db, last=CLOSE, line=6.5, first=None):
    for b in OTHERS:
        snap(db, b, -110, -110, first or C - timedelta(hours=10), last, line=line)


def flag(db, **kw):
    d = dict(
        rule_version="fp-shadow-v1",
        engine_version="t",
        tier="primary",
        sport=NBA,
        event_id="ev1",
        game_date=GD,
        commence_time=C,
        market=M,
        player_key="player a",
        side="o",
        book="fanduel",
        line=6.5,
        price=120,
        observed_at=C - timedelta(hours=3),
        flagged_at=C - timedelta(hours=3),
        fair_prob=0.5,
        ev=0.1,
        playable_to=104,
        n_books=4,
        devig_method="power",
        weights_version="equal",
        last_qualified_at=C - timedelta(hours=3),
        n_qualified=1,
    )
    d.update(kw)
    f = F(**d)
    db.add(f)
    db.commit()
    return f


def go(db, **kw):
    r = grade.run(today=TODAY, db=db, now=NOW, **kw)
    db.expire_all()
    return r


def box(db, **kw):
    d = dict(player_id=1, game_date=GD, opponent_team_id=2, minutes=30.0, rebounds=7.0)
    d.update(kw)
    db.add(RecentGames(**d))
    db.commit()


def test_clv_sign(db):
    others(db)  # close consensus 0.5 (fanduel left the market at T-3h)
    snap(db, "fanduel", 120, -140, C - timedelta(hours=3))
    flag(db)
    flag(db, price=-130, book="fanduel2", line=6.5)
    r = go(db)
    assert r["status"] == "ok" and r["flags"] == 2
    a, b = db.query(F).order_by(F.price.desc()).all()
    assert (
        a.close_note == "ok" and a.close_prob == pytest.approx(0.5) and a.n_close == 4
    )
    assert a.clv == pytest.approx(0.5 - 100 / 220)  # +0.04545
    assert b.clv == pytest.approx(0.5 - 130 / 230) and b.clv < 0
    assert a.close_at == CLOSE and not a.is_close


def test_line_conversion_and_no_conversion(db):
    others(db, line=7.5)
    flag(db)
    go(db)
    f = db.query(F).one()
    assert f.close_note == "ok"
    assert f.close_prob == pytest.approx(lines.convert(0.5, 7.5, 6.5, M))
    assert f.close_prob > 0.5  # over is likelier at the lower line
    db.query(S).delete()
    db.commit()
    others(db, line=9.5)  # shift 3.0 > MAX_SHIFT 2.0
    go(db)
    f = db.query(F).one()
    assert f.close_note == "no_conversion" and f.clv is None and f.close_prob is None


@pytest.mark.parametrize(
    "setup, line, side, result, units",
    [
        ("box7", 7.0, "o", "push", 0.0),
        ("box7", 6.5, "o", "hit", 1.2),
        ("box7", 6.5, "u", "miss", -1.0),
        ("dnp_zero", 6.5, "o", "dnp", None),
        ("dnp_other", 6.5, "o", "dnp", None),
        ("none", 6.5, "o", None, None),
    ],
)
def test_results(db, setup, line, side, result, units):
    others(db)
    if setup == "box7":
        box(db)
    elif setup == "dnp_zero":
        box(db, minutes=0.0, rebounds=0.0)
    elif setup == "dnp_other":
        box(db, player_id=9)
    flag(db, line=line, side=side)
    r = go(db)
    f = db.query(F).one()
    assert f.result == result and f.units == pytest.approx(units)
    assert f.actual == (7.0 if setup == "box7" else None)
    assert r["graded"] == (result in ("hit", "miss", "push"))
    assert r["pending"] == (result is None)
    assert r["void"] == (result == "dnp")


def test_unmapped_player_ungraded(db):
    others(db)
    box(db)
    flag(db, player_key="nobody")
    go(db)
    assert db.query(F).one().result == "ungraded"


def test_no_close_and_stale_close(db):
    flag(db)  # no snapshots at all
    go(db)
    f = db.query(F).one()
    assert (f.close_note, f.clv, f.close_prob, f.close_at) == (
        "no_close",
        None,
        None,
        None,
    )
    others(db, last=C - timedelta(minutes=90))
    go(db)
    f = db.query(F).one()
    assert f.close_note == "stale_close" and f.clv is None and f.close_prob is None
    assert f.close_at == C - timedelta(minutes=90)


def test_is_close_flag(db):
    others(db, last=CLOSE)
    snap(db, "fanduel", 120, -140, CLOSE)
    flag(db, observed_at=CLOSE)
    r = go(db)
    f = db.query(F).one()
    assert f.is_close and f.clv is None and f.close_prob is not None
    assert f.next_at is None and f.next_playable is None and r["is_close"] == 1


@pytest.mark.parametrize(
    "nxt, price, playable",
    [(110, 110, True), (100, 100, False), ("gone", None, False)],
)
def test_next_snapshot(db, nxt, price, playable):
    others(db)
    t0, t1 = C - timedelta(hours=3), C - timedelta(hours=2)
    snap(db, "fanduel", 120, -140, t0)
    if nxt != "gone":
        snap(db, "fanduel", nxt, -140, t1)
    flag(db, observed_at=t0)  # playable_to +104
    go(db)
    f = db.query(F).one()
    assert f.next_at == (t1 if nxt != "gone" else CLOSE)
    assert f.next_price == price and f.next_playable is playable


def test_idempotent_and_heals(db):
    others(db)
    snap(db, "fanduel", 120, -140, C - timedelta(hours=3))
    flag(db)
    go(db)

    def row():
        f = db.query(F).one()
        return {c.name: getattr(f, c.name) for c in F.__table__.columns}

    first = row()
    assert first["result"] is None
    go(db)
    assert row() == first
    box(db)  # box score arrives after the first grade
    go(db)
    f = db.query(F).one()
    assert f.result == "hit" and f.units == pytest.approx(1.2)


def test_window_and_four_hour_rule(db):
    others(db)
    flag(db)
    flag(db, book="old", game_date=date(2026, 11, 1))
    flag(db, book="late", commence_time=NOW - timedelta(hours=3))
    assert go(db)["flags"] == 1
    assert db.query(F).filter(F.graded_at.isnot(None)).one().book == "fanduel"


def test_disabled(db, monkeypatch):
    monkeypatch.setenv("FAIR_PRICE_SHADOW_ENABLED", "0")
    assert go(db) == {"status": "disabled"}


def test_equals_backtest(db):
    # three books at -110, X over +150 from T-6h to the close
    for b in "bcd":
        snap(db, b, -110, -110, C - timedelta(hours=10), CLOSE)
    snap(db, "a", 150, -180, C - timedelta(hours=6), CLOSE)
    box(db)
    now = C - timedelta(hours=6) + timedelta(minutes=1)
    r = shadow.run(now=now, db=db, weights_override={(NBA, M): None})
    assert r["new"] >= 1
    rows = db.query(S).all()
    quotes = [shadow._snap(x) for x in rows]
    rec = bt.run_backtest(quotes, {"player a": 1}, bt.load_box(db, GD, GD))["flags"]
    rec = {(x["book"], x["side"]): x for x in rec if x["primary"]}
    go(db)
    f = db.query(F).filter(F.book == "a", F.side == "o").one()
    x = rec[("a", "o")]
    assert f.close_prob == pytest.approx(x["p_close"]) and f.n_close == x["n_close"]
    assert f.clv == pytest.approx(x["clv"])
    assert f.result == ("hit" if x["win"] else "miss")
    assert f.baseline["clv"] == pytest.approx(x["rand_clv"])
    assert f.baseline["win"] == x["rand_win"]
    assert (f.baseline["book"], f.baseline["price"]) == (
        x["rand_book"],
        x["rand_price"],
    )
    assert f.units == pytest.approx(odds_math.units_won(150, x["win"]))
