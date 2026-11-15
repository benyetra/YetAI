"""Shadow flagger (SQLite): hand-computed thresholds, gates, dedupe, tiers, kill switch."""

import math
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import FairPriceShadowFlag as F
from app.models.predictions_models import OddsLineSnapshot as S
from app.services.fair_price import flags, shadow

NOW = datetime(2026, 11, 15, 20, 0)
COMMENCE = datetime(2026, 11, 15, 23, 0)
NBA = "basketball_nba"
M = "player_rebounds"
EQ = {(NBA, M): None}  # equal weights
OTHERS = ["draftkings", "betmgm", "caesars", "espnbet"]  # -110/-110 -> p_over 0.5


@pytest.fixture
def db(monkeypatch):
    monkeypatch.delenv("FAIR_PRICE_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("FAIR_PRICE_EXCLUDED_BOOKS", raising=False)
    monkeypatch.delenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", raising=False)
    engine = create_engine("sqlite://")
    S.__table__.create(engine)
    F.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def snap(
    db, book, o, u, at, *, sport=NBA, market=M, line=6.5, commence=COMMENCE, last=None
):
    db.add(
        S(
            sport=sport,
            event_id="ev1" if sport == NBA else "ev2",
            commence_time=commence,
            game_date=commence.date(),
            market=market,
            player_name="Player A",
            player_key="player_a",
            book=book,
            line=line,
            over_price=o,
            under_price=u,
            book_updated_at=at,
            first_seen_at=at,
            last_seen_at=last or at,
        )
    )
    db.commit()


def pass_at(db, at, flagged_over=112, others=OTHERS, **kw):
    snap(db, "fanduel", flagged_over, -130, at, **kw)
    for b in others:
        snap(db, b, -110, -110, at, **kw)


def run(db, now=NOW, **kw):
    kw.setdefault("weights_override", EQ)
    return shadow.run(now=now, db=db, **kw)


def test_threshold_ev_five_percent(db):
    # others p=0.5; +112 -> 0.5*2.12-1 = 0.06 flagged; +108 -> 0.5*2.08-1 = 0.04 not
    pass_at(db, NOW - timedelta(minutes=5), flagged_over=112)
    r = run(db)
    assert r["status"] == "ok" and r["new"] == 1 and r["by_tier"] == {"primary": 1}
    f = db.query(F).one()
    assert (f.book, f.side, f.line, f.price, f.n_books) == ("fanduel", "o", 6.5, 112, 4)
    assert f.fair_prob == pytest.approx(0.5) and f.ev == pytest.approx(0.06)
    assert f.playable_to == flags.playable_to(0.5, 0.02) == 104
    assert f.rule_version == shadow.RULE_VERSION and f.devig_method == "power"
    assert f.weights_version == "override" and f.n_qualified == 1
    assert f.hours_before == pytest.approx((3 * 60 + 5) / 60)
    assert f.game_date == COMMENCE.date() and f.player_name == "Player A"
    assert set(f.consensus) == set(OTHERS)
    assert f.consensus["betmgm"] == {"line": 6.5, "p": pytest.approx(0.5), "w": 1.0}


def test_just_under_threshold_not_flagged(db):
    pass_at(db, NOW - timedelta(minutes=5), flagged_over=108)
    assert run(db)["new"] == 0 and db.query(F).count() == 0


def test_min_books(db):
    pass_at(db, NOW - timedelta(minutes=5), others=OTHERS[:2])
    assert run(db)["new"] == 0
    pass_at(db, NOW - timedelta(minutes=4), others=OTHERS[:3])  # 3 others -> flags
    assert run(db)["new"] == 1


def test_quote_age(db):
    pass_at(db, NOW - timedelta(minutes=31))
    r = run(db)
    assert r["new"] == 0 and r["groups"] == 0 and r["recent_snapshots"] is True
    pass_at(db, NOW - timedelta(minutes=29))
    assert run(db)["new"] == 1
    f = db.query(F).one()
    assert f.quote_age_min == pytest.approx(29) and f.observed_at == NOW - timedelta(
        minutes=29
    )


def test_consensus_only_book_never_flagged_but_in_consensus(db):
    t = NOW - timedelta(minutes=5)
    snap(db, "novig", -160, 140, t)  # best price by far, never a flag
    pass_at(db, t)
    rule = flags.FlagRule(
        method="multiplicative", consensus_only=frozenset({"novig", "prophetx"})
    )
    run(db, rule=rule)
    f = db.query(F).one()
    assert f.book == "fanduel" and "novig" in f.consensus
    # novig p_over multiplicative: (130/230 ... use -160/+140 as written)
    # novig over -160 / under +140, multiplicative de-vig
    p_nov = (160 / 260) / ((160 / 260) + (100 / 240))
    logit = lambda p: math.log(p / (1 - p))  # noqa: E731
    fair = 1 / (
        1 + math.exp(-logit(p_nov) / 5)
    )  # 4 books at 0 plus novig, equal weights
    assert f.fair_prob == pytest.approx(fair) and f.n_books == 5


def test_reference_only_pinnacle_never_flagged(db):
    t = NOW - timedelta(minutes=5)
    snap(db, "pinnacle", 150, -170, t)
    pass_at(db, t, flagged_over=-110)
    assert run(db)["new"] == 0
    assert db.query(F).filter(F.book == "pinnacle").count() == 0


def test_dedupe_across_runs(db):
    t1, t2, t3 = (NOW - timedelta(minutes=m) for m in (12, 7, 2))
    pass_at(db, t1, flagged_over=112)
    pass_at(db, t2, flagged_over=114)
    pass_at(db, t3, flagged_over=116)
    assert run(db, now=t1 + timedelta(minutes=1))["new"] == 1
    assert run(db, now=t2 + timedelta(minutes=1))["updated"] == 1
    assert run(db, now=t3 + timedelta(minutes=1))["updated"] == 1
    f = db.query(F).one()
    assert f.observed_at == t1 and f.price == 112 and f.line == 6.5
    assert f.n_qualified == 3 and f.last_qualified_at == t3 and f.last_price == 116
    r = run(db, now=t3 + timedelta(minutes=1))  # same now: no change
    assert (r["new"], r["updated"]) == (0, 0)
    db.refresh(f)
    assert f.n_qualified == 3 and db.query(F).count() == 1


def test_dedupe_single_run_over_three_times(db):
    t1, t2, t3 = (NOW - timedelta(minutes=m) for m in (12, 7, 2))
    for t, o in ((t1, 112), (t2, 114), (t3, 116)):
        pass_at(db, t, flagged_over=o)
    r = run(db)
    assert (r["times"], r["new"], r["updated"]) == (3, 1, 2)
    f = db.query(F).one()
    assert f.n_qualified == 3 and f.observed_at == t1 and f.last_price == 116


def test_pregame_only(db):
    pass_at(db, COMMENCE - timedelta(minutes=2), commence=COMMENCE)
    # now after tip: nothing
    assert run(db, now=COMMENCE + timedelta(minutes=1))["new"] == 0
    # observation at tip (not yet visible before it) flags nothing at now < tip
    snap(db, "fanduel", 150, -180, COMMENCE, last=COMMENCE)
    for b in OTHERS:
        snap(db, b, -110, -110, COMMENCE, last=COMMENCE)
    assert (
        run(db, now=COMMENCE - timedelta(seconds=1))["new"] == 1
    )  # only the earlier pass
    assert db.query(F).one().observed_at == COMMENCE - timedelta(minutes=2)


def test_tiers_and_weights_version(db):
    t = NOW - timedelta(minutes=5)
    pass_at(db, t, market="player_points")
    pass_at(db, t, market="player_assists")
    pass_at(db, t, sport="icehockey_nhl", market="player_points")
    run(db, weights_override={})
    tiers = {(f.sport, f.market): (f.tier, f.weights_version) for f in db.query(F)}
    assert tiers == {
        (NBA, "player_points"): ("secondary", "equal"),
        (NBA, "player_assists"): ("primary", "equal"),
        ("icehockey_nhl", "player_points"): ("secondary", "equal"),
    }
    db.query(F).delete()
    db.commit()
    shadow.run(
        now=NOW, db=db
    )  # no override: active() -> seed / equal, no weights table
    nhl = db.query(F).filter(F.sport == "icehockey_nhl").one()
    assert nhl.tier == "secondary" and nhl.weights_version == "equal"


def test_no_recent_snapshots(db):
    assert run(db) == {
        "status": "ok",
        "rule_version": shadow.RULE_VERSION,
        "groups": 0,
        "times": 0,
        "new": 0,
        "updated": 0,
        "by_tier": {},
        "recent_snapshots": False,
    }
    pass_at(db, NOW - timedelta(hours=10))
    assert run(db)["recent_snapshots"] is True


def test_kill_switch(db, monkeypatch):
    pass_at(db, NOW - timedelta(minutes=5))
    for v in ("0", "false", "No", "OFF"):
        monkeypatch.setenv("FAIR_PRICE_SHADOW_ENABLED", v)
        assert run(db) == {"status": "disabled"}
    assert db.query(F).count() == 0
    monkeypatch.setenv("FAIR_PRICE_SHADOW_ENABLED", "1")
    assert run(db)["new"] == 1


def test_rule_version(monkeypatch):
    monkeypatch.delenv("FAIR_PRICE_EXCLUDED_BOOKS", raising=False)
    monkeypatch.delenv("FAIR_PRICE_CONSENSUS_ONLY_BOOKS", raising=False)
    assert shadow.rule_version(flags.default_rule()) == shadow.RULE_VERSION
    a = shadow.rule_version(flags.FlagRule(min_ev=0.03))
    b = shadow.rule_version(
        flags.FlagRule(
            consensus_only=frozenset({"novig", "prophetx"}),
            excluded_books=frozenset({"x"}),
        )
    )
    assert a.startswith("fp-shadow-v1+") and len(a.split("+")[1]) == 8
    assert b.startswith("fp-shadow-v1+") and a != b
    assert (
        shadow.rule_version(flags.FlagRule()) != shadow.RULE_VERSION
    )  # empty consensus_only


def test_run_never_raises():
    assert shadow.run(now=NOW, db=object())["status"] == "error"
