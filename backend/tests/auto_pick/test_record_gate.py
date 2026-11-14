"""Record gate: (league, market, stat) keys with a losing shrunk record are withheld."""

from datetime import timedelta

import itertools

import pytest

from app.models.database_models import BetSource, BetType, YetAIBet
from app.models.predictions_models import (
    PointsActuals,
    PointsProjections,
    ReboundsActuals,
    ReboundsProjections,
)
from app.services.auto_pick import record_gate as rg
from app.services.auto_pick.candidate import BetCandidate, MarketType
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.record_gate import combine, load_records, record_key
from tests.auto_pick.test_orchestrator import NOW, _bets, _cand, _provider

POINTS = ("NBA", "player_prop", "points")
REBOUNDS = ("NBA", "player_prop", "rebounds")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (
        "AUTO_PICK_RECORD_GATE_ENABLED",
        "AUTO_PICK_RECORD_MIN_PICKS",
        "AUTO_PICK_RECORD_WINDOW_DAYS",
        "AUTO_PICK_RECORD_MIN_ROI",
        "AUTO_PICK_RECORD_PRIOR_MAX_PICKS",
        "AUTO_PICK_RECORD_SHRINK_PICKS",
        "AUTO_YETAI_PICKS_AUTO_PUBLISH",
        "AUTO_YETAI_PICKS_MIN_SCORE",
    ):
        monkeypatch.delenv(k, raising=False)
    from app.services.auto_pick import orchestrator as orch_mod

    monkeypatch.setattr(orch_mod, "_can_grade", lambda league, market, stat: True)


def _seed_points(db, n, hit_rate, *, offset=1, first_id=0, edge=9.5):
    """n graded NBA points O/U calls (line 20.5, over); ``offset`` days before NOW."""
    _seed(
        db, PointsProjections, PointsActuals, "points", n, hit_rate, offset, first_id,
        edge,
    )  # fmt: skip


def _seed_rebounds(db, n, hit_rate, *, first_id=0, edge=9.5):
    _seed(
        db, ReboundsProjections, ReboundsActuals, "rebounds", n, hit_rate, 1, first_id,
        edge,
    )  # fmt: skip


def _seed(db, proj, act, stat, n, hit_rate, offset, first_id, edge=9.5):
    """``edge`` = projected - line on the over call; ``hit_rate`` is the share of overs."""
    day = NOW.date() - timedelta(days=offset)
    hits = round(n * hit_rate)
    projected = 20.5 + edge
    for i in range(first_id, first_id + n):
        extra = {"player_name": f"P{i}"}
        if stat == "rebounds":
            extra["opponent_team_name"] = "X"
        db.add(
            proj(
                date=day,
                player_id=i,
                **{f"projected_{stat}": projected},
                fanduel_line=20.5,
                fanduel_over_under="over",
                **extra,
            )
        )
        db.add(
            act(
                date=day,
                player_id=i,
                **{f"actual_{stat}": 25.0 if i - first_id < hits else 10.0},
                **{f"projected_{stat}": projected},
                **extra,
            )
        )
    db.commit()


_ids = itertools.count()


def _bet(db, won, odds, settled, league="NBA", stat="points"):
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
                "grading": {"league": league, "market": "player_prop", "stat": stat}
            },
        )
    )


def _prop(n, stat):
    c = _cand(n, league="NBA", selection=f"Player {n} OVER 5.5 {stat}")
    c.projection_metadata["stat"] = stat
    return c


async def _run(db, cands):
    return await AutoPickOrchestrator(
        db=db, providers=[_provider(cands)], now=NOW
    ).run()


# Prod scorecard shapes (NBA, prior window). Rebounds' qualifying edge is
# player_prop_projection_display.EDGE_THRESHOLDS["rebounds"] (0.5): ``edge=1.0`` qualifies,
# ``edge=0.2`` does not.


@pytest.mark.asyncio
async def test_points_losing_at_every_edge_is_withheld_rebounds_in_subset_open(
    sqlite_db,
):
    # points: 47.6% over at low and high edge alike -> no subset rescues it
    _seed_points(sqlite_db, 250, 0.476, edge=0.2)
    _seed_points(sqlite_db, 250, 0.476, edge=2.0, first_id=1000)
    # rebounds: 51.8% over all calls, 57.8% in the qualifying subset
    _seed_rebounds(sqlite_db, 275, 0.469, edge=0.2, first_id=0)
    _seed_rebounds(sqlite_db, 225, 0.578, edge=1.0, first_id=1000)

    result = await _run(sqlite_db, [_prop(1, "points"), _prop(2, "rebounds")])

    (bet,) = _bets(sqlite_db)
    assert bet.prediction_factors["grading"]["stat"] == "rebounds"
    d = result.dropped_reasons
    assert d["counts"]["losing_record"] == 1
    assert list(d["withheld_keys"]) == ["NBA/player_prop/points"]
    w = d["withheld_keys"]["NBA/player_prop/points"]
    assert w["proj_n"] == 250 and w["bet_n"] == 0 and w["shrunk_roi"] < 0
    reb = load_records(sqlite_db, NOW)[REBOUNDS]
    assert (reb.proj_n, reb.proj_hits) == (225, 130) and not reb.withheld
    assert reb.shrunk_roi > 0


def test_rebounds_overall_record_would_withhold_but_subset_is_what_counts(sqlite_db):
    _seed_rebounds(sqlite_db, 400, 0.50, edge=0.2)
    _seed_rebounds(sqlite_db, 100, 0.578, edge=1.0, first_id=1000)
    rec = load_records(sqlite_db, NOW)[REBOUNDS]
    assert rec.proj_n == 100 and not rec.withheld  # low-edge rows are not graded


def test_key_at_exact_breakeven_is_open():
    # 110/210 = 52.38% over at -110 is zero ROI.
    rec = combine(POINTS, proj_n=210, proj_hits=110)
    assert rec.shrunk_roi == 0 and not rec.withheld
    assert combine(POINTS, proj_n=210, proj_hits=109).withheld


def test_no_data_means_no_record_and_open_gate(sqlite_db):
    recs = load_records(sqlite_db, NOW)
    assert all(r.n_eff == 0 and not r.withheld for r in recs.values())
    assert not combine(POINTS).withheld


def test_thin_sample_is_not_withheld():
    rec = combine(POINTS, proj_n=20, proj_hits=6)  # 30% but n_eff 20 < 30
    assert rec.shrunk_roi < 0 and not rec.withheld


def test_withheld_is_strict_and_needs_n_eff():
    assert combine(POINTS, proj_n=60, proj_hits=26).withheld
    assert not combine(POINTS, proj_n=60, proj_hits=40).withheld


def test_prior_is_capped_and_shrunk_toward_breakeven():
    rec = combine(POINTS, proj_n=400, proj_hits=192, bet_n=5, bet_units=-5.0)
    scale = 60 / 400
    proj_units = 192 * (100 / 110) - 208
    assert rec.n_eff == pytest.approx(400 * scale + 5)
    # the shrink pseudo-picks carry zero ROI (breakeven), not a 50% hit rate at -110
    assert rec.shrunk_roi == pytest.approx(
        (proj_units * scale - 5.0) / (400 * scale + 5 + 20)
    )


def test_recovery_when_projection_record_turns_winning(sqlite_db):
    _seed_points(sqlite_db, 400, 0.48)
    assert load_records(sqlite_db, NOW)[POINTS].withheld
    # A later run: the key kept being graded and now wins.
    _seed_points(sqlite_db, 400, 0.70, offset=2, first_id=1000)
    assert not load_records(sqlite_db, NOW)[POINTS].withheld


def test_bet_units_use_stored_odds(sqlite_db):
    settled = NOW - timedelta(days=3)
    for _ in range(10):
        _bet(sqlite_db, True, 150, settled, stat="points")
        _bet(sqlite_db, False, 150, settled, stat="points")
    for i in range(12):
        _bet(sqlite_db, True, -200, settled, stat="rebounds")
    for i in range(8):
        _bet(sqlite_db, False, -200, settled, stat="rebounds")
    sqlite_db.commit()
    recs = load_records(sqlite_db, NOW)
    assert recs[POINTS].bet_units == pytest.approx(5.0) and recs[POINTS].shrunk_roi > 0
    assert recs[REBOUNDS].bet_units == pytest.approx(-2.0)
    assert recs[REBOUNDS].shrunk_roi < 0


def test_kill_switch_and_env_overrides(monkeypatch):
    losing = dict(proj_n=400, proj_hits=192)
    assert combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_GATE_ENABLED", "false")
    assert not combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_GATE_ENABLED", "true")
    monkeypatch.setenv("AUTO_PICK_RECORD_MIN_PICKS", "100")
    assert not combine(POINTS, **losing).withheld  # n_eff 60 < 100
    monkeypatch.setenv("AUTO_PICK_RECORD_MIN_PICKS", "abc")
    assert rg.min_picks() == 30 and combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_MIN_ROI", "-0.5")
    assert not combine(POINTS, **losing).withheld
    monkeypatch.setenv("AUTO_PICK_RECORD_WINDOW_DAYS", "7")
    assert rg.window_days() == 7


def test_no_leak_of_today_or_future_results(sqlite_db):
    _seed_points(sqlite_db, 50, 0.0, offset=0)  # today's slate: ignored
    settled_later = NOW + timedelta(hours=1)
    for _ in range(40):
        _bet(sqlite_db, False, -110, settled_later)
    sqlite_db.commit()
    rec = load_records(sqlite_db, NOW)[POINTS]
    assert (rec.proj_n, rec.bet_n) == (0, 0)
    _seed_points(sqlite_db, 50, 0.0, offset=1, first_id=500)  # yesterday: counted
    assert load_records(sqlite_db, NOW)[POINTS].proj_n == 50


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
        records={POINTS: combine(POINTS, proj_n=400, proj_hits=192)},
    )
    assert historical_sub_score(c, ctx) < 40  # losing key, not the 100 of the old rate
    ctx.records = {POINTS: combine(POINTS, proj_n=10, proj_hits=1)}  # thin: fall back
    assert historical_sub_score(c, ctx) == 100.0


def test_nba_spread_projection_record_feeds_the_gate(sqlite_db):
    from app.models.predictions_models import NBASpreadActuals, NBASpreadProjections

    day = NOW.date() - timedelta(days=2)
    for i in range(100):
        home, away = f"H{i}", f"A{i}"
        sqlite_db.add(
            NBASpreadProjections(
                game_date=day,
                home_team_name=home,
                away_team_name=away,
                projected_margin=8.0,
                home_win_prob=0.7,
                market_spread_home=-3.5,
                recommendation="HOME",
            )
        )
        margin = 10 if i < 40 else 1  # home covers -3.5 in 40 of 100
        sqlite_db.add(
            NBASpreadActuals(
                game_date=day,
                home_team_name=home,
                away_team_name=away,
                home_score=100 + margin,
                away_score=100,
                actual_margin=margin,
                home_won=True,
            )
        )
    sqlite_db.commit()

    rec = load_records(sqlite_db, NOW)[("NBA", "spread", None)]
    assert (rec.proj_hits, rec.proj_n) == (40, 100)
    assert rec.withheld


def test_gate_report_prints_each_key_and_writes_nothing(sqlite_db, capsys):
    from app.models.database_models import YetAIBet
    from app.services.auto_pick import __main__ as cli

    _seed_points(sqlite_db, 250, 0.476, edge=2.0)
    _seed_rebounds(sqlite_db, 225, 0.578, edge=1.0)
    for _ in range(3):
        _bet(sqlite_db, True, -110, NOW - timedelta(days=3), stat="rebounds")
    sqlite_db.commit()
    bets_before = sqlite_db.query(YetAIBet).count()

    rows = rg.gate_report(sqlite_db, NOW)
    by_key = {r["key"]: r for r in rows}
    pts, reb = by_key["NBA/player_prop/points"], by_key["NBA/player_prop/rebounds"]
    assert (pts["proj_n"], pts["proj_hits"], pts["withheld"]) == (250, 119, True)
    assert (reb["bet_n"], reb["proj_n"], reb["proj_hits"]) == (3, 225, 130)
    assert reb["withheld"] is False and reb["shrunk_roi"] > 0
    assert reb["prior_hit_rate"] == pytest.approx(130 / 225)

    cli.print_gate_report(rows)
    out = capsys.readouterr().out
    assert "NBA/player_prop/points" in out and "WITHHELD" in out
    assert sqlite_db.query(YetAIBet).count() == bets_before
