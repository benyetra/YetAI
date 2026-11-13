"""NFL sources: QB passing, receiving yards, spread, totals (real ORM rows)."""

import asyncio
from datetime import date, datetime

from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadProjections,
    NFLTotalsProjections,
    QBPredictions,
    RecvYdsPredictions,
)
from app.services.auto_pick.candidate import MarketType, slate_window_for_date
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.sources.nfl_qb_passing_source import NFLQBPassingSource
from app.services.auto_pick.sources.nfl_receiving_yards_source import (
    NFLReceivingYardsSource,
)
from app.services.auto_pick.sources.nfl_spread_source import NFLSpreadSource
from app.services.auto_pick.sources.nfl_totals_source import NFLTotalsSource

DAY = date(2026, 11, 15)
KICK_UTC = datetime(2026, 11, 15, 18, 0)  # 1pm ET
HOME, AWAY = "Kansas City Chiefs", "Buffalo Bills"
DR = slate_window_for_date(DAY)


def run(coro):
    return asyncio.run(coro)


def _line(db, **kw):
    gl = NFLGameLines(
        game_date=kw.pop("game_date", DAY),
        home_team_name=HOME,
        away_team_name=AWAY,
        odds_api_event_id="evt1",
        game_time=KICK_UTC,
        spread_home=-2.5,
        spread_home_odds=-108,
        spread_away_odds=-112,
        total=47.5,
        over_odds=-105,
        under_odds=-115,
        **kw,
    )
    db.add(gl)
    db.commit()
    return gl


def _qb(db, **kw):
    base = dict(
        qb_player_id="q1",
        qb_player_name="Patrick Mahomes",
        team_id=1,
        team_name=HOME,
        opponent_team_name="BUF",
        game_date=datetime(2026, 11, 15, 13, 0),  # naive ET kickoff
        venue_name="Arrowhead",
        season=2026,
        week=10,
        predicted_passing_yards=285.0,
        ou_line=271.5,
        over_odds=-115,
        under_odds=-105,
        betting_recommendation="OVER",
        model_confidence=0.7,
        prediction_date=datetime(2026, 11, 15, 9, 0),
    )
    base.update(kw)
    db.add(QBPredictions(**base))
    db.commit()


def test_qb_passing(sqlite_db):
    _line(sqlite_db)
    _qb(sqlite_db)
    _qb(sqlite_db, qb_player_id="q2", betting_recommendation="PASS")
    _qb(sqlite_db, qb_player_id="q3", over_odds=None)  # no price for side
    _qb(sqlite_db, qb_player_id="q4", game_date=datetime(2026, 11, 16, 20, 0))
    rows = run(NFLQBPassingSource(sqlite_db).get_todays_projections(DR))
    assert len(rows) == 1
    r = rows[0]
    assert (r["side"], r["line"], r["odds"], r["stat"]) == (
        "over",
        271.5,
        -115,
        "passing_yards",
    )
    assert r["game_date"] == DAY and r["commence_time"] == KICK_UTC
    assert (r["home_team_name"], r["away_team_name"]) == (HOME, AWAY)
    assert r["opponent"] == AWAY and r["event_id"].startswith("evt1")
    assert r["generated_at"] == datetime(2026, 11, 15, 9, 0)

    (c,) = run(
        PlayerPropCandidateProvider(NFLQBPassingSource(sqlite_db)).get_candidates(DR)
    )
    assert c.market_type == MarketType.PLAYER_PROP
    assert c.projection_metadata["side"] == "over"
    assert c.game_date == DAY and c.commence_time == KICK_UTC


def test_qb_under_uses_under_price(sqlite_db):
    _line(sqlite_db)
    _qb(sqlite_db, betting_recommendation="UNDER")
    (r,) = run(NFLQBPassingSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["odds"]) == ("under", -105)


def test_qb_without_game_line_skipped(sqlite_db):
    _qb(sqlite_db)
    assert run(NFLQBPassingSource(sqlite_db).get_todays_projections(DR)) == []


def test_receiving_yards(sqlite_db):
    _line(sqlite_db)

    def rec(pid, **kw):
        base = dict(
            season=2026,
            week=10,
            game_date=DAY,
            player_id=pid,
            player_name="Travis Kelce",
            position="TE",
            team_name=HOME,
            opponent_team_name=AWAY,
            predicted_receiving_yards=70.0,
            ou_line=61.5,
            over_odds=-120,
            under_odds=100,
            betting_recommendation="UNDER",
        )
        base.update(kw)
        sqlite_db.add(RecvYdsPredictions(**base))

    rec("a")
    rec("b", betting_recommendation="PASS")
    rec("c", under_odds=None)
    rec("d", game_date=date(2026, 11, 16))
    sqlite_db.commit()
    rows = run(NFLReceivingYardsSource(sqlite_db).get_todays_projections(DR))
    assert len(rows) == 1
    r = rows[0]
    assert (r["side"], r["line"], r["odds"], r["stat"]) == (
        "under",
        61.5,
        100,
        "receiving_yards",
    )
    assert r["commence_time"] == KICK_UTC and r["game_date"] == DAY
    assert (r["home_team_name"], r["away_team_name"]) == (HOME, AWAY)
    assert r["generated_at"] is None


def _spread(db, rec="HOME", **kw):
    db.add(
        NFLSpreadProjections(
            game_date=kw.pop("game_date", DAY),
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_margin=6.0,
            home_win_prob=0.7,
            market_spread_home=-2.5,
            edge=3.5,
            recommendation=rec,
            created_at=datetime(2026, 11, 15, 8, 0),
            **kw,
        )
    )
    db.commit()


def test_spread_home_and_away(sqlite_db):
    _line(sqlite_db)
    _spread(sqlite_db)
    (r,) = run(NFLSpreadSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["spread_odds"], r["market_spread_home"]) == (
        "home",
        -108,
        -2.5,
    )
    assert r["projected_margin"] == 6.0 and r["commence_time"] == KICK_UTC
    assert r["generated_at"] == datetime(2026, 11, 15, 8, 0)
    (c,) = run(SpreadCandidateProvider(NFLSpreadSource(sqlite_db)).get_candidates(DR))
    assert c.market_line == -2.5 and c.market_odds == -108
    assert c.game_date == DAY and c.projection_metadata["side"] == "home"


def test_spread_away_price_and_skips(sqlite_db):
    _line(sqlite_db)
    _spread(sqlite_db, rec="AWAY")
    (r,) = run(NFLSpreadSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["spread_odds"]) == ("away", -112)


def test_spread_no_play_missing_price_other_day(sqlite_db):
    _line(sqlite_db)
    _spread(sqlite_db, rec="NO_PLAY")
    _spread(sqlite_db, game_date=date(2026, 11, 16))
    assert run(NFLSpreadSource(sqlite_db).get_todays_projections(DR)) == []
    sqlite_db.query(NFLSpreadProjections).delete()
    sqlite_db.query(NFLGameLines).delete()
    gl = _line(sqlite_db)
    gl.spread_home_odds = None
    sqlite_db.commit()
    _spread(sqlite_db)
    assert run(NFLSpreadSource(sqlite_db).get_todays_projections(DR)) == []


def _total(db, rec="OVER", **kw):
    db.add(
        NFLTotalsProjections(
            game_date=kw.pop("game_date", DAY),
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_total=51.0,
            market_total=47.5,
            edge=3.5,
            recommendation=rec,
            created_at=datetime(2026, 11, 15, 8, 0),
            **kw,
        )
    )
    db.commit()


def test_totals(sqlite_db):
    _line(sqlite_db)
    _total(sqlite_db)
    (r,) = run(NFLTotalsSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["line_odds"], r["market_total"]) == ("over", -105, 47.5)
    assert r["commence_time"] == KICK_UTC and r["game_date"] == DAY
    assert (r["home_team_name"], r["away_team_name"]) == (HOME, AWAY)
    (c,) = run(TotalsCandidateProvider(NFLTotalsSource(sqlite_db)).get_candidates(DR))
    assert c.market_odds == -105 and c.projection_metadata["side"] == "over"
    assert c.game_date == DAY and c.commence_time == KICK_UTC


def test_totals_under_and_skips(sqlite_db):
    _line(sqlite_db)
    _total(sqlite_db, rec="UNDER")
    (r,) = run(NFLTotalsSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["line_odds"]) == ("under", -115)
    sqlite_db.query(NFLTotalsProjections).delete()
    _total(sqlite_db, rec="NO_PLAY")
    _total(sqlite_db, game_date=date(2026, 11, 16))
    assert run(NFLTotalsSource(sqlite_db).get_todays_projections(DR)) == []


def test_moved_line_spread_and_totals_rederive_edge(sqlite_db):
    # Projection: margin 6.0 vs -2.5 (HOME), total 51.0 vs 47.5 (OVER); threshold 3.0.
    for spread, total, kept in (
        (-4.0, 49.0, False),  # edge shrinks to 2.0 / 2.0
        (-1.5, 46.5, True),  # edge grows to 4.5 / 4.5
        (-10.0, 55.0, False),  # side flips
    ):
        sqlite_db.query(NFLSpreadProjections).delete()
        sqlite_db.query(NFLTotalsProjections).delete()
        sqlite_db.query(NFLGameLines).delete()
        gl = NFLGameLines(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            odds_api_event_id="evt1",
            game_time=KICK_UTC,
            spread_home=spread,
            spread_home_odds=-108,
            spread_away_odds=-112,
            total=total,
            over_odds=-105,
            under_odds=-115,
        )
        sqlite_db.add(gl)
        sqlite_db.commit()
        _spread(sqlite_db)
        _total(sqlite_db)
        s = run(NFLSpreadSource(sqlite_db).get_todays_projections(DR))
        t = run(NFLTotalsSource(sqlite_db).get_todays_projections(DR))
        if kept:
            assert s[0]["market_spread_home"] == spread and s[0]["edge"] == 4.5
            assert t[0]["market_total"] == total and t[0]["edge"] == 4.5
        else:
            assert s == [] and t == []
