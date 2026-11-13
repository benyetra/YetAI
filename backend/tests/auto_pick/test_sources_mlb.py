"""MLB strikeout + game moneyline sources (real ORM rows)."""

import asyncio
from datetime import date, datetime

from app.models.predictions_models import GameProjections, Pitcher, StrikeoutProjections
from app.services.auto_pick.candidate import slate_window_for_date
from app.services.auto_pick.providers.moneyline_provider import (
    MoneylineCandidateProvider,
)
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.sources.mlb_game_source import MLBGameMoneylineSource
from app.services.auto_pick.sources.mlb_strikeout_source import MLBStrikeoutSource

DAY = date(2026, 6, 10)
DR = slate_window_for_date(DAY)
FIRST_PITCH = datetime(2026, 6, 10, 23, 5)  # naive UTC
NYY, BOS = "New York Yankees", "Boston Red Sox"


def run(coro):
    return asyncio.run(coro)


def _proj(db, pid="p1", **kw):
    base = dict(
        date=DAY,
        pitcher_id=pid,
        pitcher_name="Gerrit Cole",
        projected_strikeouts=8.5,
        projected_innings_pitched=6.0,
        projected_at_bats=24.0,
        fanduel_line=6.5,
        fanduel_over_under="over",
    )
    base.update(kw)
    db.add(StrikeoutProjections(**base))


def _pitcher(db, pid="p1", **kw):
    base = dict(
        name="Gerrit Cole",
        pitch_hand="R",
        team=NYY,
        opponent=BOS,
        game_time=FIRST_PITCH,
        venue_name="Yankee Stadium",
        k_per_9=10.0,
        last_5_avg_k_per_9=10.0,
        opponent_k_rate=22.0,
        combined_score=1.0,
        fanduel_point=6.5,
        fanduel_price=-135.0,
        fanduel_flag="o",
        game_status="Scheduled",
        pitcher_id=pid,
        projected_strikeouts=8.5,
        projected_innings=6.0,
        projected_at_bats=24.0,
        game_id=77,
    )
    base.update(kw)
    db.add(Pitcher(**base))


def _game(db, **kw):
    base = dict(
        date=DAY,
        game_id=77,
        home_team=BOS,
        away_team=NYY,
        home_win_prob=0.40,
        away_win_prob=0.60,
        projected_total=8.5,
        model_confidence=0.2,
        market_home_ml=150,
        market_away_ml=-170,
        ml_recommendation="AWAY",
        game_time=FIRST_PITCH,
        created_at=datetime(2026, 6, 10, 10, 0),
        updated_at=datetime(2026, 6, 10, 15, 0),
    )
    base.update(kw)
    db.add(GameProjections(**base))


def test_strikeouts_picked_side_price_and_teams(sqlite_db):
    _proj(sqlite_db)
    _pitcher(sqlite_db)
    _game(sqlite_db)
    sqlite_db.commit()
    (r,) = run(MLBStrikeoutSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["line"], r["odds"], r["stat"]) == (
        "over",
        6.5,
        -135,
        "strikeouts",
    )
    assert r["odds_assumed"] is False
    assert r["game_date"] == DAY and r["commence_time"] == FIRST_PITCH
    assert (r["home_team_name"], r["away_team_name"]) == (BOS, NYY)
    assert r["generated_at"] is None
    (c,) = run(
        PlayerPropCandidateProvider(MLBStrikeoutSource(sqlite_db)).get_candidates(DR)
    )
    assert c.projection_metadata["side"] == "over"
    assert c.commence_time == FIRST_PITCH and c.game_date == DAY


def test_strikeouts_price_for_other_side_is_assumed(sqlite_db):
    _proj(sqlite_db, projected_strikeouts=4.0, fanduel_over_under="under")
    _pitcher(sqlite_db)  # flag "o" -> price is not the under price
    sqlite_db.commit()
    (r,) = run(MLBStrikeoutSource(sqlite_db).get_todays_projections(DR))
    assert (r["side"], r["odds"], r["odds_assumed"]) == ("under", -110, True)
    # no GameProjections row: pitcher team is away, opponent home
    assert (r["home_team_name"], r["away_team_name"]) == (BOS, NYY)


def test_strikeouts_skips(sqlite_db):
    _proj(sqlite_db, "a", date=date(2026, 6, 9))  # other day
    _proj(sqlite_db, "b", projected_strikeouts=6.7)  # insufficient edge
    _proj(sqlite_db, "c", fanduel_line=None)
    _proj(sqlite_db, "d")  # no pitcher meta today
    _pitcher(sqlite_db, "a")
    _pitcher(sqlite_db, "b")
    _pitcher(sqlite_db, "c")
    _pitcher(sqlite_db, "d", game_time=datetime(2026, 6, 9, 23, 5))  # stale row
    sqlite_db.commit()
    assert run(MLBStrikeoutSource(sqlite_db).get_todays_projections(DR)) == []


def test_moneyline(sqlite_db):
    _game(sqlite_db)
    sqlite_db.commit()
    (r,) = run(MLBGameMoneylineSource(sqlite_db).get_todays_projections(DR))
    assert r["side"] == "away" and r["moneyline_away"] == -170
    assert (r["home_team_name"], r["away_team_name"]) == (BOS, NYY)
    assert r["game_date"] == DAY and r["commence_time"] == FIRST_PITCH
    assert r["generated_at"] == datetime(2026, 6, 10, 15, 0)
    (c,) = run(
        MoneylineCandidateProvider(MLBGameMoneylineSource(sqlite_db)).get_candidates(DR)
    )
    assert c.market_odds == -170 and c.our_projection == 0.60
    assert c.projection_metadata["side"] == "away"
    assert c.projection_metadata["opp_odds"] == 150
    assert c.game_date == DAY and c.commence_time == FIRST_PITCH


def test_moneyline_created_at_fallback_and_skips(sqlite_db):
    _game(sqlite_db, updated_at=None)
    _game(sqlite_db, game_id=2, ml_recommendation="NO_PLAY")
    _game(sqlite_db, game_id=3, market_away_ml=None)
    _game(sqlite_db, game_id=4, ml_recommendation=None)
    _game(sqlite_db, game_id=5, date=date(2026, 6, 11))
    sqlite_db.commit()
    (r,) = run(MLBGameMoneylineSource(sqlite_db).get_todays_projections(DR))
    assert r["generated_at"] == datetime(2026, 6, 10, 10, 0)
