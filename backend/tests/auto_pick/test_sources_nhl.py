"""NHL goalie saves + team totals sources (real ORM rows).

Seeds match etl/nhl/daily_predictions.py: place names for teams (full names come
from the NHL team id), recommendations "OVER 27.5" / "UNDER 6.0" / "PASS", no
``line_available`` (column default False), starter_confirmed True.
"""

import asyncio
from datetime import date, datetime

from app.models.predictions_models import NHLGoaliePredictions, NHLTeamTotalsPredictions
from app.services.auto_pick.candidate import slate_window_for_date
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.sources.nhl_goalie_saves_source import NHLGoalieSavesSource
from app.services.auto_pick.sources.nhl_totals_source import NHLTotalsSource

DAY = date(2026, 1, 15)
DR = slate_window_for_date(DAY)
START_ET = datetime(2026, 1, 15, 19, 0)  # naive ET
START_UTC = datetime(2026, 1, 16, 0, 0)  # 7pm EST
BOS, TOR = "Boston Bruins", "Toronto Maple Leafs"
BOS_ID, TOR_ID = 6, 10


def run(coro):
    return asyncio.run(coro)


def _goalie(db, gid, **kw):
    base = dict(
        game_date=DAY,
        goalie_id=gid,
        goalie_name=f"Goalie {gid}",
        team_id=BOS_ID,
        team_name="Boston",
        opponent_team_id=TOR_ID,
        opponent_team_name="Toronto",
        is_home=True,
        game_time=START_ET,
        starter_confirmed=True,
        was_scratch=False,
        predicted_saves=30.0,
        predicted_shots_against=32.0,
        predicted_save_pct=0.92,
        saves_line=27.5,
        over_odds=-120,
        under_odds=100,
        betting_recommendation="OVER 27.5",
        confidence=70.0,
        prediction_date=datetime(2026, 1, 15, 12, 0),
    )
    base.update(kw)
    db.add(NHLGoaliePredictions(**base))
    db.commit()


def test_goalie_saves_home_over(sqlite_db):
    _goalie(sqlite_db, 1)
    (r,) = run(NHLGoalieSavesSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["line"], r["odds"], r["stat"]) == ("over", 27.5, -120, "saves")
    assert r["game_date"] == DAY and r["commence_time"] == START_UTC
    assert (r["home_team_name"], r["away_team_name"]) == (BOS, TOR)
    assert r["generated_at"] == datetime(2026, 1, 15, 12, 0)
    assert r["injury_flag"] is False
    (c,) = run(
        PlayerPropCandidateProvider(NHLGoalieSavesSource(sqlite_db)).get_candidates(DR)
    )
    assert c.projection_metadata["side"] == "over"
    assert c.game_date == DAY and c.commence_time == START_UTC


def test_goalie_saves_away_under(sqlite_db):
    _goalie(sqlite_db, 1, is_home=False, betting_recommendation="UNDER 27.5")
    (r,) = run(NHLGoalieSavesSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["odds"]) == ("under", 100)
    assert (r["home_team_name"], r["away_team_name"]) == (TOR, BOS)


def test_goalie_saves_skips(sqlite_db):
    _goalie(sqlite_db, 1, starter_confirmed=False)
    _goalie(sqlite_db, 2, opponent_team_id=999)  # unresolvable team
    _goalie(sqlite_db, 3, betting_recommendation="PASS")
    _goalie(sqlite_db, 4, over_odds=None)
    _goalie(sqlite_db, 5, game_date=date(2026, 1, 16))
    _goalie(sqlite_db, 6, saves_line=None)
    assert run(NHLGoalieSavesSource(sqlite_db).get_todays_projections(DR)) == []


def _totals(db, **kw):
    base = dict(
        game_date=DAY,
        game_time_et=START_ET,
        home_team_id=BOS_ID,
        home_team_name="Boston",
        away_team_id=TOR_ID,
        away_team_name="Toronto",
        predicted_home_goals=3.4,
        predicted_away_goals=3.0,
        predicted_total_goals=6.4,
        suggested_ou_line=6.5,
        draftkings_ou_line=5.5,
        over_odds=-110,
        under_odds=-105,
        confidence=60.0,
        edge=0.9,
        betting_recommendation="OVER 5.5",
        prediction_date=datetime(2026, 1, 15, 12, 0),
    )
    base.update(kw)
    db.add(NHLTeamTotalsPredictions(**base))
    db.commit()


def test_totals(sqlite_db):
    _totals(sqlite_db)
    (r,) = run(NHLTotalsSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["line_odds"], r["market_total"]) == ("over", -110, 5.5)
    assert r["commence_time"] == START_UTC and r["game_date"] == DAY
    assert (r["home_team_name"], r["away_team_name"]) == (BOS, TOR)
    assert r["generated_at"] == datetime(2026, 1, 15, 12, 0)
    (c,) = run(TotalsCandidateProvider(NHLTotalsSource(sqlite_db)).get_candidates(DR))
    assert c.projection_metadata["side"] == "over"
    assert c.game_date == DAY and c.commence_time == START_UTC


def test_totals_under_price_and_skips(sqlite_db):
    _totals(sqlite_db, betting_recommendation="UNDER 5.5")
    (r,) = run(NHLTotalsSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["line_odds"]) == ("under", -105)
    sqlite_db.query(NHLTeamTotalsPredictions).delete()
    _totals(sqlite_db, betting_recommendation="PASS")
    _totals(
        sqlite_db, away_team_id=3, under_odds=None, betting_recommendation="UNDER 5.5"
    )
    _totals(sqlite_db, away_team_id=4, game_date=date(2026, 1, 16))
    _totals(sqlite_db, away_team_id=5, draftkings_ou_line=None)
    _totals(sqlite_db, away_team_id=999)  # unresolvable team
    assert run(NHLTotalsSource(sqlite_db).get_todays_projections(DR)) == []


def test_totals_new_york_resolved_by_team_id(sqlite_db):
    # Both NY teams are "New York" by place name; the id decides.
    _totals(sqlite_db, home_team_id=2, home_team_name="New York")
    _totals(sqlite_db, home_team_id=3, home_team_name="New York", away_team_id=6)
    rows = run(NHLTotalsSource(sqlite_db).get_todays_projections(DR))
    assert {r["home_team_name"] for r in rows} == {
        "New York Islanders",
        "New York Rangers",
    }


def test_utah_names_match_espn_display_name():
    from app.services.auto_pick.sources._nhl_teams import nhl_full_name

    assert nhl_full_name(59) == nhl_full_name(68) == "Utah Mammoth"
    assert nhl_full_name(6) == "Boston Bruins"
