import random
from datetime import date, datetime, timedelta

import pytest

from app.services.fair_price import backtest as bt
from app.services.fair_price import flags as fp
from app.services.fair_price.flags import FlagRule

C = datetime(2026, 11, 15, 0, 0)  # tip; US Eastern date 2026-11-14
GD = date(2026, 11, 14)
M = "player_rebounds"


def sq(book, first, last, o=-110, u=-110, line=6.5, pk="p", event="e1", market=M):
    return bt.SnapQuote(event, market, pk, book, line, o, u, first, last, C, GD)


CLOSE = C - timedelta(minutes=5)
BOX = {(1, GD): {"minutes": 30, "rebounds": 7, "assists": 1, "points": 10}}
KEYS = {"p": 1}


def scenario(x_last):
    """Three books at -110/-110 from T-10h to the close; X over +150 from T-6h to x_last."""
    qs = [sq(b, C - timedelta(hours=10), CLOSE) for b in "bcd"]
    qs.append(sq("a", C - timedelta(hours=6), x_last, o=150, u=-180))
    if x_last < CLOSE:  # X back in line until the close
        qs.append(sq("a", x_last + timedelta(minutes=1), CLOSE))
    return qs


def test_flag_clv_result_and_dedupe():
    res = bt.run_backtest(scenario(C - timedelta(hours=3)), KEYS, BOX)
    fl = res["flags"]
    # replay times: T-10h, T-6h, T-3h, T-179m, close. X is flagged at T-6h and T-3h only.
    assert [(f["t"], f["primary"]) for f in fl] == [
        (C - timedelta(hours=6), True),
        (C - timedelta(hours=3), False),
    ]
    f = fl[0]
    assert (f["book"], f["side"], f["price"], f["n_books"]) == ("a", "o", 150, 3)
    # others are 0.5, so fair 0.5 and EV = 0.5 * 2.5 - 1; close consensus 0.5:
    # CLV = 0.5 - 100/250 = 0.10
    assert f["ev"] == pytest.approx(0.25)
    assert f["p_close"] == pytest.approx(0.5) and f["n_close"] == 4
    assert f["clv"] == pytest.approx(0.10) and f["ev_close"] == pytest.approx(0.25)
    assert f["win"] is True  # 7 > 6.5, +150 pays 1.5 units
    t = res["summary"]["tables"]
    assert t["overall_primary"]["n"] == 1
    assert t["overall_primary"]["roi"] == pytest.approx(1.5)
    assert t["all_flags"]["n"] == 2
    assert res["summary"]["counts"]["flags_primary"] == 1


def test_flag_at_close_is_excluded_from_clv():
    res = bt.run_backtest(scenario(CLOSE), KEYS, BOX)
    close = [f for f in res["flags"] if f["is_close"]]
    assert len(close) == 1 and close[0]["clv"] is None and not close[0]["primary"]
    t = res["summary"]["tables"]
    assert t["overall_primary"]["n"] == 1 and t["overall_primary"]["clv_n"] == 1
    assert t["is_close_roi_only"]["n"] == 1
    assert t["is_close_roi_only"]["roi"] == pytest.approx(1.5)
    assert t["is_close_roi_only"]["clv_n"] == 0


def test_voids_are_not_scored():
    box = {(1, GD): {"minutes": 0, "rebounds": 7}}
    res = bt.run_backtest(scenario(C - timedelta(hours=3)), KEYS, box)
    assert res["flags"][0]["win"] is None and res["flags"][0]["void"] == "no_minutes"
    assert res["summary"]["tables"]["overall_primary"]["decided"] == 0
    res = bt.run_backtest(scenario(C - timedelta(hours=3)), {}, BOX)
    assert res["summary"]["counts"]["void_primary"] == {"no_player": 1}


def test_walk_forward_weights_use_only_earlier_months():
    def rows(seed, flip=False, n=120):
        r = random.Random(seed)
        out = []
        for _ in range(n):
            y = r.random() < 0.5
            a = 0.75 if y else 0.25  # a is informative, b is noise
            b = r.choice([0.3, 0.7])
            out.append(({"a": a, "b": b}, int(y) ^ int(flip)))
        return out

    base = {(M, "2026-11"): rows(1), (M, "2026-12"): rows(2), (M, "2027-01"): rows(3)}
    p = bt.Params(min_n_weights=50)
    w = bt.walk_forward_weights(base, p)
    assert w[(M, "2026-11")]["weights"] is None
    assert w[(M, "2026-12")]["n_rows"] == 120
    assert w[(M, "2027-01")]["n_rows"] == 240
    alt = dict(base)
    alt[(M, "2026-12")] = rows(2, flip=True)
    alt[(M, "2027-01")] = rows(9, flip=True)
    w2 = bt.walk_forward_weights(alt, p)
    assert w2[(M, "2026-11")] == w[(M, "2026-11")]
    assert w2[(M, "2026-12")] == w[(M, "2026-12")]  # own and later months do not matter
    assert w2[(M, "2027-01")] != w[(M, "2027-01")]  # earlier month does
    assert w[(M, "2026-12")]["weights"]["a"] > w[(M, "2026-12")]["weights"]["b"]


def flag3():
    base = {"game_date": GD, "market": M, "ev": 0.1}
    return [
        dict(base, event_id="e", player_key="p1", price=100, win=True),
        dict(base, event_id="e", player_key="p2", price=-200, win=True),
        dict(base, event_id="e", player_key="p3", price=200, win=False),
    ]


def test_placebo_expectation_and_flips():
    fl = flag3()
    p = bt.Params(placebo_runs=400, seed=7)
    s = bt.placebo_summary(fl, p)
    # 0.5 * decimal - 1: +100 -> 0, -200 -> -0.25, +200 -> +0.5; mean = 0.25 / 3
    assert s["expectation"] == pytest.approx(0.25 / 3)
    assert s["runs"] == 400 and abs(s["mean_hit_rate"] - 0.5) < 0.1
    assert s == bt.placebo_summary(fl, p)  # seeded
    assert bt.placebo_summary(fl, bt.Params(placebo_runs=400, seed=8)) != s
    same_prop = dict(fl[0], book="x")  # whole props flip together
    assert all(bt._coin(7, r, fl[0]) == bt._coin(7, r, same_prop) for r in range(20))
    assert {bt._coin(7, r, fl[0]) for r in range(20)} == {True, False}


def test_random_baseline_seeded_and_in_candidates():
    qs = scenario(C - timedelta(hours=3))
    a = bt.run_backtest(qs, KEYS, BOX, bt.Params(seed=3))["flags"][0]
    b = bt.run_backtest(qs, KEYS, BOX, bt.Params(seed=3))["flags"][0]
    assert {k: v for k, v in a.items() if k.startswith("rand_")} == {
        k: v for k, v in b.items() if k.startswith("rand_")
    }
    assert a["rand_book"] in "abcd" and a["rand_side"] in "ou"
    assert a["rand_clv"] is not None


def test_wilson_and_clustered():
    lo, hi = bt.wilson(55, 100)
    assert (lo, hi) == pytest.approx((0.4524, 0.6438), abs=1e-4)
    c = bt.clustered_mean([1, 2, 3, 4], ["a", "a", "b", "b"])
    # mean 2.5; cluster sums of deviations -2, +2; G = 2 -> se = sqrt(2 * 8) / 4 = 1
    assert c["mean"] == 2.5 and c["se"] == pytest.approx(1.0)
    assert c["lo"] == pytest.approx(2.5 - 1.96)
    assert bt.clustered_mean([1.0, 2.0], ["a", "a"])["se"] is None


def row(n=500, clv_lo=0.01, clv_hi=0.05, roi=0.02, roi_hi=0.1):
    return dict(n=n, clv_lo=clv_lo, clv_hi=clv_hi, roi=roi, roi_hi=roi_hi)


def test_verdicts():
    ok_pl = {"mean_roi": 0.0, "expectation": 0.001, "se": 0.01}
    rand = {"clv_lo": -0.02}
    pos = {"lo": 0.005}
    assert bt.decide(row(), ok_pl, rand, pos) == "GO"
    assert bt.decide(row(roi=-0.01), ok_pl, rand, pos) == "INCONCLUSIVE"
    assert bt.decide(row(), ok_pl, rand, {"lo": -0.01}) == "INCONCLUSIVE"
    assert bt.decide(row(n=299), ok_pl, rand, pos) == "INCONCLUSIVE"
    neg = row(clv_lo=-0.05, clv_hi=-0.001, roi=-0.03)
    assert bt.decide(neg, ok_pl, rand, {"lo": -1}) == "NO GO"
    roi_neg = row(n=1000, clv_lo=-0.02, clv_hi=0.02, roi=-0.1, roi_hi=-0.01)
    assert bt.decide(roi_neg, ok_pl, rand, {"lo": -1}) == "NO GO"
    assert bt.decide(dict(roi_neg, n=999), ok_pl, rand, {"lo": -1}) == "INCONCLUSIVE"
    bad_pl = {"mean_roi": 0.05, "expectation": 0.0, "se": 0.01}
    assert bt.decide(row(), bad_pl, rand, pos) == "INVALID"
    assert bt.decide(row(), ok_pl, {"clv_lo": 0.001}, pos) == "INVALID"


def test_fast_loo_equals_evaluate_prop_across_lines():
    at = C - timedelta(hours=2)
    spec = [
        ("a", 6.5, 120, -150),
        ("b", 6.5, -110, -110),
        ("c", 7.5, -135, 115),
        ("d", 7.5, 105, -125),
        ("e", 5.5, -160, 135),
        ("f", 6.5, -105, -115),
        ("pinnacle", 7.5, -120, 100),
    ]
    qs = [
        sq(b, at - timedelta(minutes=9), at, o=o, u=u, line=ln) for b, ln, o, u in spec
    ]
    w = {"a": 2.0, "c": 0.5, "pinnacle": 1.7}
    rule = FlagRule(min_ev=-0.5, min_books=3, p_range=(0.01, 0.99))
    slow = fp.evaluate_prop(qs, at, M, w, rule, C)
    fast = bt.fast_prop_flags(qs, at, M, w, rule, C)
    assert len(slow) > 6
    assert [(f.book, f.side, f.line, f.price, f.n_books) for f in slow] == [
        (f.book, f.side, f.line, f.price, f.n_books) for f in fast
    ]
    for s, f in zip(slow, fast):
        assert f.fair_prob == pytest.approx(s.fair_prob, abs=1e-9)
        assert f.ev == pytest.approx(s.ev, abs=1e-9)
        assert (f.playable_to, f.expires_at) == (s.playable_to, s.expires_at)


def test_summary_and_csv_byte_identical():
    qs = scenario(C - timedelta(hours=3))
    r1, r2 = (bt.run_backtest(qs, KEYS, BOX) for _ in range(2))
    assert bt.summary_json(r1["summary"]) == bt.summary_json(r2["summary"])
    assert bt.flags_csv(r1["flags"]) == bt.flags_csv(r2["flags"])
    assert "Verdict" in bt.report_md(r1["summary"])
    assert r1["summary"]["verdict"] in bt.VERDICT_RULES
    assert r1["summary"]["devig_calibration"] == r2["summary"]["devig_calibration"]


def test_loaders_roundtrip_sqlite():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from app.models.predictions_models import OddsLineSnapshot, RecentGames

    eng = create_engine("sqlite://")
    OddsLineSnapshot.__table__.create(eng)
    RecentGames.__table__.create(eng)
    with eng.begin() as c:
        for t in bt.NAME_TABLES:
            c.execute(text(f"CREATE TABLE {t} (player_id INTEGER, player_name TEXT)"))
        c.execute(text("INSERT INTO pred_team_roster VALUES (1, 'Jay Smith')"))
        c.execute(text("INSERT INTO pred_points_projections VALUES (1, 'Jay Smith')"))
        c.execute(text("INSERT INTO pred_points_projections VALUES (2, 'Ann Lee')"))
        c.execute(text("INSERT INTO pred_rebounds_projections VALUES (3, 'Ann Lee')"))
    with sessionmaker(bind=eng)() as s:
        s.add(
            OddsLineSnapshot(
                sport=bt.SPORT,
                event_id="e",
                market=M,
                player_key="jay smith",
                book="a",
                line=6.5,
                over_price=-110,
                under_price=-110,
                game_date=GD,
                commence_time=C,
                first_seen_at=C,
                last_seen_at=C,
            )
        )
        s.add(
            RecentGames(
                player_id=1,
                game_date=GD,
                opponent_team_id=2,
                minutes=30.0,
                rebounds=7.0,
            )
        )
        s.commit()
        keys, dropped = bt.load_player_keys(s)
        assert (
            list(keys.values()) == [1] and dropped == 1
        )  # 'ann lee' maps to ids 2 and 3
        q = bt.load_snapshots(s, [M], GD, GD)
        assert len(q) == 1 and q[0].book == "a"
        assert bt.load_box(s, GD, GD)[(1, GD)]["rebounds"] == 7.0
