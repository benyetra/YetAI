"""Record gate: keys whose record at real prices is losing are withheld; unproven keys wait.

Every graded call in a record is priced (best_price) and passed the selector's EV rule;
nothing is valued at -110.
"""

import itertools
from datetime import date, timedelta

import pytest

from app.models.database_models import BetSource, BetType, YetAIBet
from app.models.predictions_models import (
    PointsActuals,
    PointsProjections,
    ReboundsActuals,
    ReboundsProjections,
)
from app.services.auto_pick import ev
from app.services.auto_pick import record_gate as rg
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.record_gate import combine, load_records, record_key
from tests.auto_pick.test_orchestrator import NOW, _bets, _cand, _provider

POINTS = ("NBA", "player_prop", "points")
REBOUNDS = ("NBA", "player_prop", "rebounds")
PRA = ("NBA", "player_prop", "pra")
# At -125 a win pays 0.8u. fair 0.58 clears both EV gates (consensus EV +0.044).
PRICE, FAIR = -125, 0.58


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "AUTO_PICK_RECORD_GATE_ENABLED",
        "AUTO_PICK_REQUIRE_PROVEN_RECORD",
        "AUTO_PICK_PROVE_IN_KEYS",
        "AUTO_PICK_RECORD_MIN_PICKS",
        "AUTO_PICK_RECORD_WINDOW_DAYS",
        "AUTO_PICK_RECORD_MIN_ROI",
        "AUTO_PICK_RECORD_SHRINK_PICKS",
        "AUTO_YETAI_PICKS_AUTO_PUBLISH",
        "AUTO_YETAI_PICKS_MIN_SCORE",
    ):
        monkeypatch.delenv(k, raising=False)
    from app.services.auto_pick import orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_can_grade", lambda league, market, stat: True)


def _seed_points(db, n, hit_rate, *, offset=1, first_id=0, **kw):
    _seed(db, PointsProjections, PointsActuals, "points", n, hit_rate, offset, first_id, **kw)  # fmt: skip


def _seed_rebounds(db, n, hit_rate, *, first_id=0, **kw):
    _seed(db, ReboundsProjections, ReboundsActuals, "rebounds", n, hit_rate, 1, first_id, **kw)  # fmt: skip


def _seed(db, proj, act, stat, n, hit_rate, offset, first_id, price=PRICE, fair=FAIR):
    """n graded over calls (line 20.5, projection 30); ``hit_rate`` is the share that hit.
    ``price`` / ``fair`` None = the row's last write had no fresh quote (unpriced)."""
    day = NOW.date() - timedelta(days=offset)
    hits = round(n * hit_rate)
    for i in range(first_id, first_id + n):
        extra = {"player_name": f"P{i}"}
        if stat == "rebounds":
            extra["opponent_team_name"] = "X"
        db.add(
            proj(
                date=day,
                player_id=i,
                **{f"projected_{stat}": 30.0},
                fanduel_line=20.5,
                fanduel_over_under="over",
                best_line=20.5 if price else None,
                best_price=price,
                best_fair_prob=fair,
                **extra,
            )
        )
        db.add(
            act(
                date=day,
                player_id=i,
                **{f"actual_{stat}": 25.0 if i - first_id < hits else 10.0},
                **{f"projected_{stat}": 30.0},
                **extra,
            )
        )
    db.commit()


_ids = itertools.count()


def _bet(db, won, odds, settled, league="NBA", stat="points", sv=ev.SELECTION_VERSION):
    db.add(
        YetAIBet(
            id=f"b{next(_ids)}",
            title="t",
            bet_type=BetType.PROP,
            selection="s",
            odds=odds,
            confidence=70,
            status="won" if won else "lost",
            source=BetSource.AUTO,
            sport="basketball_nba",
            settled_at=settled,
            prediction_factors={
                "selection_version": sv,
                "grading": {"league": league, "market": "player_prop", "stat": stat},
            },
        )
    )


def _prop(n, stat):
    c = _cand(n, league="NBA", selection=f"Player {n} OVER 5.5 {stat}")
    c.projection_metadata["stat"] = stat
    return c


def _fake_rows(monkeypatch, part, rows):
    """Feed ``rows`` (dicts) to the NBA prop loader as the merged rows of ``part``."""
    monkeypatch.setattr(
        "app.services.nba_accuracy_service._nba_season_window_rows",
        lambda db, start, end: [(part, "x", rows, {})],
    )


def _row(i, hit, *, stat="points", price=PRICE, fair=FAIR, version="v1", day=1, **kw):
    """A stored over call: projection 30 vs line 20.5, graded hit or miss."""
    r = {
        "id": i,
        "date": NOW.date() - timedelta(days=day),
        "model_version": version,
        f"projected_{stat}": 30.0,
        "fanduel_over_under": "over",
        "best_line": 20.5,
        "best_price": price,
        "best_fair_prob": fair,
        f"actual_{stat}": 25.0 if hit else 10.0,
    }
    r.update(kw)
    return r


def _state(db, key):
    return {r["key"]: r for r in rg.all_key_rows(db, NOW)}[rg.key_label(key)]


async def _run(db, cands):
    return await AutoPickOrchestrator(
        db=db, providers=[_provider(cands)], now=NOW
    ).run()


# ---------- the arithmetic ----------


def test_even_split_at_minus_125_over_200_priced_rows_is_withheld_losing(
    sqlite_db, monkeypatch
):
    # 100 of 200 hit at -125: -20u, shrunk ROI -9%. At -110 this would be +4.5u: open.
    _fake_rows(monkeypatch, "points_ou", [_row(i, i < 100) for i in range(200)])
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert (rec.proj_n, rec.proj_hits) == (200, 100)
    assert rec.proj_units == pytest.approx(-20.0)
    assert rec.withheld and rg.drop_reason(rec) == "losing_record"
    assert _state(sqlite_db, POINTS)["state"] == "withheld-losing"


def test_large_sample_slightly_negative_is_withheld_no_cap(sqlite_db, monkeypatch):
    # 935 of 1700 at -125 = -17u, ROI about -1%: inside the -2% dead band, but past
    # LARGE_SAMPLE the cut is 0. The old code capped the record at 60 calls: open.
    _fake_rows(monkeypatch, "points_ou", [_row(i, i < 935) for i in range(1700)])
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert rec.n_eff == 1700 and -0.02 < rec.shrunk_roi < 0
    assert rec.withheld
    # the same ROI on a small sample sits in the dead band and is open
    assert not combine(POINTS, proj_n=200, proj_hits=100, proj_units=-3.0).withheld


def test_small_sample_shrink_holds():
    # 30 calls at raw ROI -2.5% (-0.75u): shrunk ROI -1.5%, above the -2% cut
    rec = combine(POINTS, proj_n=30, proj_hits=16, proj_units=-0.75)
    assert rec.shrunk_roi == pytest.approx(-0.75 / 50)
    assert not rec.withheld
    # under min_picks never withheld, however bad
    assert not combine(POINTS, proj_n=29, proj_hits=0, proj_units=-29.0).withheld
    assert combine(POINTS, proj_n=30, proj_hits=0, proj_units=-30.0).withheld


def test_key_at_exact_breakeven_is_open_and_dead_band_does_not_flip():
    assert not combine(POINTS, proj_n=210, proj_hits=105, proj_units=0.0).withheld
    # a hair under breakeven sits in the dead band: still open
    states = [
        combine(POINTS, proj_n=210, proj_hits=105, proj_units=u).withheld
        for u in (0.0, -1.0, 0.5, -3.0, -4.0)
    ]
    assert states == [False] * 5
    assert combine(POINTS, proj_n=210, proj_hits=90, proj_units=-30.0).withheld


def test_there_is_no_prior_cap_and_no_minus_110(monkeypatch):
    rec = combine(
        POINTS, proj_n=400, proj_hits=192, proj_units=-30.0, bet_n=5, bet_units=-5.0
    )
    assert rec.n_eff == 405  # no cap: all 400 count
    assert rec.shrunk_roi == pytest.approx(-35.0 / (405 + 20))
    assert not hasattr(rg, "prior_max_picks") and not hasattr(rg, "BREAKEVEN_ODDS")
    # hits alone are never valued: without units a key has no value
    assert combine(POINTS, proj_n=100, proj_hits=55).shrunk_roi == 0


def test_kill_switch_and_env_overrides(monkeypatch):
    losing = dict(proj_n=100, proj_hits=40, proj_units=-30.0)
    assert combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_GATE_ENABLED", "false")
    assert not combine(POINTS, **losing).withheld
    assert rg.drop_reason(None, POINTS) is None
    monkeypatch.setenv("AUTO_PICK_RECORD_GATE_ENABLED", "true")
    monkeypatch.setenv("AUTO_PICK_RECORD_MIN_PICKS", "200")
    assert not combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_MIN_PICKS", "abc")
    assert rg.min_picks() == 30 and combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_MIN_ROI", "-0.5")
    assert not combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_WINDOW_DAYS", "7")
    assert rg.window_days() == 7


# ---------- what goes into the record ----------


def test_unpriced_rows_contribute_nothing(sqlite_db):
    # last write had no fresh quote: no best_price / best_fair_prob
    _seed_points(sqlite_db, 100, 0.3, price=None, fair=None)
    _seed_points(sqlite_db, 50, 0.3, fair=None, first_id=500)  # price but no fair prob
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert (rec.proj_n, rec.n_eff, rec.proj_units, rec.withheld) == (0, 0, 0.0, False)


def test_priced_rows_are_valued_at_best_price_through_the_real_loader(sqlite_db):
    _seed_points(sqlite_db, 100, 0.55)  # 55 hits at -125
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert (rec.proj_n, rec.proj_hits) == (100, 55)
    assert rec.proj_units == pytest.approx(55 * 0.8 - 45)


def test_rows_of_an_older_model_version_are_excluded(sqlite_db, monkeypatch):
    old = [_row(i, True, version="v1", day=3) for i in range(80)]
    new = [_row(100 + i, i < 2, version="v2", day=1) for i in range(40)]
    _fake_rows(monkeypatch, "points_ou", old + new)
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert rec.version == "v2" and (rec.proj_n, rec.proj_hits) == (40, 2)
    # None is a version too: legacy unversioned rows are the current model while they are latest
    legacy = [_row(i, True, version=None, day=1) for i in range(10)]
    _fake_rows(monkeypatch, "points_ou", old + legacy)
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert rec.version is None and rec.proj_n == 10


def test_current_version_rows_ties_break_on_projected_at_then_id():
    from datetime import datetime

    d = date(2026, 5, 1)
    rows = [
        {"date": d, "id": 9, "model_version": "a"},
        {"date": d, "id": 1, "model_version": "b", "projected_at": datetime(2026, 5, 1, 9)},
        {"date": d, "id": 2, "model_version": "c", "projected_at": datetime(2026, 5, 1, 8)},
    ]  # fmt: skip
    assert rg.current_version_rows(rows, "date")[0] == "b"
    assert rg.current_version_rows(rows[:1] + rows[2:], "date")[0] == "c"
    assert rg.current_version_rows([], "date") == (None, [])


def test_only_rows_the_selector_would_consider_are_graded(sqlite_db, monkeypatch):
    rows = [
        _row(1, True),  # qualifies: graded at -125 -> +0.8u
        _row(2, True, fair=0.50),  # consensus EV negative at -125
        _row(3, True, fair=0.56, projected_points=20.5),  # EV 0.008 <= MIN_EV
        _row(4, True, best_price=None),
        _row(5, True, best_fair_prob=None),
        _row(6, True, fanduel_over_under=None),
    ]
    _fake_rows(monkeypatch, "points_ou", rows)
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert (rec.proj_n, rec.proj_hits) == (1, 1)
    assert rec.proj_units == pytest.approx(0.8)
    # the rule is ev.py's own
    assert ev.gate_reason(ev.prop_ev("points", "o", 30.0, 20.5, -125, 0.50)) is not None


def test_fill_floor_edge_is_gone():
    assert not hasattr(rg, "fill_floor_edge")


def test_pra_has_a_record_and_must_prove_in(sqlite_db, monkeypatch):
    _fake_rows(
        monkeypatch,
        "pra_ou",
        [_row(i, i < 40, stat="pra") for i in range(60)],
    )
    rec = load_records(sqlite_db, NOW, ("nba_props",))[PRA]
    assert rec.proj_n == 60 and rec.shrunk_roi > 0 and not rec.withheld
    assert rg.drop_reason(rec) == "unproven_record"  # 60 < 100 qualifying rows
    assert rg.withheld_keys(sqlite_db, NOW, {PRA}, ("nba_props",)) == {
        PRA: "unproven_record"
    }
    assert "NBA/player_prop/pra" in rg.DEFAULT_PROVE_IN_KEYS


def test_no_leak_of_today_or_future_results(sqlite_db, monkeypatch):
    seen = {}

    def loader(db, start, end):
        seen["window"] = (start, end)
        return {}

    monkeypatch.setitem(rg.PROJECTION_LOADERS, "nba_props", loader)
    rg.load_projection_records(sqlite_db, NOW)
    assert seen["window"][1] == NOW.date() - timedelta(days=1)
    for _ in range(40):
        _bet(sqlite_db, False, -110, NOW + timedelta(hours=1), stat="blocks")
    sqlite_db.commit()
    assert ("NBA", "player_prop", "blocks") not in rg.load_bet_records(sqlite_db, NOW)


def test_recovery_when_projection_record_turns_winning(sqlite_db):
    _seed_points(sqlite_db, 120, 0.40)
    assert load_records(sqlite_db, NOW)[POINTS].withheld
    _seed_points(sqlite_db, 400, 0.80, offset=2, first_id=1000)
    assert not load_records(sqlite_db, NOW)[POINTS].withheld


# ---------- bet record ----------


def test_bet_units_use_stored_odds_for_keys_without_a_projection_record(sqlite_db):
    settled = NOW - timedelta(days=3)
    for _ in range(10):
        _bet(sqlite_db, True, 150, settled, league="WNBA", stat="points")
        _bet(sqlite_db, False, 150, settled, league="WNBA", stat="points")
    for _ in range(12):
        _bet(sqlite_db, True, -200, settled, league="WNBA", stat="rebounds")
    for _ in range(8):
        _bet(sqlite_db, False, -200, settled, league="WNBA", stat="rebounds")
    sqlite_db.commit()
    recs = load_records(sqlite_db, NOW)
    wp, wr = ("WNBA", "player_prop", "points"), ("WNBA", "player_prop", "rebounds")
    assert recs[wp].bet_units == pytest.approx(5.0) and recs[wp].shrunk_roi > 0
    assert recs[wr].bet_units == pytest.approx(-2.0) and recs[wr].bet_hits == 12
    assert recs[wr].n_eff == 20


def test_bets_of_another_selection_version_are_ignored(sqlite_db):
    settled = NOW - timedelta(days=3)
    for _ in range(40):
        _bet(sqlite_db, False, -110, settled, league="WNBA", sv="ev-v0")
        _bet(sqlite_db, False, -110, settled, league="WNBA", sv=None)
    sqlite_db.commit()
    assert ("WNBA", "player_prop", "points") not in load_records(sqlite_db, NOW)
    for _ in range(30):
        _bet(sqlite_db, False, -110, settled, league="WNBA")
    sqlite_db.commit()
    assert load_records(sqlite_db, NOW)[("WNBA", "player_prop", "points")].bet_n == 30


def test_bets_on_a_key_with_a_projection_record_are_not_double_counted(sqlite_db):
    _seed_points(sqlite_db, 100, 0.60)
    for _ in range(10):
        _bet(sqlite_db, False, -110, NOW - timedelta(days=3), stat="points")
    sqlite_db.commit()
    rec = load_records(sqlite_db, NOW)[POINTS]
    assert (rec.bet_n, rec.proj_n, rec.n_eff) == (0, 100, 100)


# ---------- prove-in ----------


def test_require_proven_record_defaults_true_and_false_turns_it_off(monkeypatch):
    assert rg.require_proven_record()
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    assert not rg.require_proven_record()
    # off: a non-prove-in key with no record is open, a prove-in key is not
    assert rg.drop_reason(None, POINTS) is None
    assert rg.drop_reason(None, ("MLB", "moneyline", None)) == "unproven_record"


def test_unproven_below_100_calls_or_below_breakeven():
    assert rg.drop_reason(None, POINTS) == "unproven_record"
    thin = combine(POINTS, proj_n=60, proj_hits=40, proj_units=20.0)
    assert rg.drop_reason(thin) == "unproven_record"  # 60 < 100
    flat = combine(POINTS, proj_n=100, proj_hits=50, proj_units=-1.0)
    assert rg.drop_reason(flat) == "unproven_record"  # shrunk ROI < 0, not losing
    ok = combine(POINTS, proj_n=100, proj_hits=60, proj_units=12.0, dates=10)
    assert rg.drop_reason(ok) is None
    # the same calls from too few slate dates (one night's rows are correlated)
    one_week = combine(POINTS, proj_n=100, proj_hits=60, proj_units=12.0, dates=9)
    assert rg.drop_reason(one_week) == "unproven_record"
    bad = combine(POINTS, proj_n=100, proj_hits=40, proj_units=-30.0)
    assert rg.drop_reason(bad) == "losing_record"  # losing is reported first


def test_nba_moneyline_mlb_wnba_withheld_unproven_with_no_record(sqlite_db):
    for key in (("NBA", "moneyline", None), ("MLB", "moneyline", None),
                ("MLB", "player_prop", "strikeouts"), ("WNBA", "spread", None),
                ("WNBA", "player_prop", "points")):  # fmt: skip
        assert rg.drop_reason(None, key) == "unproven_record", key
        assert rg.prove_in_required(key), key
    assert rg.withheld_keys(
        sqlite_db, NOW, {("NBA", "moneyline", None), ("MLB", "moneyline", None)}, ()
    ) == {
        ("NBA", "moneyline", None): "unproven_record",
        ("MLB", "moneyline", None): "unproven_record",
    }


def test_steals_blocks_pra_nhl_must_prove_in(monkeypatch):
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    for stat in ("steals", "blocks", "pra"):
        key = ("NBA", "player_prop", stat)
        assert rg.drop_reason(None, key) == "unproven_record"
        assert (
            rg.drop_reason(combine(key, proj_n=10, proj_hits=9, proj_units=5.0))
            == "unproven_record"
        )
    assert rg.drop_reason(None, ("NHL", "total", None)) == "unproven_record"
    assert rg.drop_reason(None, POINTS) is None


# ---------- loaders without a stored price ----------


def test_unpriced_loader_rows_count_only_as_unpriced_n(sqlite_db):
    from app.models.predictions_models import NBASpreadActuals, NBASpreadProjections
    from app.services.etl.nba.spread_projector import SPREAD_MODEL_VERSION

    day = NOW.date() - timedelta(days=2)
    for i in range(100):
        sqlite_db.add(
            NBASpreadProjections(
                game_date=day,
                home_team_name=f"H{i}",
                away_team_name=f"A{i}",
                projected_margin=8.0,
                home_win_prob=0.7,
                market_spread_home=-3.5,
                recommendation="NO_PLAY",
                model_version=SPREAD_MODEL_VERSION,
            )
        )
        margin = 10 if i < 40 else 1  # home covers -3.5 in 40 of 100
        sqlite_db.add(
            NBASpreadActuals(
                game_date=day,
                home_team_name=f"H{i}",
                away_team_name=f"A{i}",
                home_score=100 + margin,
                away_score=100,
                actual_margin=margin,
                home_won=True,
            )
        )
    sqlite_db.commit()
    rec = load_records(sqlite_db, NOW)[("NBA", "spread", None)]
    assert rec.unpriced_n == 100 and rec.proj_n == 0 and rec.n_eff == 0
    assert rec.proj_units == 0 and not rec.withheld
    assert rec.version == SPREAD_MODEL_VERSION


def test_nba_totals_record_counts_only_current_version(sqlite_db):
    from app.models.predictions_models import NBASpreadActuals, NBATotalsProjections
    from app.services.etl.nba.totals_projector import MODEL_VERSION

    day = NOW.date() - timedelta(days=2)
    for i in range(30):
        cur = i < 10
        sqlite_db.add(
            NBATotalsProjections(
                game_date=day,
                home_team_name=f"H{i}",
                away_team_name=f"A{i}",
                projected_total=230.0,
                market_total=225.0,
                recommendation="NO_PLAY",
                model_version=MODEL_VERSION if cur else None,
            )
        )
        sqlite_db.add(
            NBASpreadActuals(
                game_date=day,
                home_team_name=f"H{i}",
                away_team_name=f"A{i}",
                home_score=120,
                away_score=110 if cur else 90,
                actual_margin=10 if cur else 30,
                home_won=True,
            )
        )
    sqlite_db.commit()
    assert load_records(sqlite_db, NOW)[("NBA", "total", None)].unpriced_n == 10


# ---------- reporting and wiring ----------


def test_all_key_rows_lists_every_emitted_key_with_state(
    sqlite_db, monkeypatch, capsys
):
    from app.services.auto_pick import __main__ as cli

    _fake_rows(monkeypatch, "points_ou", [_row(i, i < 100) for i in range(200)])
    bets_before = sqlite_db.query(YetAIBet).count()
    rows = rg.all_key_rows(sqlite_db, NOW)
    assert rows == sorted(rows, key=lambda r: r["key"])
    by_key = {r["key"]: r for r in rows}
    emitted = {rg.key_label(k) for ks in rg.emitted_keys().values() for k in ks}
    assert emitted <= set(by_key)
    fields = {"key", "n", "hits", "units", "n_eff", "shrunk_roi", "version",
              "selection_version", "unpriced_n", "bet_n", "dates", "state", "reason"}  # fmt: skip
    assert all(set(r) == fields for r in rows)
    assert {r["state"] for r in rows} <= {
        "open",
        "withheld-losing",
        "withheld-unproven",
    }
    pts = by_key["NBA/player_prop/points"]
    assert (pts["n"], pts["hits"], pts["units"], pts["version"]) == (
        200,
        100,
        -20.0,
        "v1",
    )
    assert (pts["state"], pts["reason"]) == ("withheld-losing", "losing_record")
    assert pts["selection_version"] == ev.SELECTION_VERSION
    assert by_key["NBA/moneyline"]["state"] == "withheld-unproven"
    assert rg.gate_report is rg.all_key_rows
    cli.print_gate_report(rows)
    out = capsys.readouterr().out
    assert "NBA/player_prop/points" in out and "withheld-losing" in out
    assert "unpriced" in out and "selection" in out
    assert sqlite_db.query(YetAIBet).count() == bets_before


@pytest.mark.asyncio
async def test_losing_points_key_is_withheld_in_the_orchestrator(sqlite_db):
    _seed_points(sqlite_db, 150, 0.40)  # priced, losing
    _seed_rebounds(sqlite_db, 150, 0.70)  # priced, winning
    result = await _run(sqlite_db, [_prop(1, "points")])
    assert not [b for b in _bets(sqlite_db)]
    w = result.dropped_reasons["withheld_keys"]["NBA/player_prop/points"]
    assert w["reason"] == "losing_record" and w["proj_n"] == 150


def test_record_key_for_game_market_has_no_stat():
    c = BetCandidate(
        market_type=MarketType.TOTAL,
        league="NBA",
        event_id="e",
        selection="s",
        market_line=200.5,
        market_odds=-110,
        our_projection=210.0,
        projection_metadata={"stat": "ignored"},
    )
    assert record_key(c) == ("NBA", "total", None)


def test_historical_sub_score_uses_key_record_else_old_hit_rate():
    from app.services.auto_pick.scoring_context import ScoringContext, ScoringWeights
    from app.services.auto_pick.sub_scores import historical_sub_score

    c = _prop(1, "points")
    ctx = ScoringContext(
        weights=ScoringWeights(),
        score_threshold=65.0,
        historical_hit_rates={("player_prop", "NBA"): 0.65},
        records={POINTS: combine(POINTS, proj_n=400, proj_hits=192, proj_units=-30.0)},
    )
    assert historical_sub_score(c, ctx) < 50  # losing key, not the 100 of the old rate
    ctx.records = {POINTS: combine(POINTS, proj_n=10, proj_hits=1, proj_units=-8.0)}
    assert historical_sub_score(c, ctx) == 100.0  # thin: fall back


def test_no_data_means_no_record_and_every_key_open_with_prove_in_off(
    sqlite_db, monkeypatch
):
    monkeypatch.setenv("AUTO_PICK_REQUIRE_PROVEN_RECORD", "false")
    recs = load_records(sqlite_db, NOW)
    assert all(r.n_eff == 0 and not r.withheld for r in recs.values())
    assert not combine(POINTS).withheld


def test_every_registered_source_declares_its_keys():
    from app.tasks.auto_pick import _build_providers

    declared = rg.emitted_keys()
    names = {type(p.source).__name__ for p in _build_providers(None)}
    assert names <= set(declared), names - set(declared)


def test_threes_shadow_rows_read_the_threes_projection_field(sqlite_db, monkeypatch):
    # The threes table's projection column is projected_three_pt_made, not projected_threes.
    rows = [
        {
            "id": i,
            "date": NOW.date() - timedelta(days=1),
            "model_version": "v1",
            "projected_three_pt_made": 5.0,
            "fanduel_over_under": "o",
            "best_line": 2.5,
            "best_price": PRICE,
            "best_fair_prob": FAIR,
            "actual_three_pt_made": 4.0 if i < 20 else 1.0,
        }
        for i in range(40)
    ]
    _fake_rows(monkeypatch, "three_pt_ou", rows)
    rec = load_records(sqlite_db, NOW, ("nba_props",))[("NBA", "player_prop", "threes")]
    assert (rec.proj_n, rec.proj_hits) == (40, 20)


def test_shadow_record_counts_slate_dates_and_skips_out_of_bounds_prices(
    sqlite_db, monkeypatch
):
    rows = [_row(i, i % 2 == 0, day=1 + i % 3) for i in range(30)]
    rows += [_row(100 + i, True, price=+450) for i in range(5)]  # odds_max is +400
    _fake_rows(monkeypatch, "points_ou", rows)
    rec = load_records(sqlite_db, NOW, ("nba_props",))[POINTS]
    assert rec.proj_n == 30 and rec.dates == 3


def test_one_stray_row_does_not_switch_the_current_version():
    rows = [_row(i, True, version="v2") for i in range(5)]
    rows.append(_row(99, True, version="backfill"))  # newest id, same date
    version, kept = rg.current_version_rows(rows, "date")
    assert version == "v2" and len(kept) == 5


def test_shadow_skips_rows_with_no_edge_at_the_shopped_line(sqlite_db, monkeypatch):
    # FanDuel side over (projection 21 vs 20.5), but the best line shopped to 21.5: the
    # selector drops it as non_positive_edge, so the record must too.
    rows = [_row(i, True, projected_points=21.0, best_line=21.5) for i in range(5)]
    rows += [_row(10 + i, True) for i in range(3)]
    _fake_rows(monkeypatch, "points_ou", rows)
    assert load_records(sqlite_db, NOW, ("nba_props",))[POINTS].proj_n == 3
