"""Consensus-price path: sources build candidates from the stored best_* / ml_best_* quote."""

from datetime import date, datetime

import pytest

from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadProjections,
    NBATotalsProjections,
    NFLGameLines,
    NFLSpreadProjections,
    NFLTotalsProjections,
    NHLGoaliePredictions,
    NHLTeamTotalsPredictions,
    QBPredictions,
    RecvYdsPredictions,
    WNBAGameLines,
    WNBASpreadProjections,
)
from app.services.auto_pick import ev
from app.services.auto_pick.providers.moneyline_provider import (
    MoneylineCandidateProvider,
)
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.sources.nba_moneyline_source import NBAMoneylineSource
from app.services.auto_pick.sources.nba_spread_source import NBASpreadSource
from app.services.auto_pick.sources.nba_totals_source import NBATotalsSource
from app.services.auto_pick.sources.nfl_moneyline_source import NFLMoneylineSource
from app.services.auto_pick.sources.nfl_qb_passing_source import NFLQBPassingSource
from app.services.auto_pick.sources.nfl_receiving_yards_source import (
    NFLReceivingYardsSource,
)
from app.services.auto_pick.sources.nfl_spread_source import NFLSpreadSource
from app.services.auto_pick.sources.nfl_totals_source import NFLTotalsSource
from app.services.auto_pick.sources.nhl_goalie_saves_source import NHLGoalieSavesSource
from app.services.auto_pick.sources.nhl_totals_source import NHLTotalsSource
from app.services.auto_pick.sources.wnba_spread_source import WNBASpreadSource
from tests.auto_pick import test_sources_nba as nba
from tests.auto_pick import test_sources_nfl as nfl
from tests.auto_pick import test_sources_nhl as nhl

QUOTED = datetime(2026, 1, 15, 15, 30)
CREATED = datetime(2026, 1, 15, 15, 0)
FACTORS = {"anchor": {"k": 0.1}, "model_margin": 4.0}


def best(side, line, price, fair, prefix="best_"):
    out = {
        f"{prefix}book": "fanduel",
        f"{prefix}price": price,
        f"{prefix}side": side,
        f"{prefix}fair_prob": fair,
        f"{prefix}ev": 0.05,
        f"{prefix}quoted_at": QUOTED,
    }
    if line is not None:
        out[f"{prefix}line"] = line
    return out


def cands(provider, source, dr):
    return nba.run(provider(source).get_candidates(dr))


def priced(c):
    e, reason = ev.candidate_ev(c)
    return e, reason


# ---- NBA spread / total / moneyline -----------------------------------------


def test_nba_spread_away_best_quote_and_no_play_still_yields(sqlite_db):
    nba._gl(sqlite_db)
    # NO_PLAY by the projector; the away best quote carries the away line (+6.0).
    nba._spread(
        sqlite_db,
        rec="NO_PLAY",
        factors=FACTORS,
        **best("away", 6.0, -105, 0.56),
    )
    (r,) = nba.run(NBASpreadSource(sqlite_db).get_todays_projections(nba.RANGE))
    assert r["side"] == "away" and r["spread_odds"] == -105
    assert (
        r["market_spread_home"] == -6.0
    )  # emitted as the HOME line; provider flips it
    assert (r["fair_prob"], r["quoted_at"]) == (0.56, QUOTED)
    assert r["projected_at"] == nba.datetime(2026, 1, 15, 15, 0)
    (c,) = cands(SpreadCandidateProvider, NBASpreadSource(sqlite_db), nba.RANGE)
    assert c.market_line == 6.0 and c.market_odds == -105
    md = c.projection_metadata
    assert (md["anchor_k"], md["model_margin"]) == (0.1, 4.0)
    assert md["margin_scale"] == pytest.approx(6.6)
    assert md["fair_prob"] == 0.56 and md["quoted_at"] == QUOTED
    e, reason = priced(c)
    assert reason is None and e is not None


def test_nba_spread_home_best_quote(sqlite_db):
    nba._gl(sqlite_db)
    nba._spread(sqlite_db, rec="HOME", **best("home", -5.5, -110, 0.52))
    (c,) = cands(SpreadCandidateProvider, NBASpreadSource(sqlite_db), nba.RANGE)
    assert c.market_line == -5.5 and c.projection_metadata["side"] == "home"


def test_nba_spread_without_quote_is_unpriced(sqlite_db):
    nba._gl(sqlite_db)
    nba._spread(sqlite_db, rec="NO_PLAY")
    (r,) = nba.run(NBASpreadSource(sqlite_db).get_todays_projections(nba.RANGE))
    assert r["side"] == "away" and r["spread_odds"] == -108 and "quoted_at" not in r
    (c,) = cands(SpreadCandidateProvider, NBASpreadSource(sqlite_db), nba.RANGE)
    assert "quoted_at" not in c.projection_metadata
    assert priced(c) == (None, "no_consensus_price")
    # no stored odds for the side either: skipped
    sqlite_db.query(NBAGameLines).update({"spread_away_odds": None})
    assert nba.run(NBASpreadSource(sqlite_db).get_todays_projections(nba.RANGE)) == []


def test_nba_totals_best_and_unpriced(sqlite_db):
    nba._gl(sqlite_db)
    sqlite_db.add(
        NBATotalsProjections(
            game_date=nba.DAY,
            home_team_name=nba.HOME,
            away_team_name=nba.AWAY,
            projected_total=231.0,
            market_total=225.5,
            recommendation="NO_PLAY",
            created_at=CREATED,
            **best("under", 227.5, -108, 0.55),
        )
    )
    (c,) = cands(TotalsCandidateProvider, NBATotalsSource(sqlite_db), nba.RANGE)
    # best quote wins over the stored projection's own side
    assert (c.market_line, c.market_odds) == (227.5, -108)
    assert c.projection_metadata["side"] == "under"
    assert c.projection_metadata["fair_prob"] == 0.55
    assert c.projection_metadata["projected_at"] == CREATED
    sqlite_db.query(NBATotalsProjections).update(
        {"best_side": None, "best_price": None, "best_line": None}
    )
    (c,) = cands(TotalsCandidateProvider, NBATotalsSource(sqlite_db), nba.RANGE)
    assert c.projection_metadata["side"] == "over" and c.market_odds == -115
    assert priced(c) == (None, "no_consensus_price")


def test_nba_moneyline_best_and_unpriced(sqlite_db):
    nba._gl(sqlite_db)
    nba._spread(
        sqlite_db,
        rec="NO_PLAY",
        hwp=0.4,
        factors=FACTORS,
        **best("away", None, 180, 0.38, prefix="ml_best_"),
    )
    (c,) = cands(MoneylineCandidateProvider, NBAMoneylineSource(sqlite_db), nba.RANGE)
    md = c.projection_metadata
    assert (c.market_odds, c.our_projection) == (180, pytest.approx(0.6))
    assert md["side"] == "away" and md["fair_prob"] == 0.38
    assert md["quoted_at"] == QUOTED and md["opp_odds"] is None
    assert md["market_margin"] == 6.5 and md["anchor_k"] == 0.1
    e, reason = priced(c)
    assert e is not None and reason is None
    # no ml quote: stored-projection side at the stored price, unpriced
    sqlite_db.query(NBASpreadProjections).update(
        {"ml_best_side": None, "ml_best_price": None}
    )
    (c,) = cands(MoneylineCandidateProvider, NBAMoneylineSource(sqlite_db), nba.RANGE)
    assert c.market_odds == 170 and "quoted_at" not in c.projection_metadata
    assert priced(c) == (None, "no_consensus_price")


# ---- WNBA unchanged ----------------------------------------------------------


def test_wnba_spread_still_follows_the_recommendation(sqlite_db):
    sqlite_db.add(
        WNBAGameLines(
            game_date=date(2026, 7, 10),
            home_team_name="Las Vegas Aces",
            away_team_name="Seattle Storm",
            spread_home=-3.5,
            spread_home_odds=-110,
            spread_away_odds=-105,
        )
    )
    base = dict(
        game_date=date(2026, 7, 10),
        home_team_name="Las Vegas Aces",
        away_team_name="Seattle Storm",
        projected_margin=9.0,
        home_win_prob=0.8,
        market_spread_home=-3.5,
        edge=5.5,
    )
    sqlite_db.add(WNBASpreadProjections(recommendation="NO_PLAY", **base))
    from tests.auto_pick import test_sources_wnba as w

    assert w.run(WNBASpreadSource(sqlite_db).get_todays_projections(w.RANGE)) == []
    sqlite_db.query(WNBASpreadProjections).update({"recommendation": "HOME"})
    (r,) = w.run(WNBASpreadSource(sqlite_db).get_todays_projections(w.RANGE))
    assert r["side"] == "home" and r["spread_odds"] == -110
    assert "fair_prob" not in r and "projected_at" not in r  # outside the new gates


# ---- NFL ---------------------------------------------------------------------


def _nfl_spread(db, **kw):
    nfl._spread(db, factors=FACTORS, **kw)


def test_nfl_spread_moneyline_totals_best(sqlite_db):
    nfl._line(sqlite_db, moneyline_home=-130, moneyline_away=110)
    _nfl_spread(
        sqlite_db,
        rec="NO_PLAY",
        **best("away", 3.0, -104, 0.5),
        **best("away", None, 115, 0.44, prefix="ml_best_"),
    )
    nfl._total(
        sqlite_db,
        rec="NO_PLAY",
        **best("under", 48.5, -102, 0.52),
    )
    (s,) = cands(SpreadCandidateProvider, NFLSpreadSource(sqlite_db), nfl.DR)
    assert (s.market_line, s.market_odds) == (3.0, -104)
    assert s.projection_metadata["margin_scale"] == pytest.approx(7.4)
    assert s.projection_metadata["fair_prob"] == 0.5
    assert s.projection_metadata["projected_at"] == datetime(2026, 11, 15, 8, 0)
    (m,) = cands(MoneylineCandidateProvider, NFLMoneylineSource(sqlite_db), nfl.DR)
    assert (m.market_odds, m.projection_metadata["side"]) == (115, "away")
    assert m.our_projection == pytest.approx(0.3)
    assert m.projection_metadata["quoted_at"] == QUOTED
    assert m.projection_metadata["market_margin"] == 2.5
    (t,) = cands(TotalsCandidateProvider, NFLTotalsSource(sqlite_db), nfl.DR)
    assert (t.market_line, t.market_odds) == (48.5, -102)
    assert t.projection_metadata["side"] == "under"


def test_nfl_spread_moneyline_totals_unpriced(sqlite_db):
    nfl._line(sqlite_db, moneyline_home=-130, moneyline_away=110)
    _nfl_spread(sqlite_db, rec="NO_PLAY")
    nfl._total(sqlite_db, rec="NO_PLAY")
    for prov, src in (
        (SpreadCandidateProvider, NFLSpreadSource),
        (MoneylineCandidateProvider, NFLMoneylineSource),
        (TotalsCandidateProvider, NFLTotalsSource),
    ):
        (c,) = cands(prov, src(sqlite_db), nfl.DR)
        assert "quoted_at" not in c.projection_metadata
        assert priced(c) == (None, "no_consensus_price")


def test_nfl_props_best_quote(sqlite_db):
    nfl._line(sqlite_db)
    nfl._qb(
        sqlite_db, betting_recommendation="PASS", **best("under", 268.5, -108, 0.54)
    )
    sqlite_db.add(
        RecvYdsPredictions(
            season=2026,
            week=10,
            game_date=nfl.DAY,
            player_id="a",
            player_name="Travis Kelce",
            position="TE",
            team_name=nfl.HOME,
            opponent_team_name=nfl.AWAY,
            predicted_receiving_yards=70.0,
            ou_line=61.5,
            over_odds=-120,
            under_odds=100,
            betting_recommendation="PASS",
            **best("over", 62.5, -112, 0.53),
        )
    )
    sqlite_db.commit()
    (q,) = cands(PlayerPropCandidateProvider, NFLQBPassingSource(sqlite_db), nfl.DR)
    assert (q.market_line, q.market_odds) == (268.5, -108)
    md = q.projection_metadata
    assert md["side"] == "under" and md["fair_prob"] == 0.54
    assert md["projected_at"] == datetime(2026, 11, 15, 9, 0)
    assert md["quoted_at"] == QUOTED
    (r,) = cands(
        PlayerPropCandidateProvider, NFLReceivingYardsSource(sqlite_db), nfl.DR
    )
    assert (r.market_line, r.market_odds) == (62.5, -112)
    # no refresh stamp on these rows: freshness is the quote's
    assert r.projection_metadata["projected_at"] == QUOTED
    assert r.projection_metadata["quoted_at"] == QUOTED
    # without a quote: stored side, no freshness keys, unpriced
    sqlite_db.query(RecvYdsPredictions).update({"best_side": None, "best_price": None})
    sqlite_db.query(QBPredictions).update({"best_side": None, "best_price": None})
    for src in (NFLQBPassingSource, NFLReceivingYardsSource):
        (c,) = cands(PlayerPropCandidateProvider, src(sqlite_db), nfl.DR)
        assert "quoted_at" not in c.projection_metadata
        assert priced(c) == (None, "no_consensus_price")


# ---- NHL ---------------------------------------------------------------------


def test_nhl_totals_and_goalie_best_and_unpriced(sqlite_db):
    nhl._totals(
        sqlite_db, betting_recommendation="PASS", **best("under", 6.0, -105, 0.51)
    )
    nhl._goalie(
        sqlite_db, 1, betting_recommendation="PASS", **best("under", 26.5, -110, 0.5)
    )
    (t,) = cands(TotalsCandidateProvider, NHLTotalsSource(sqlite_db), nhl.DR)
    assert (t.market_line, t.market_odds, t.projection_metadata["side"]) == (
        6.0,
        -105,
        "under",
    )
    assert t.projection_metadata["projected_at"] == datetime(2026, 1, 15, 12, 0)
    assert t.projection_metadata["quoted_at"] == QUOTED
    (g,) = cands(PlayerPropCandidateProvider, NHLGoalieSavesSource(sqlite_db), nhl.DR)
    assert (g.market_line, g.market_odds) == (26.5, -110)
    assert g.projection_metadata["fair_prob"] == 0.5
    sqlite_db.query(NHLTeamTotalsPredictions).update({"best_side": None})
    sqlite_db.query(NHLGoaliePredictions).update({"best_side": None})
    for prov, src in (
        (TotalsCandidateProvider, NHLTotalsSource),
        (PlayerPropCandidateProvider, NHLGoalieSavesSource),
    ):
        (c,) = cands(prov, src(sqlite_db), nhl.DR)
        assert "quoted_at" not in c.projection_metadata
        assert priced(c) == (None, "no_consensus_price")


def test_goalie_filters_kept_with_best_quote(sqlite_db):
    nhl._goalie(sqlite_db, 1, was_scratch=True, **best("over", 27.5, -110, 0.5))
    nhl._goalie(
        sqlite_db,
        2,
        team_id=7,
        starter_confirmed=False,
        **best("over", 27.5, -110, 0.5),
    )
    assert nba.run(NHLGoalieSavesSource(sqlite_db).get_todays_projections(nhl.DR)) == []
