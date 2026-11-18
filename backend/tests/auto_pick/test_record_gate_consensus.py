"""Record gate: priced shadow records of the consensus-price keys (game lines, NFL / NHL props).

Rows of the current model version go through the selector's own row functions, providers
and clock-free gates, and are graded at best_line / best_price with the one grading rule.
"""

from datetime import date, datetime, timedelta

import pytest

from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    NBASpreadProjections,
    NBATotalsProjections,
    NFLGameLines,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTotalsActuals,
    NFLTotalsProjections,
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
    QBActuals,
    QBPredictions,
    RecvYdsActuals,
    RecvYdsPredictions,
)
from app.services.auto_pick import ev
from app.services.auto_pick import orchestrator as orch_mod
from app.services.auto_pick import record_gate as rg
from app.services.auto_pick.candidate import latest_refresh_start, slate_window_for_date
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.sources.nba_spread_source import NBASpreadSource
from app.services.yetai_grading import game_result
from tests.auto_pick.test_orchestrator import NOW

NBA_SPREAD = ("NBA", "spread", None)
FACTORS = {"anchor": {"k": 0.1}, "model_margin": 8.0}
WIN_AT_110 = 100 / 110


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
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(orch_mod, "_can_grade", lambda league, market, stat: True)


def best(side, line, price=-110, fair=0.55, prefix="best_"):
    out = {
        f"{prefix}book": "fanduel",
        f"{prefix}price": price,
        f"{prefix}side": side,
        f"{prefix}fair_prob": fair,
        f"{prefix}ev": 0.05,
        f"{prefix}quoted_at": NOW - timedelta(hours=1),
    }
    if line is not None:
        out[f"{prefix}line"] = line
    return out


def _past(days):
    return NOW.date() - timedelta(days=days)


# ---------- grading: one definition ----------


@pytest.mark.parametrize(
    "market,side,line,hs,aws,want",
    [
        ("spread", "home", -3.5, 110, 100, "won"),
        ("spread", "home", -3.5, 102, 100, "lost"),
        ("spread", "away", 3.5, 102, 100, "won"),
        ("spread", "home", -4.0, 104, 100, "pushed"),  # pushes on the number
        ("total", "over", 225.0, 120, 105, "pushed"),
        ("total", "under", 225.5, 120, 105, "won"),
        ("moneyline", "home", 0.0, 100, 99, "won"),
        ("moneyline", "away", 0.0, 100, 99, "lost"),
        ("moneyline", "home", 0.0, 3, 3, "pushed"),  # a tie is a push
    ],
)
def test_game_result(market, side, line, hs, aws, want):
    assert game_result(market, side, line, hs, aws) == want


def test_soccer_moneyline_tie_is_a_loss():
    assert game_result("moneyline", "home", 0.0, 1, 1, soccer=True) == "lost"


# ---------- NBA spread: seeding ----------


def _nba_game(db, i, day, *, margin, line=-3.5, proj=8.0, quote=None, created=None):
    """One NBA spread row (home side by the projection) with its game line and result.
    ``quote`` is the best_* dict (None = no best quote); ``margin`` the final home margin.
    """
    home, away = f"H{i}", f"A{i}"
    db.add(
        NBAGameLines(
            game_date=day,
            home_team_name=home,
            away_team_name=away,
            odds_api_event_id=f"e{i}",
            game_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=23),
            spread_home=line,
            spread_away=-line,
            spread_home_odds=-110,
            spread_away_odds=-110,
        )
    )
    db.add(
        NBASpreadProjections(
            game_date=day,
            home_team_name=home,
            away_team_name=away,
            projected_margin=proj,
            home_win_prob=0.7,
            market_spread_home=line,
            recommendation="NO_PLAY",
            factors=FACTORS,
            model_version="v1",
            created_at=created or datetime.combine(day, datetime.min.time()),
            **(quote if quote is not None else {}),
        )
    )
    if margin is not None:
        db.add(
            NBASpreadActuals(
                game_date=day,
                home_team_name=home,
                away_team_name=away,
                home_score=100 + margin,
                away_score=100,
                actual_margin=margin,
                home_won=margin > 0,
            )
        )


def _seed_spreads(db, n, dates, hit_share=0.6, first=0):
    """n priced home -3.5 calls at -110 (fair 0.55) spread over ``dates`` past days."""
    hits = round(n * hit_share)
    for k in range(n):
        _nba_game(
            db,
            first + k,
            _past(1 + k % dates),
            margin=10 if k < hits else 1,
            quote=best("home", -3.5),
        )
    db.commit()


def _spread_rec(db):
    return rg.load_records(db, NOW, ("nba_games",))[NBA_SPREAD]


# ---------- the gate on priced spread calls ----------


def test_a_proven_priced_record_opens_the_spread_key(sqlite_db):
    _seed_spreads(sqlite_db, 100, 10)
    rec = _spread_rec(sqlite_db)
    assert (rec.proj_n, rec.proj_hits, rec.dates, rec.version) == (100, 60, 10, "v1")
    assert rec.proj_units == pytest.approx(60 * WIN_AT_110 - 40)
    assert rg.drop_reason(rec) is None


def test_99_calls_or_9_dates_stay_unproven(sqlite_db):
    _seed_spreads(sqlite_db, 99, 10)
    assert rg.drop_reason(_spread_rec(sqlite_db)) == "unproven_record"


def test_9_dates_stay_unproven(sqlite_db):
    _seed_spreads(sqlite_db, 100, 9)
    assert rg.drop_reason(_spread_rec(sqlite_db)) == "unproven_record"


def test_gates_unpriced_pushes_and_the_best_line(sqlite_db):
    d = _past(1)
    good = best("home", -3.5)
    # 0 passes the gates and wins (margin 10)
    _nba_game(sqlite_db, 0, d, margin=10, quote=good)
    # 1 odds out of bounds (default bounds -300..400)
    _nba_game(sqlite_db, 1, d, margin=10, quote=best("home", -3.5, price=-500))
    # 2 no edge: the projection is on the other side of the stored line
    _nba_game(sqlite_db, 2, d, margin=10, proj=1.0, quote=good)
    # 3 negative consensus EV (fair 0.45 at -110)
    _nba_game(sqlite_db, 3, d, margin=10, quote=best("home", -3.5, fair=0.45))
    # 4 no best quote, would-be side home: unpriced, graded (a loss), never valued
    _nba_game(sqlite_db, 4, d, margin=1, quote=None)
    # 5 a push at the best line (-4 and margin 4): counts for nothing
    _nba_game(sqlite_db, 5, d, margin=4, quote=best("home", -4.0))
    # 6 graded at the best line, not the stored one: -2.5 covers a 3 point win
    _nba_game(sqlite_db, 6, d, margin=3, quote=best("home", -2.5, price=120))
    # 7 no actual yet: not graded anywhere
    _nba_game(sqlite_db, 7, d, margin=None, quote=good)
    sqlite_db.commit()
    rec = _spread_rec(sqlite_db)
    assert (rec.proj_n, rec.proj_hits, rec.unpriced_n) == (2, 2, 1)
    assert rec.proj_units == pytest.approx(WIN_AT_110 + 1.2)  # +120 pays 1.2u
    assert rec.dates == 1


def test_only_the_current_version_counts(sqlite_db):
    _seed_spreads(sqlite_db, 30, 10)
    # a stray older-version row on an older date: the current version is the latest date's
    _nba_game(sqlite_db, 900, _past(20), margin=10, quote=best("home", -3.5))
    sqlite_db.query(NBASpreadProjections).filter_by(home_team_name="H900").update(
        {"model_version": "v0"}
    )
    sqlite_db.commit()
    assert _spread_rec(sqlite_db).proj_n == 30


def test_todays_results_do_not_leak_in(sqlite_db):
    _seed_spreads(sqlite_db, 10, 10)
    _nba_game(sqlite_db, 901, NOW.date(), margin=10, quote=best("home", -3.5))
    sqlite_db.commit()
    assert _spread_rec(sqlite_db).proj_n == 10


# ---------- every new key has a priced record from its own tables ----------

DAY = _past(1)


def _nba_total_and_ml(db):
    _nba_game(db, 50, DAY, margin=10, quote=best("home", -3.5, **{}))
    sqlite_row = (
        db.query(NBASpreadProjections).filter_by(home_team_name="H50").one()
    )  # the moneyline quote lives on the spread row
    for k, v in best("home", None, price=-150, fair=0.62, prefix="ml_best_").items():
        setattr(sqlite_row, k, v)
    gl = db.query(NBAGameLines).filter_by(home_team_name="H50").one()
    gl.total, gl.over_odds, gl.under_odds = 220.5, -110, -110
    db.add(
        NBATotalsProjections(
            game_date=DAY,
            home_team_name="H50",
            away_team_name="A50",
            projected_total=230.0,
            market_total=220.5,
            recommendation="NO_PLAY",
            model_version="v1",
            created_at=datetime.combine(DAY, datetime.min.time()),
            **best("over", 220.5),
        )
    )
    db.commit()


def test_nba_moneyline_and_total_are_priced_from_the_same_scores(sqlite_db):
    _nba_total_and_ml(sqlite_db)  # final 110-100: total 210 < 220.5
    recs = rg.load_records(sqlite_db, NOW, ("nba_games",))
    ml = recs[("NBA", "moneyline", None)]
    assert (ml.proj_n, ml.proj_hits) == (1, 1)
    assert ml.proj_units == pytest.approx(100 / 150)  # at ml_best_price, side home
    total = recs[("NBA", "total", None)]
    assert (total.proj_n, total.proj_hits) == (1, 0)  # over lost at 210
    assert total.proj_units == pytest.approx(-1.0)


def _nfl_game(db, day):
    kw = dict(game_date=day, home_team_name="KC", away_team_name="BUF")
    db.add(
        NFLGameLines(
            odds_api_event_id="n1",
            game_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=18),
            spread_home=-2.5,
            spread_home_odds=-110,
            spread_away_odds=-110,
            total=47.5,
            over_odds=-110,
            under_odds=-110,
            moneyline_home=-150,
            moneyline_away=130,
            **kw,
        )
    )
    spread = NFLSpreadProjections(
        projected_margin=8.0,
        home_win_prob=0.7,
        market_spread_home=-2.5,
        recommendation="NO_PLAY",
        factors=FACTORS,
        model_version="n1",
        created_at=datetime.combine(day, datetime.min.time()),
        **kw,
        **best("home", -2.5),
        **best("home", None, price=-150, fair=0.62, prefix="ml_best_"),
    )
    db.add(spread)
    db.add(
        NFLTotalsProjections(
            projected_total=55.0,
            market_total=47.5,
            recommendation="NO_PLAY",
            model_version="n1",
            created_at=datetime.combine(day, datetime.min.time()),
            **kw,
            **best("over", 47.5),
        )
    )
    db.add(
        NFLSpreadActuals(
            home_score=30, away_score=20, actual_margin=10, home_won=True, **kw
        )
    )
    db.add(NFLTotalsActuals(actual_total=50, **kw))
    for pid, proj, line, side in (("q1", 285.0, 271.5, "over"),):
        db.add(
            QBPredictions(
                qb_player_id=pid,
                qb_player_name="QB",
                team_id=1,
                venue_name="V",
                team_name="KC",
                opponent_team_name="BUF",
                game_date=datetime.combine(day, datetime.min.time())
                + timedelta(hours=13),
                season=2026,
                week=10,
                predicted_passing_yards=proj,
                ou_line=line,
                over_odds=-110,
                under_odds=-110,
                model_version="n1",
                prediction_date=datetime.combine(day, datetime.min.time()),
                **best(side, line),
            )
        )
        db.add(
            QBActuals(
                qb_player_id=pid,
                qb_player_name="QB",
                team_name="KC",
                opponent_team_name="BUF",
                game_date=datetime.combine(day, datetime.min.time())
                + timedelta(hours=13),
                season=2026,
                week=10,
                actual_passing_yards=300.0,
                predicted_passing_yards=285.0,
            )
        )
    db.add(
        RecvYdsPredictions(
            season=2026,
            week=10,
            game_date=day,
            player_id="r1",
            player_name="WR",
            position="WR",
            team_name="KC",
            opponent_team_name="BUF",
            predicted_receiving_yards=80.0,
            ou_line=61.5,
            over_odds=-110,
            under_odds=-110,
            model_version="n1",
            **best("over", 61.5),
        )
    )
    db.add(
        RecvYdsActuals(
            season=2026,
            week=10,
            game_date=day,
            player_id="r1",
            player_name="WR",
            position="WR",
            team_name="KC",
            opponent_team_name="BUF",
            actual_receiving_yards=50.0,
        )
    )
    db.commit()


def test_nfl_keys_are_priced_and_graded_from_their_own_actuals(sqlite_db):
    _nfl_game(sqlite_db, DAY)
    recs = rg.load_records(sqlite_db, NOW, ("nfl",))
    got = {
        k[1] + ("/" + k[2] if k[2] else ""): (r.proj_n, r.proj_hits, r.dates)
        for k, r in recs.items()
        if k[0] == "NFL"
    }
    assert got == {
        "spread": (1, 1, 1),  # KC -2.5, won by 10
        "moneyline": (1, 1, 1),
        "total": (1, 1, 1),  # over 47.5, final 50
        "player_prop/passing_yards": (1, 1, 1),  # over 271.5, 300
        "player_prop/receiving_yards": (1, 0, 1),  # over 61.5, 50
    }
    assert recs[("NFL", "moneyline", None)].proj_units == pytest.approx(100 / 150)


def _nhl_game(db, day):
    db.add(
        NHLGoaliePredictions(
            game_date=day,
            goalie_id=1,
            goalie_name="G",
            team_id=6,
            team_name="Boston",
            opponent_team_id=10,
            opponent_team_name="Toronto",
            is_home=True,
            game_time=datetime.combine(day, datetime.min.time()) + timedelta(hours=19),
            starter_confirmed=True,
            was_scratch=False,
            predicted_saves=30.0,
            predicted_shots_against=32.0,
            predicted_save_pct=0.92,
            saves_line=27.5,
            over_odds=-110,
            under_odds=-110,
            model_version="heuristic-v2",
            prediction_date=datetime.combine(day, datetime.min.time()),
            **best("over", 27.5),
        )
    )
    db.add(
        NHLGoalieActuals(
            game_id=2026020001,
            game_date=day,
            goalie_id=1,
            goalie_name="G",
            team_name="Boston",
            opponent_team_name="Toronto",
            actual_saves=25,
            actual_shots_against=27,
            actual_save_pct=0.9,
            actual_goals_against=2,
        )
    )
    db.add(
        NHLTeamTotalsPredictions(
            game_date=day,
            game_time_et=datetime.combine(day, datetime.min.time())
            + timedelta(hours=19),
            home_team_id=6,
            home_team_name="Boston",
            away_team_id=10,
            away_team_name="Toronto",
            predicted_home_goals=3.5,
            predicted_away_goals=3.0,
            predicted_total_goals=6.5,
            suggested_ou_line=6.5,
            draftkings_ou_line=5.5,
            over_odds=-110,
            under_odds=-110,
            model_version="heuristic-v2",
            prediction_date=datetime.combine(day, datetime.min.time()),
            **best("over", 5.5),
        )
    )
    db.add(
        NHLTeamTotalsActuals(
            game_id=2026020002,
            game_date=day,
            home_team_id=6,
            home_team_name="Boston",
            away_team_id=10,
            away_team_name="Toronto",
            actual_home_goals=4,
            actual_away_goals=3,
            actual_total_goals=7,
        )
    )
    db.commit()


def test_nhl_saves_and_total_are_priced_shadow_records(sqlite_db):
    _nhl_game(sqlite_db, DAY)
    recs = rg.load_records(sqlite_db, NOW, ("nhl",))
    saves = recs[("NHL", "player_prop", "saves")]
    assert (saves.proj_n, saves.proj_hits) == (1, 0)  # over 27.5, 25 saves
    total = recs[("NHL", "total", None)]
    assert (total.proj_n, total.proj_hits, total.dates) == (
        1,
        1,
        1,
    )  # over 5.5, 7 goals
    assert total.proj_units == pytest.approx(WIN_AT_110)
    assert ("NHL", "player_prop", "shots") in recs  # shots keep their unpriced loader


def test_pre_repair_nhl_rows_are_excluded(sqlite_db):
    _nhl_game(sqlite_db, DAY)
    sqlite_db.query(NHLTeamTotalsPredictions).update({"model_version": "heuristic-v1"})
    sqlite_db.commit()
    rec = rg.load_records(sqlite_db, NOW, ("nhl",))[("NHL", "total", None)]
    assert rec.proj_n == 0 and rec.unpriced_n == 0


# ---------- reporting ----------

NEW_KEYS = {
    "NBA/spread",
    "NBA/total",
    "NBA/moneyline",
    "NFL/spread",
    "NFL/total",
    "NFL/moneyline",
    "NFL/player_prop/passing_yards",
    "NFL/player_prop/receiving_yards",
    "NHL/player_prop/saves",
    "NHL/total",
}


def test_all_key_rows_lists_every_new_key_with_n_dates_unpriced(sqlite_db):
    _nfl_game(sqlite_db, DAY)
    _nhl_game(sqlite_db, DAY)
    _nba_total_and_ml(sqlite_db)
    _nba_game(sqlite_db, 60, DAY, margin=1, quote=None)  # unpriced display row
    sqlite_db.commit()
    rows = {r["key"]: r for r in rg.all_key_rows(sqlite_db, NOW)}
    assert NEW_KEYS <= set(rows)
    for k in NEW_KEYS:
        assert {"n", "dates", "unpriced_n"} <= set(rows[k])
    assert rows["NFL/spread"]["n"] == 1 and rows["NFL/spread"]["dates"] == 1
    assert rows["NBA/spread"]["unpriced_n"] == 1
    assert rows["NHL/total"]["state"] == "withheld-unproven"


# ---------- the selector end to end ----------


def _todays_spread(db, *, price, fair):
    """Today's NBA spread: fresh row and quote, home -3.5 projection +8."""
    day = NOW.date()
    ts = NOW - timedelta(hours=1)
    assert ts >= latest_refresh_start(NOW, "NBA")
    _nba_game(
        db,
        7000,
        day,
        margin=None,
        quote=best("home", -3.5, price=price, fair=fair) | {"best_quoted_at": ts},
        created=ts,
    )
    db.query(NBAGameLines).filter_by(home_team_name="H7000").update(
        {"game_time": NOW + timedelta(hours=5)}
    )
    db.commit()


async def _dry_run(db):
    return await AutoPickOrchestrator(
        db=db,
        providers=[SpreadCandidateProvider(source=NBASpreadSource(db))],
        now=NOW,
        dry_run=True,
    ).run()


@pytest.mark.asyncio
async def test_a_proven_record_lets_the_selector_pick_a_positive_ev_spread(sqlite_db):
    _seed_spreads(sqlite_db, 100, 10)
    _todays_spread(sqlite_db, price=-110, fair=0.55)
    result = await _dry_run(sqlite_db)
    (pick,) = result.picks
    assert (
        pick.candidate.selection.endswith("-3.5") and pick.candidate.market_odds == -110
    )
    assert pick.ev.consensus_ev > 0 and pick.ev.ev > ev.MIN_EV


@pytest.mark.asyncio
async def test_negative_consensus_ev_is_not_picked_even_with_a_proven_record(sqlite_db):
    _seed_spreads(sqlite_db, 100, 10)
    _todays_spread(sqlite_db, price=-110, fair=0.45)
    result = await _dry_run(sqlite_db)
    assert result.pick_count == 0
    assert result.dropped_reasons["counts"] == {"negative_consensus_ev": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("n,dates", [(99, 10), (100, 9)])
async def test_a_thin_record_is_unproven(sqlite_db, n, dates):
    _seed_spreads(sqlite_db, n, dates)
    _todays_spread(sqlite_db, price=-110, fair=0.55)
    result = await _dry_run(sqlite_db)
    assert result.pick_count == 0
    assert result.dropped_reasons["counts"] == {"unproven_record": 1}
