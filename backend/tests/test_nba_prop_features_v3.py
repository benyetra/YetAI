"""NBA prop features: opponent defense as of the game date, the Vegas line
found through the opponent, and the recency / rate / volume features."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    NBAGameLines,
    RecentGames,
    TeamDefenseStats,
    TeamRoster,
)
from app.services.etl.nba import _feature_engineering as fe
from app.services.etl.nba import _team_defense as td
from app.services.etl.nba import generate_pra_predictions as pra
from app.services.etl.nba import update_team_defense_stats as utds

OPENER = date(2026, 10, 20)
TODAY = date(2026, 11, 20)
CELTICS = 1610612738
NUGGETS = 1610612743
LAKERS = 1610612747


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (NBAGameLines, RecentGames, TeamDefenseStats, TeamRoster):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    td.clear_cache()
    yield session
    session.close()
    td.clear_cache()


def game(player_id, day, *, opponent=CELTICS, points=20.0, minutes=30.0, **stats):
    row = dict(
        player_id=player_id,
        game_date=day,
        opponent_team_id=opponent,
        points=points,
        minutes=minutes,
        rebounds=5.0,
        assists=4.0,
        fg_attempts=15.0,
        three_pt_attempts=5.0,
        ft_attempts=4.0,
        turnovers=2.0,
        personal_fouls=2.0,
        home_game=True,
    )
    row.update(stats)
    return RecentGames(**row)


def add_player_games(db, player_id, points, *, start=OPENER, minutes=None, **stats):
    """One game every other day, oldest first, against the Celtics."""
    minutes = minutes or [30.0] * len(points)
    db.add_all(
        game(
            player_id,
            start + timedelta(days=2 * i),
            points=p,
            minutes=m,
            **stats,
        )
        for i, (p, m) in enumerate(zip(points, minutes))
    )
    db.commit()


# ---- opponent defense as of a date --------------------------------------------


def test_team_defense_only_counts_games_before_the_date(db):
    # Nuggets allowed 100 early, 140 late.
    for i in range(4):
        db.add(game(100 + i, OPENER + timedelta(days=i), opponent=NUGGETS, points=100))
    for i in range(4):
        db.add(
            game(200 + i, OPENER + timedelta(days=10 + i), opponent=NUGGETS, points=140)
        )
    db.commit()

    early = td.team_defense_as_of(db, NUGGETS, OPENER + timedelta(days=5))
    late = td.team_defense_as_of(db, NUGGETS, TODAY)
    assert early["points_allowed_per_game"] == 100.0
    assert early["games"] == 4
    assert late["points_allowed_per_game"] == 120.0
    assert td.team_defense_as_of(db, NUGGETS, OPENER) is None


def test_team_defense_sums_a_teams_players_per_game(db):
    day = OPENER + timedelta(days=1)
    db.add_all(
        [
            game(1, day, opponent=NUGGETS, points=30, rebounds=10),
            game(2, day, opponent=NUGGETS, points=20, rebounds=4),
            game(3, day + timedelta(days=2), opponent=NUGGETS, points=40, rebounds=6),
        ]
    )
    db.commit()
    out = td.team_defense_as_of(db, NUGGETS, TODAY)
    assert out["games"] == 2
    assert out["points_allowed_per_game"] == 45.0  # (50 + 40) / 2
    assert out["rebounds_allowed_per_game"] == 10.0
    assert out["defensive_rating"] == round(114.0 * 45.0 / 95.0, 1)


def test_team_defense_uses_this_season_once_it_has_a_game(db):
    for i in range(5):
        db.add(game(i, date(2026, 3, 1 + i), opponent=NUGGETS, points=90))
    db.add(game(9, OPENER, opponent=NUGGETS, points=130))
    db.commit()
    assert td.team_defense_as_of(db, NUGGETS, TODAY)["points_allowed_per_game"] == 130
    # Before this season's first game it still reaches back.
    assert td.team_defense_as_of(db, NUGGETS, OPENER)["points_allowed_per_game"] == 90


def test_stored_defense_table_matches_what_features_compute_for_tomorrow(db):
    for i in range(6):
        db.add(game(i, OPENER + timedelta(days=i), opponent=NUGGETS, points=110 + i))
    db.commit()
    with (
        patch.object(utds, "SessionLocal", return_value=db),
        patch.object(utds, "now_eastern", return_value=datetime(2026, 11, 19, 3, 30)),
        patch.object(db, "close"),
    ):
        result = utds.run()
    assert result["teams_updated"] == 1
    stored = db.query(TeamDefenseStats).filter_by(team_id=NUGGETS).one()
    live = td.team_defense_as_of(db, NUGGETS, date(2026, 11, 20))
    assert stored.points_allowed_per_game == live["points_allowed_per_game"] == 112.5
    assert stored.defensive_rating == live["defensive_rating"]


def test_features_see_the_opponents_defense_as_of_each_game(db):
    add_player_games(db, 7, [20.0] * 12)
    # Nuggets: stingy through October, porous in November.
    for i in range(5):
        db.add(game(300 + i, OPENER + timedelta(days=i), opponent=NUGGETS, points=95))
    for i in range(5):
        db.add(game(400 + i, date(2026, 11, 10 + i), opponent=NUGGETS, points=135))
    db.commit()
    # A stale "today" row must not leak into a past game's features.
    db.add(
        TeamDefenseStats(
            team_id=NUGGETS,
            team_name="Denver Nuggets",
            points_allowed_per_game=999.0,
            defensive_rating=999.0,
        )
    )
    db.commit()

    then = fe.build_features(db, 7, date(2026, 11, 1), NUGGETS, "points")
    now = fe.build_features(db, 7, TODAY, NUGGETS, "points")
    assert then["opp_stat_allowed"] == 95.0
    assert now["opp_stat_allowed"] == 115.0
    assert then["opp_def_rating"] < now["opp_def_rating"] < 999.0


def test_features_fall_back_to_the_stored_row_without_game_logs(db):
    add_player_games(db, 7, [20.0] * 6)
    db.add(
        TeamDefenseStats(
            team_id=LAKERS,
            team_name="Los Angeles Lakers",
            points_allowed_per_game=118.0,
            defensive_rating=141.6,
        )
    )
    db.commit()
    feats = fe.build_features(db, 7, TODAY, LAKERS, "points")
    assert feats["opp_stat_allowed"] == 118.0
    assert feats["opp_def_rating"] == 141.6


# ---- Vegas line through the opponent ----------------------------------------------


def test_line_is_found_through_the_opponent_even_after_a_trade(db):
    add_player_games(db, 7, [20.0] * 6)
    # The roster says he is a Laker today; on this date he played the Nuggets
    # for someone else.
    db.add(
        TeamRoster(
            team_id=LAKERS,
            player_id=7,
            player_name="Traded Guy",
            last_updated=datetime(2026, 11, 19),
        )
    )
    db.add(
        NBAGameLines(
            game_date=TODAY,
            home_team_name="Denver Nuggets",
            away_team_name="Boston Celtics",
            spread_home=-6.5,
            spread_away=6.5,
            total=228.5,
        )
    )
    db.commit()
    feats = fe.build_features(db, 7, TODAY, NUGGETS, "points")
    assert feats["total"] == 228.5
    assert feats["is_home"] == 0  # the opponent is the home team
    assert feats["spread"] == 6.5
    assert feats["is_favorite"] == 0


def test_no_line_leaves_the_market_features_neutral(db):
    add_player_games(db, 7, [20.0] * 6)
    feats = fe.build_features(db, 7, TODAY, NUGGETS, "points")
    assert (feats["spread"], feats["total"], feats["is_home"]) == (0, 0, 0)
    assert feats["blowout_risk"] == 0.15


# ---- recency / rate / volume --------------------------------------------------------


def test_recency_features_weight_the_latest_games_most(db):
    # Six quiet games, then a new role: 30 a night.
    add_player_games(db, 7, [10.0] * 6 + [30.0] * 4)
    feats = fe.build_features(db, 7, TODAY, CELTICS, "points")
    assert feats["points_avg_season"] == 18.0
    assert feats["points_last"] == 30.0
    assert feats["sample_games"] == 10
    assert feats["points_avg_season"] < feats["points_ewm_10"] < feats["points_ewm_5"]
    assert feats["points_ewm_5"] < 30.0


def test_rate_times_minutes_follows_a_minutes_jump(db):
    # 0.5 points a minute throughout; minutes go from 16 to 32.
    minutes = [16.0] * 8 + [32.0] * 3
    add_player_games(db, 7, [m / 2 for m in minutes], minutes=minutes)
    feats = fe.build_features(db, 7, TODAY, CELTICS, "points")
    assert feats["points_per_min_20"] == pytest.approx(0.5)
    assert feats["minutes_avg_3"] == 32.0
    assert feats["minutes_last"] == 32.0
    assert feats["minutes_ewm_3"] > feats["minutes_avg_season"]
    # The 10-game average still says ~10.9; rate x recent minutes is ahead of it.
    assert feats["points_rate_x_min_5"] == pytest.approx(0.5 * (16 * 2 + 32 * 3) / 5)
    assert feats["points_rate_x_min_5"] > feats["points_avg_10"]


def test_volume_features_average_shot_attempts(db):
    add_player_games(
        db, 7, [20.0] * 12, fg_attempts=18.0, three_pt_attempts=7.0, ft_attempts=6.0
    )
    feats = fe.build_features(db, 7, TODAY, CELTICS, "points")
    assert feats["fg_attempts_avg_10"] == feats["fg_attempts_avg_20"] == 18.0
    assert feats["three_pt_attempts_avg_10"] == 7.0
    assert feats["ft_attempts_avg_10"] == 6.0
    assert feats["turnovers_avg_10"] == 2.0


def test_new_features_tolerate_missing_box_score_columns(db):
    add_player_games(
        db, 7, [12.0] * 6, fg_attempts=None, three_pt_attempts=None, ft_attempts=None
    )
    feats = fe.build_features(db, 7, TODAY, CELTICS, "points")
    assert feats["fg_attempts_avg_10"] == 0.0
    assert feats["points_ewm_5"] == pytest.approx(12.0)


def test_legacy_feature_names_are_still_produced(db):
    add_player_games(db, 7, [20.0] * 12)
    feats = fe.build_features(db, 7, TODAY, CELTICS, "points")
    for name in (
        "points_avg_5",
        "points_avg_10",
        "points_avg_20",
        "points_std_10",
        "minutes_avg_5",
        "avg_minutes_10",
        "is_starter",
        "days_rest",
        "opp_def_rating",
        "opp_pace",
        "opp_stat_allowed",
        "spread",
        "total",
        "is_home",
        "month",
        "home_away_split",
    ):
        assert name in feats, name
    assert fe.FEATURES_VERSION == 3


# ---- PRA ----------------------------------------------------------------------------


def test_pra_mean_is_the_sum_of_its_parts():
    assert pra.CORRELATION_ADJUSTMENT == 1.0


# ---- a player ruled out after the overnight run ---------------------------------


def test_mark_projection_out_flags_only_that_players_row_and_keeps_it(db):
    from app.models.predictions_models import PointsProjections
    from app.services.etl.nba._stale_rows import mark_projection_out

    PointsProjections.__table__.create(db.get_bind())
    for pid, day in ((7, TODAY), (8, TODAY), (7, TODAY - timedelta(days=1))):
        db.add(
            PointsProjections(
                date=day,
                player_id=pid,
                player_name=f"p{pid}",
                opponent_team_name="Boston Celtics",
                projected_points=20.0,
                fanduel_line=19.5,
                fanduel_over_under="o",
            )
        )
    db.commit()

    assert mark_projection_out(db, PointsProjections, TODAY, 7) is True
    sides = {
        (r.player_id, r.date): (r.fanduel_line, r.fanduel_over_under)
        for r in db.query(PointsProjections).all()
    }
    assert sides == {
        (7, TODAY): (19.5, "OUT"),
        (8, TODAY): (19.5, "o"),
        (7, TODAY - timedelta(days=1)): (19.5, "o"),
    }


@pytest.mark.parametrize(
    "module_name,model_name",
    [
        ("generate_points_predictions", "PointsProjections"),
        ("generate_rebounds_predictions", "ReboundsProjections"),
        ("generate_assists_predictions", "AssistsProjections"),
        ("generate_three_pt_made_predictions", "ThreePointProjections"),
        ("generate_steals_predictions", "StealsProjections"),
        ("generate_blocks_predictions", "BlocksProjections"),
        ("generate_free_throws_made_predictions", "FreeThrowPredictions"),
    ],
)
def test_generators_flag_the_morning_row_of_a_player_now_out(module_name, model_name):
    import importlib
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    module = importlib.import_module(f"app.services.etl.nba.{module_name}")
    player = SimpleNamespace(
        player_id=42,
        player_name="Ruled Out",
        team_name="Boston Celtics",
        opponent_team_name="Denver Nuggets",
        opponent_team_id=NUGGETS,
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [player]
    patches = [
        patch.object(module, "SessionLocal", return_value=mock_db),
        patch.object(module, "active_players_not_started", return_value=[player]),
        patch.object(module, "now_eastern", return_value=datetime(2026, 11, 20, 17)),
        patch.object(module, "_is_injured", return_value=(True, "out")),
        patch.object(module, "mark_projection_out"),
    ]
    if hasattr(module, "resolve_nba_prop_model_version"):
        patches.append(
            patch.object(module, "resolve_nba_prop_model_version", return_value="t")
        )
    if hasattr(module, "line_diagnostics"):
        patches.append(patch.object(module, "line_diagnostics", return_value={}))
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        result = module.run()

    assert result["skipped_injured"] == 1
    drop = mocks[4]
    drop.assert_called_once()
    args = drop.call_args[0]
    assert args[1].__name__ == model_name
    assert args[2:] == (TODAY, 42)
