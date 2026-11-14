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


def _seed_points(db, n, hit_rate, *, offset=1, first_id=0):
    """n graded NBA points O/U calls (line 20.5, over); ``offset`` days before NOW."""
    _seed(db, PointsProjections, PointsActuals, "points", n, hit_rate, offset, first_id)


def _seed_rebounds(db, n, hit_rate):
    _seed(db, ReboundsProjections, ReboundsActuals, "rebounds", n, hit_rate, 1, 0)


def _seed(db, proj, act, stat, n, hit_rate, offset, first_id):
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


@pytest.mark.asyncio
async def test_losing_key_is_withheld_and_winning_key_still_picked(sqlite_db):
    _seed_points(sqlite_db, 400, 0.48)
    _seed_rebounds(sqlite_db, 400, 0.58)

    result = await _run(sqlite_db, [_prop(1, "points"), _prop(2, "rebounds")])

    (bet,) = _bets(sqlite_db)
    assert bet.prediction_factors["grading"]["stat"] == "rebounds"
    d = result.dropped_reasons
    assert d["counts"]["losing_record"] == 1
    assert list(d["withheld_keys"]) == ["NBA/player_prop/points"]
    w = d["withheld_keys"]["NBA/player_prop/points"]
    assert w["proj_n"] == 400 and w["proj_hits"] == 192 and w["bet_n"] == 0
    assert w["shrunk_roi"] < 0 and w["n_eff"] == 60


def test_thin_sample_is_not_withheld():
    rec = combine(POINTS, proj_n=20, proj_hits=6)  # 30% but n_eff 20 < 30
    assert rec.shrunk_roi < 0 and not rec.withheld


def test_withheld_is_strict_and_needs_n_eff():
    assert combine(POINTS, proj_n=60, proj_hits=26).withheld
    assert not combine(POINTS, proj_n=60, proj_hits=40).withheld


def test_prior_is_capped_and_shrunk():
    rec = combine(POINTS, proj_n=400, proj_hits=192, bet_n=5, bet_units=-5.0)
    scale = 60 / 400
    proj_units = 192 * (100 / 110) - 208
    shrink_units = 20 * (0.5 * 100 / 110 - 0.5)
    assert rec.n_eff == pytest.approx(400 * scale + 5)
    assert rec.shrunk_roi == pytest.approx(
        (proj_units * scale - 5.0 + shrink_units) / (400 * scale + 5 + 20)
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
