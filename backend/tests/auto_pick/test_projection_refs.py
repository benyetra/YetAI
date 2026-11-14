"""H-7 projection_ref / L5(d) model_version / B9 odds_assumed gate."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.models.database_models import YetAIBet
from app.models.predictions_models import (
    NBAGameLines,
    PointsProjections,
    WNBAPointsProjections,
)
from app.services.auto_pick import orchestrator as orch_mod
from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.sources.mlb_game_source import MLBGameMoneylineSource
from app.services.auto_pick.sources.mlb_hits_source import MLBHitsSource
from app.services.auto_pick.sources.mlb_strikeout_source import MLBStrikeoutSource
from app.services.auto_pick.sources.nba_moneyline_source import NBAMoneylineSource
from app.services.auto_pick.sources.nba_spread_source import NBASpreadSource
from app.services.auto_pick.sources.nba_totals_source import NBATotalsSource
from app.services.auto_pick.sources.nfl_qb_passing_source import NFLQBPassingSource
from app.services.auto_pick.sources.nfl_receiving_yards_source import (
    NFLReceivingYardsSource,
)
from app.services.auto_pick.sources.nfl_spread_source import NFLSpreadSource
from app.services.auto_pick.sources.nfl_totals_source import NFLTotalsSource
from app.services.auto_pick.sources.nhl_goalie_saves_source import NHLGoalieSavesSource
from app.services.auto_pick.sources.nhl_totals_source import NHLTotalsSource
from app.services.auto_pick.sources.player_prop_source import PlayerPropSource
from app.services.auto_pick.sources.wnba_player_prop_source import WNBAPlayerPropSource
from app.services.auto_pick.sources.wnba_spread_source import WNBASpreadSource
from app.services.auto_pick.sources.wnba_totals_source import WNBATotalsSource
from tests.auto_pick import test_orchestrator as orch_t
from tests.auto_pick import test_selector as sel_t
from tests.auto_pick import test_sources_mlb as mlb_t
from tests.auto_pick import test_sources_nba as nba_t
from tests.auto_pick import test_sources_nfl as nfl_t
from tests.auto_pick import test_sources_nhl as nhl_t
from tests.auto_pick import test_sources_wnba as wnba_t


def run(coro):
    return asyncio.run(coro)


# --- B9 ---------------------------------------------------------------------


def test_gate_drops_assumed_odds_only_when_flagged():
    now = sel_t.NOW
    ok = sel_t._sc("e", 70, commence_time=now + timedelta(hours=3))
    bad = sel_t._sc(
        "e", 70, commence_time=now + timedelta(hours=3), meta={"odds_assumed": True}
    )
    assert sel_t._gate(ok) is None
    assert sel_t._gate(bad) == "odds_assumed"


def test_mlb_strikeout_with_no_usable_price_is_gated(sqlite_db):
    mlb_t._proj(sqlite_db)
    mlb_t._pitcher(sqlite_db, fanduel_flag="u")  # price is for the other side
    mlb_t._game(sqlite_db)
    sqlite_db.commit()
    (c,) = run(
        PlayerPropCandidateProvider(MLBStrikeoutSource(sqlite_db)).get_candidates(
            mlb_t.DR
        )
    )
    assert c.market_odds == -110 and c.projection_metadata["odds_assumed"] is True
    c.commence_time = sel_t.NOW + timedelta(hours=3)
    sc = sel_t.ScoredCandidate(c, None)
    assert sel_t.hard_gate_reason(sc, sel_t.NOW, -300, 400) == "odds_assumed"


def test_mlb_hits_rows_are_marked_assumed():
    r = MagicMock()
    r.id, r.player_id, r.player_name, r.game_id = 5, "123", "A", 7
    r.game_time, r.combined_score, r.hits_last_10_games = datetime(2026, 6, 10), 3.5, 8
    r.team, r.opponent = "NYY", "BOS"
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [r]
    dr = DateRange(datetime(2026, 6, 10), datetime(2026, 6, 11), datetime(2026, 6, 10).date())
    (row,) = run(MLBHitsSource(db).get_todays_projections(dr))
    assert row["odds_assumed"] is True


# --- H-7 / L5(d): sources ---------------------------------------------------


def _ref(row, table, **keys):
    ref = row["projection_ref"]
    assert ref["table"] == table and ref["id"] is not None
    for k, v in keys.items():
        assert ref[k] == v, k
    return ref


def test_nba_sources(sqlite_db):
    nba_t._gl(sqlite_db)
    nba_t._spread(sqlite_db)
    nba_t._total(sqlite_db)
    sqlite_db.add(
        PointsProjections(
            date=nba_t.DAY,
            player_id=1,
            player_name="T",
            opponent_team_name=nba_t.AWAY,
            projected_points=29.0,
            fanduel_line=26.5,
            fanduel_over_under="o",
            fanduel_price=-125,
        )
    )
    sqlite_db.commit()
    game = dict(
        game_date=nba_t.DAY, home_team_name=nba_t.HOME, away_team_name=nba_t.AWAY
    )
    (s,) = nba_t._spread_rows(sqlite_db)
    _ref(s, "pred_nba_spread_projections", **game)
    assert s["model_version"] is None
    (t,) = nba_t._total_rows(sqlite_db)
    _ref(t, "pred_nba_totals_projections", **game)
    (m,) = run(NBAMoneylineSource(sqlite_db).get_todays_projections(nba_t.RANGE))
    _ref(m, "pred_nba_spread_projections", **game)
    (p,) = run(PlayerPropSource(sqlite_db).get_todays_projections(nba_t.RANGE))
    _ref(p, "pred_points_projections", date=nba_t.DAY, player_id=1, stat="points")
    # provider copies it into the candidate metadata
    (c,) = run(SpreadCandidateProvider(NBASpreadSource(sqlite_db)).get_candidates(nba_t.RANGE))
    assert c.projection_metadata["projection_ref"] == s["projection_ref"]
    (c,) = run(TotalsCandidateProvider(NBATotalsSource(sqlite_db)).get_candidates(nba_t.RANGE))
    assert c.projection_metadata["projection_ref"] == t["projection_ref"]
    (c,) = run(PlayerPropCandidateProvider(PlayerPropSource(sqlite_db)).get_candidates(nba_t.RANGE))
    assert c.projection_metadata["projection_ref"] == p["projection_ref"]


def test_wnba_sources(sqlite_db):
    wnba_t._gl(sqlite_db)
    from app.models.predictions_models import (
        WNBASpreadProjections,
        WNBATotalsProjections,
    )

    names = dict(
        game_date=wnba_t.DAY, home_team_name=wnba_t.HOME, away_team_name=wnba_t.AWAY
    )
    sqlite_db.add(
        WNBATotalsProjections(
            **names, projected_total=168.5, market_total=165.5, recommendation="OVER"
        )
    )
    sqlite_db.add(
        WNBASpreadProjections(
            **names,
            projected_margin=1.0,
            market_spread_home=-3.5,
            edge=-4.5,
            recommendation="AWAY",
            home_win_prob=0.5,
        )
    )
    sqlite_db.add(
        WNBAPointsProjections(
            date=wnba_t.DAY,
            player_id=3,
            player_name="A",
            opponent_team_name=wnba_t.AWAY,
            projected_points=20.0,
            market_line=17.5,
            recommendation="OVER",
            fanduel_price=-110,
        )
    )
    sqlite_db.commit()
    (t,) = run(WNBATotalsSource(sqlite_db).get_todays_projections(wnba_t.RANGE))
    _ref(t, "pred_wnba_totals_projections", **names)
    (s,) = run(WNBASpreadSource(sqlite_db).get_todays_projections(wnba_t.RANGE))
    _ref(s, "pred_wnba_spread_projections", **names)
    (p,) = run(WNBAPlayerPropSource(sqlite_db).get_todays_projections(wnba_t.RANGE))
    _ref(p, "pred_wnba_points_projections", date=wnba_t.DAY, player_id=3, stat="points")


def test_mlb_sources(sqlite_db):
    mlb_t._proj(sqlite_db, model_version="k1")
    mlb_t._pitcher(sqlite_db)
    mlb_t._game(sqlite_db)
    sqlite_db.commit()
    (k,) = run(MLBStrikeoutSource(sqlite_db).get_todays_projections(mlb_t.DR))
    _ref(k, "pred_strikeout_projections", date=mlb_t.DAY, pitcher_id="p1")
    assert k["model_version"] == "k1"
    (g,) = run(MLBGameMoneylineSource(sqlite_db).get_todays_projections(mlb_t.DR))
    _ref(g, "pred_game_projections", date=mlb_t.DAY, game_id=77)
    assert g["model_version"] == "v1.0"  # column default
    (c,) = run(PlayerPropCandidateProvider(MLBStrikeoutSource(sqlite_db)).get_candidates(mlb_t.DR))
    assert c.projection_metadata["model_version"] == "k1"
    r = MagicMock(spec=["id", "player_id", "player_name", "game_id", "game_time",
                        "combined_score", "hits_last_10_games", "team", "opponent"])
    r.id, r.player_id, r.player_name, r.game_id = 5, "123", "A", 7
    r.game_time, r.combined_score, r.hits_last_10_games = datetime(2026, 6, 10), 3.5, 8
    r.team, r.opponent = "NYY", "BOS"
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [r]
    dr = DateRange(datetime(2026, 6, 10), datetime(2026, 6, 11), datetime(2026, 6, 10).date())
    (h,) = run(MLBHitsSource(db).get_todays_projections(dr))
    assert h["projection_ref"]["id"] == 5 and h["projection_ref"]["player_id"] == "123"
    assert h["model_version"] is None


def test_nfl_sources(sqlite_db):
    nfl_t._line(sqlite_db)
    nfl_t._qb(sqlite_db, model_version="q7")
    nfl_t._spread(sqlite_db)
    nfl_t._total(sqlite_db)
    dr = nfl_t.DR
    game = dict(game_date=nfl_t.DAY, home_team_name=nfl_t.HOME, away_team_name=nfl_t.AWAY)
    (q,) = run(NFLQBPassingSource(sqlite_db).get_todays_projections(dr))
    _ref(q, "pred_qb_predictions", qb_player_id="q1")
    assert q["model_version"] == "q7"
    (s,) = run(NFLSpreadSource(sqlite_db).get_todays_projections(dr))
    _ref(s, "pred_nfl_spread_projections", **game)
    (t,) = run(NFLTotalsSource(sqlite_db).get_todays_projections(dr))
    _ref(t, "pred_nfl_totals_projections", **game)
    assert NFLReceivingYardsSource  # recv table covered below


def test_nfl_receiving(sqlite_db):
    from app.models.predictions_models import RecvYdsPredictions

    nfl_t._line(sqlite_db)
    sqlite_db.add(
        RecvYdsPredictions(
            player_id="r1",
            player_name="R",
            team_name=nfl_t.HOME,
            opponent_team_name=nfl_t.AWAY,
            game_date=nfl_t.DAY,
            predicted_receiving_yards=80.0,
            ou_line=60.5,
            over_odds=-110,
            under_odds=-110,
            betting_recommendation="OVER",
            model_version="r2",
            season=2026,
            position="WR",
            week=10,
        )
    )
    sqlite_db.commit()
    (r,) = run(NFLReceivingYardsSource(sqlite_db).get_todays_projections(nfl_t.DR))
    _ref(r, "pred_recv_yds_predictions", game_date=nfl_t.DAY, player_id="r1")
    assert r["model_version"] == "r2"


def test_nhl_sources(sqlite_db):
    nhl_t._goalie(sqlite_db, 1, model_version="g3")
    nhl_t._totals(sqlite_db)
    (g,) = run(NHLGoalieSavesSource(sqlite_db).get_todays_projections(nhl_t.DR))
    _ref(g, "pred_nhl_goalie_predictions", game_date=nhl_t.DAY, goalie_id=1)
    assert g["model_version"] == "g3"
    (t,) = run(NHLTotalsSource(sqlite_db).get_todays_projections(nhl_t.DR))
    _ref(t, "pred_nhl_team_totals_predictions", game_date=nhl_t.DAY)


# --- orchestrator -----------------------------------------------------------


@pytest.mark.asyncio
async def test_bet_carries_projection_ref_and_model_version(sqlite_db, monkeypatch):
    monkeypatch.setattr(orch_mod, "_can_grade", lambda *a: True)
    ref = {"table": "pred_points_projections", "id": 42, "player_id": 1}
    c = orch_t._cand(1)
    c.projection_metadata.update(projection_ref=ref, model_version="m" * 120)
    c2 = orch_t._cand(2)
    await orch_t._run(sqlite_db, [c, c2])
    bets = {b.prediction_factors["event_id"]: b for b in orch_t._bets(sqlite_db)}
    assert bets["e1"].prediction_factors["projection_ref"] == ref
    assert bets["e1"].model_version == "m" * 100
    assert bets["e2"].prediction_factors["projection_ref"] is None
    assert bets["e2"].model_version is None


@pytest.mark.asyncio
async def test_parlay_leg_carries_projection_ref(sqlite_db):
    c = orch_t._cand(1)
    ref = {"table": "t", "id": 1}
    c.projection_metadata["projection_ref"] = ref
    sc = sel_t.ScoredCandidate(c, MagicMock(total=70.0, reasoning=""))
    leg = orch_mod.AutoPickOrchestrator(
        db=sqlite_db, providers=[], now=orch_t.NOW
    )._build_parlay_leg_dict(sc)
    assert leg["projection_ref"] == ref
