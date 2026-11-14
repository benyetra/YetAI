"""NBA projections sample this season's games once a player or team has any."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v1 import predictions as predictions_module
from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    PlayerInjuryStatus,
    RecentGames,
    TeamDefenseStats,
    TeamRoster,
)
from app.services.etl.nba import _feature_engineering as fe
from app.services.etl.nba import generate_no_steals as gns
from app.services.etl.nba import totals_projector as tp
from app.services.etl.nba import update_team_defense_stats as utds
from app.services.etl.nba._samples import player_games
from app.services.ml import dataset_cache

OPENER = date(2026, 10, 20)
TODAY = date(2026, 11, 7)
LAST_SEASON = date(2026, 2, 1)
CELTICS = 1610612738
NUGGETS = 1610612743


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (
        NBAGameLines,
        NBASpreadActuals,
        PlayerInjuryStatus,
        RecentGames,
        TeamDefenseStats,
        TeamRoster,
    ):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def projector(db):
    tp.db = db
    tp._finals_cache.clear()
    yield
    tp.db = None
    tp._finals_cache.clear()
    tp.TEAM_NAME_TO_ID.clear()
    tp.TEAM_ID_TO_NAME.clear()


def add_games(db, player_id, start, n, points, minutes=30.0, opponent=CELTICS):
    db.add_all(
        RecentGames(
            player_id=player_id,
            game_date=start + timedelta(days=2 * i),
            opponent_team_id=opponent,
            points=points,
            minutes=minutes,
            home_game=i % 2 == 0,
        )
        for i in range(n)
    )
    db.commit()


def add_roster(db, team_id, player_id, name):
    db.add(
        TeamRoster(
            team_id=team_id,
            player_id=player_id,
            player_name=name,
            last_updated=datetime(2026, 11, 1),
        )
    )
    db.commit()


# --- player samples ----------------------------------------------------------


def test_player_games_use_this_season_once_there_is_one(db):
    add_games(db, 1, LAST_SEASON, 30, points=25)
    add_games(db, 1, OPENER, 1, points=10)
    games = player_games(db, 1, TODAY, 50)
    assert [g.points for g in games] == [10]


def test_player_games_reach_back_with_no_current_season_games(db):
    add_games(db, 1, LAST_SEASON, 30, points=25)
    games = player_games(db, 1, TODAY, 20)
    assert [g.points for g in games] == [25] * 20


def test_matchup_sample_stays_in_this_season(db):
    add_games(db, 1, LAST_SEASON, 4, points=25, opponent=NUGGETS)
    add_games(db, 1, OPENER, 2, points=8, opponent=NUGGETS)
    add_games(db, 1, OPENER + timedelta(days=5), 3, points=12, opponent=CELTICS)
    games = player_games(db, 1, TODAY, 10, RecentGames.opponent_team_id == NUGGETS)
    assert [g.points for g in games] == [8] * 2


def test_player_games_exclude_the_game_date_and_apply_criteria(db):
    add_games(db, 1, OPENER, 6, points=10)
    add_games(db, 1, OPENER + timedelta(days=1), 3, points=0, minutes=0)
    games = player_games(
        db, 1, OPENER + timedelta(days=10), 30, RecentGames.minutes > 0
    )
    assert len(games) == 5  # Oct 20-28; the Oct 30 game is on the date itself


def test_features_follow_this_seasons_role(db):
    # Last season's big role, this season's smaller one.
    add_games(db, 7, LAST_SEASON, 30, points=30, minutes=36)
    add_games(db, 7, OPENER, 8, points=12, minutes=24)
    feats = fe.build_features(db, 7, TODAY, CELTICS, "points")
    # Windows longer than the season so far average what there is.
    assert feats["points_avg_5"] == feats["points_avg_20"] == 12
    assert feats["minutes_avg_10"] == feats["avg_minutes_10"] == 24
    assert feats["is_starter"] == 0
    assert feats["points_matchup_mult"] == 1.0


def test_features_skip_until_five_current_season_games(db):
    add_games(db, 7, LAST_SEASON, 30, points=30)
    add_games(db, 7, OPENER, 2, points=12)
    # Two current-season games are not mixed with last season; the model waits.
    assert fe.build_features(db, 7, TODAY, CELTICS, "points") is None


# --- team defense ---------------------------------------------------------------


def test_defense_stats_drop_last_season_after_one_game(db, monkeypatch):
    for i in range(30):
        db.add(
            RecentGames(
                player_id=5,
                game_date=LAST_SEASON + timedelta(days=i),
                opponent_team_id=CELTICS,
                points=10,
            )
        )
    db.add(
        RecentGames(
            player_id=5,
            game_date=OPENER,
            opponent_team_id=CELTICS,
            points=40,
        )
    )
    db.commit()
    monkeypatch.setattr(utds, "SessionLocal", lambda: db)
    monkeypatch.setattr(utds, "NBA_TEAM_NAMES", {CELTICS: "Boston Celtics"})
    monkeypatch.setattr(
        utds, "now_eastern", lambda: datetime(2026, 11, 1, 4, 0, tzinfo=utds.EASTERN)
    )
    db.close = lambda: None
    utds.run()
    row = db.query(TeamDefenseStats).filter_by(team_id=CELTICS).one()
    assert row.points_allowed_per_game == 40


# --- totals adjustments ---------------------------------------------------------


def test_team_form_compares_to_this_seasons_average(db, projector):
    tp.TEAM_NAME_TO_ID["boston celtics"] = CELTICS
    add_roster(db, CELTICS, 1, "Steady Scorer")
    add_games(db, 1, LAST_SEASON, 40, points=30)
    add_games(db, 1, OPENER, 8, points=15)
    # Against a multi-season average (27.5) he'd look 12.5 points cold.
    assert tp.calculate_team_form("Boston Celtics", TODAY) == 0.0


def test_team_form_still_sees_a_slump(db, projector):
    tp.TEAM_NAME_TO_ID["boston celtics"] = CELTICS
    add_roster(db, CELTICS, 1, "Slumping Scorer")
    add_games(db, 1, OPENER, 5, points=20)
    add_games(db, 1, OPENER + timedelta(days=9), 5, points=10)
    assert tp.calculate_team_form("Boston Celtics", TODAY) == pytest.approx(-5.0)


def _denver_finals(db, n):
    db.add_all(
        NBASpreadActuals(
            game_date=OPENER + timedelta(days=2 * i),
            home_team_name="Denver Nuggets",
            away_team_name="Utah Jazz",
            home_score=120,
            away_score=110,
            actual_margin=10,
            home_won=True,
        )
        for i in range(n)
    )
    db.commit()


def test_injury_impact_scales_with_games_the_star_played(db, projector):
    tp.TEAM_NAME_TO_ID["denver nuggets"] = NUGGETS
    add_roster(db, NUGGETS, 203999, "Nikola Jokic")
    db.add(
        PlayerInjuryStatus(player_id=203999, player_name="Nikola Jokic", status="out")
    )
    _denver_finals(db, 8)
    add_games(db, 203999, OPENER, 2, points=30)
    impact, report = tp.calculate_injury_impact("Denver Nuggets", TODAY)
    assert impact == pytest.approx(-8.0 * 2 / 8)
    assert report[0]["player"] == "Nikola Jokic"


def test_season_long_absence_is_already_in_the_baseline(db, projector):
    tp.TEAM_NAME_TO_ID["denver nuggets"] = NUGGETS
    add_roster(db, NUGGETS, 203999, "Nikola Jokic")
    db.add(
        PlayerInjuryStatus(player_id=203999, player_name="Nikola Jokic", status="out")
    )
    _denver_finals(db, 8)
    assert tp.calculate_injury_impact("Denver Nuggets", TODAY) == (0.0, [])


def test_injury_impact_is_full_before_the_team_has_a_sample(db, projector):
    tp.TEAM_NAME_TO_ID["denver nuggets"] = NUGGETS
    add_roster(db, NUGGETS, 203999, "Nikola Jokic")
    db.add(
        PlayerInjuryStatus(player_id=203999, player_name="Nikola Jokic", status="out")
    )
    _denver_finals(db, 2)
    impact, _ = tp.calculate_injury_impact("Denver Nuggets", TODAY)
    assert impact == -8.0


# --- props API -------------------------------------------------------------------


def test_nba_minutes_only_count_this_season(db):
    add_games(db, 1, LAST_SEASON, 30, points=0, minutes=40)
    add_games(db, 1, OPENER, 5, points=0, minutes=10)
    add_games(db, 2, OPENER, 5, points=0, minutes=30)
    mpg = predictions_module._load_nba_season_minutes_avg(db, [1, 2, 3], TODAY)
    assert mpg == {1: 10.0, 2: 30.0}


def _prop_row(row_id, player_id, name):
    row = SimpleNamespace(
        id=row_id,
        date=TODAY,
        player_id=player_id,
        player_name=name,
        opponent_team_name="Opp",
        projected_points=10.0,
        fanduel_line=None,
    )
    row.__table__ = SimpleNamespace(
        columns=[SimpleNamespace(name=n) for n in row.__dict__ if not n.startswith("_")]
    )
    return row


def test_nba_props_ranked_by_minutes_not_insert_order(monkeypatch):
    # The cap and ranking apply to a live slate; past slates return every row.
    monkeypatch.setattr(predictions_module, "_is_past_date", lambda _d: False)
    db = MagicMock()
    model = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        _prop_row(100, 1, "Starter"),
        _prop_row(300, 3, "Wizards Bench"),
        _prop_row(200, 2, "Sixth Man"),
    ]
    monkeypatch.setattr(
        predictions_module,
        "_load_nba_season_minutes_avg",
        lambda _db, _ids, _as_of: {1: 34.0, 2: 26.0, 3: 9.0},
    )
    rows = predictions_module._query_nba_props_by_season_minutes(db, model, TODAY, 2)
    assert [r["player_name"] for r in rows] == ["Starter", "Sixth Man"]


# --- no steals ----------------------------------------------------------------------


def test_no_steals_probability_is_a_plain_float(monkeypatch):
    for helper in (
        "get_advanced_defensive_profile",
        "get_opponent_ball_handling_factor",
        "get_combined_pace_factor",
    ):
        monkeypatch.setattr(gns, helper, lambda *_a, **_k: 1.0)
    games = [SimpleNamespace(steals=0, minutes=20.0) for _ in range(5)]
    p = gns.calculate_no_steals_probability(
        player_career=SimpleNamespace(steals=10, minutes=1000.0),
        recent_games=games,
        opponent_offense_stats=SimpleNamespace(turnovers_per_game=14.0, pace=100.0),
        historical_matchups=[],
        avg_minutes=20.0,
        player_position="C",
        player_team_id=1,
        opponent_team_id=2,
    )
    assert type(p) is float and 0 < p <= 1


def test_dataset_cache_key_carries_the_feature_version():
    key = dataset_cache.cache_key(
        "nba/ml_models", "points", date(2024, 10, 1), date(2026, 6, 30), version=2
    )
    assert key == "nba/ml_datasets/points_2024-10-01_2026-06-30_v2.pkl"
