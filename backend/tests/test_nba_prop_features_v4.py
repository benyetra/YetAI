"""NBA prop features v4: team availability, role shares, return and sample rules."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    NBAGameLines,
    PlayerInjuryStatus,
    RecentGames,
    TeamDefenseStats,
    TeamRoster,
    TodayActivePlayers,
)
from app.services.etl.nba import _feature_engineering as fe
from app.services.etl.nba import _ml_predict
from app.services.etl.nba._team_context import DOUBTFUL_WEIGHT, team_context
from app.services.etl.nba.ml_training import run_train_props

OPENER = date(2026, 10, 20)
TARGET = OPENER + timedelta(days=30)
OPP = 1610612738  # the team our players face
OWN = 1610612743  # our players' team
P, STAR, MID, BENCH = 1, 2, 3, 4  # BENCH never reaches the rotation

# Game-line features: NaN in v4 when no stored line says otherwise.
LINE_KEYS = ("spread", "total", "is_home", "is_favorite", "blowout_risk")

# v3 keys and values on the fixture in `_v3_fixture`, taken before v4 existed.
V3_BASELINE = {
    "points_avg_5": 19.0,
    "points_std_5": 1.5811388300841898,
    "points_avg_10": 16.5,
    "points_std_10": 3.0276503540974917,
    "points_avg_20": 15.5,
    "points_std_20": 3.605551275463989,
    "minutes_avg_5": 25.8,
    "minutes_std_5": 1.3038404810405297,
    "minutes_avg_10": 25.7,
    "minutes_std_10": 1.1595018087284057,
    "points_ewm_5": 17.08000438152746,
    "points_ewm_10": 16.316565048162232,
    "points_avg_season": 15.5,
    "points_last": 21.0,
    "sample_games": 12.0,
    "points_per_min_20": 0.6078431372549019,
    "points_rate_x_min_5": 15.68235294117647,
    "points_rate_x_min_10": 15.621568627450978,
    "minutes_avg_3": 26.0,
    "minutes_avg_20": 25.5,
    "minutes_avg_season": 25.5,
    "minutes_ewm_3": 25.784530246846938,
    "minutes_last": 27.0,
    "fg_attempts_avg_10": 16.5,
    "fg_attempts_avg_20": 15.5,
    "three_pt_attempts_avg_10": 4.0,
    "ft_attempts_avg_10": 3.0,
    "turnovers_avg_10": 2.0,
    "personal_fouls_avg_10": 2.0,
    "points_trend": 1.0,
    "points_trend_pct": 0.22580645161290322,
    "points_matchup_avg": 15.5,
    "points_matchup_games": 12.0,
    "points_matchup_mult": 1.0,
    "days_rest": 9.0,
    "is_b2b": 0.0,
    "games_last_7_days": 0.0,
    "avg_minutes_5": 25.8,
    "avg_minutes_10": 25.7,
    "minutes_std": 1.1595018087284057,
    "is_starter": 0.0,
    "usage_percentage_avg": 0.0,
    "true_shooting_percentage_avg": 0.0,
    "effective_field_goal_percentage_avg": 0.0,
    "offensive_rating_avg": 0.0,
    "defensive_rating_avg": 0.0,
    "assist_percentage_avg": 0.0,
    "rebound_percentage_avg": 0.0,
    "turnover_percentage_avg": 0.0,
    "plus_minus_avg": 0.0,
    "pace_avg": 0.0,
    "opp_def_rating": 18.6,
    "opp_pace": 0.0,
    "opp_stat_allowed": 15.5,
    "spread": 0.0,
    "total": 0.0,
    "is_home": 0.0,
    "is_favorite": 0.0,
    "blowout_risk": 0.15,
    "month": 11.0,
    "home_away_split": -0.06451612903225806,
}


def new_db():
    engine = create_engine("sqlite://")
    for model in (
        NBAGameLines,
        PlayerInjuryStatus,
        RecentGames,
        TeamDefenseStats,
        TeamRoster,
        TodayActivePlayers,
    ):
        model.__table__.create(engine)
    return sessionmaker(bind=engine)()


@pytest.fixture
def db():
    session = new_db()
    yield session
    session.close()


def row(pid, day, *, minutes=30.0, opponent=OPP, **stats):
    vals = dict(
        player_id=pid,
        game_date=day,
        opponent_team_id=opponent,
        points=20.0,
        minutes=minutes,
        rebounds=5.0,
        assists=4.0,
        fg_attempts=10.0,
        home_game=True,
    )
    vals.update(stats)
    return RecentGames(**vals)


def season(db):
    """Ten games, every other day before TARGET. P, STAR (36 min) and MID
    (20 min) play every game; BENCH plays 5 min, an opposing player is ignored."""
    for i in range(10):
        day = TARGET - timedelta(days=2 * (10 - i))
        db.add_all(
            [
                row(P, day, minutes=30.0),
                row(STAR, day, minutes=36.0, points=30.0, rebounds=8.0),
                row(MID, day, minutes=20.0),
                row(BENCH, day, minutes=5.0),
                row(99, day, minutes=40.0, opponent=OWN),
            ]
        )
    db.commit()


def tonight(db, *, out=(), doubtful=(), skip=()):
    """Serving state for TARGET: no box rows, active list and injury table."""
    for pid in (P, STAR, MID, BENCH):
        if pid in skip:
            continue
        db.add(
            TodayActivePlayers(
                player_id=pid,
                player_name=str(pid),
                team_id=OWN,
                team_name="own",
                opponent_team_id=OPP,
                opponent_team_name="opp",
                game_date=TARGET,
                is_home_game=True,
            )
        )
    for pid in out:
        db.add(PlayerInjuryStatus(player_id=pid, player_name=str(pid), status="out"))
    for pid in doubtful:
        db.add(
            PlayerInjuryStatus(player_id=pid, player_name=str(pid), status="doubtful")
        )
    db.commit()


def played_target(db, *, absent=()):
    """Box rows of the target game itself."""
    for pid in (P, STAR, MID, BENCH):
        if pid not in absent:
            db.add(row(pid, TARGET, minutes=30.0))
    db.commit()


def vector(db, **kw):
    return fe.build_features(db, P, TARGET, OPP, "points", **kw)


# ---- parity, leak -------------------------------------------------------------


def test_past_and_serving_paths_give_the_same_vector():
    past, serving = new_db(), new_db()
    season(past)
    played_target(past, absent=[STAR])
    season(serving)
    tonight(serving, out=[STAR])
    a, b = vector(past), vector(serving)
    assert _nan_equal(a, b)
    assert a["team_out_rotation_players"] == 1.0
    assert a["team_out_min_share"] > 0


def test_forced_sources_agree(db):
    season(db)
    played_target(db, absent=[STAR])
    tonight(db, out=[STAR])
    box = team_context(db, P, TARGET, OPP, source="box")
    status = team_context(db, P, TARGET, OPP, source="status")
    assert box == status == team_context(db, P, TARGET, OPP)


def test_target_game_stats_and_later_rows_do_not_leak(db):
    season(db)
    played_target(db, absent=[STAR])
    before = vector(db)
    for r in db.query(RecentGames).filter(RecentGames.game_date == TARGET):
        r.points, r.minutes, r.rebounds = 99.0, 48.0, 40.0
    for i in range(1, 4):
        db.add_all(
            row(pid, TARGET + timedelta(days=i), points=77.0) for pid in (P, STAR, MID)
        )
    db.commit()
    assert _nan_equal(vector(db), before)


# ---- availability weights --------------------------------------------------------


def test_star_out_raises_the_missing_shares(db):
    season(db)
    tonight(db)
    healthy = vector(db)
    db.add(PlayerInjuryStatus(player_id=STAR, player_name="s", status="ir"))
    db.commit()
    out = vector(db)
    assert healthy["team_out_min_share"] == 0
    for k in ("min", "fga", "reb", "ast"):
        assert out[f"team_out_{k}_share"] > healthy[f"team_out_{k}_share"]
    # STAR plays 36 of the 86 team minutes (P 30, MID 20, BENCH 5, STAR 36 = 91).
    assert out["team_out_min_share"] == pytest.approx(36 / 91)
    assert out["own_min_share"] == pytest.approx(30 / 91)


def test_doubtful_weighs_075_and_traded_teammate_counts_one(db):
    season(db)
    tonight(db, doubtful=[MID])
    ctx = team_context(db, P, TARGET, OPP)
    assert ctx["team_out_rotation_players"] == DOUBTFUL_WEIGHT == 0.75


def test_teammate_not_on_todays_roster_counts_one(db):
    season(db)
    tonight(db, skip=[STAR])  # traded: not on today's list, status healthy
    assert team_context(db, P, TARGET, OPP)["team_out_rotation_players"] == 1.0


def test_no_active_row_means_no_information(db):
    season(db)
    db.add(PlayerInjuryStatus(player_id=STAR, player_name="s", status="out"))
    db.commit()
    ctx = team_context(db, P, TARGET, OPP)
    assert ctx["team_out_min_share"] == 0 and ctx["own_min_share"] > 0


def test_empty_window_is_all_zero(db):
    assert set(team_context(db, P, TARGET, OPP).values()) == {0.0}


# ---- versions, samples -------------------------------------------------------------


def _v3_fixture(db):
    for i in range(12):
        db.add(
            RecentGames(
                player_id=7,
                game_date=OPENER + timedelta(days=2 * i),
                opponent_team_id=OPP,
                points=10.0 + i,
                minutes=24.0 + i % 4,
                rebounds=5.0 + i % 3,
                assists=3.0,
                fg_attempts=10.0 + i,
                three_pt_attempts=4.0,
                ft_attempts=3.0,
                turnovers=2.0,
                personal_fouls=2.0,
                home_game=i % 2 == 0,
            )
        )
    db.commit()


def test_version_3_is_unchanged_and_version_4_is_a_superset(db):
    _v3_fixture(db)
    day = date(2026, 11, 20)
    v3 = fe.build_features(db, 7, day, OPP, "points", version=3)
    assert v3.pop("low_sample") == 0
    assert v3.keys() == V3_BASELINE.keys()
    assert v3 == pytest.approx(V3_BASELINE)
    v4 = fe.build_features(db, 7, day, OPP, "points")
    assert fe.FEATURES_VERSION == 4
    assert v4.keys() > V3_BASELINE.keys()
    # v4 differs from v3 only in the game-line features: unknown is NaN, not 0 / 0.15
    # (train/serve parity, .factory/training/handoffs/training-to-nba-model.md).
    same = {k: v for k, v in V3_BASELINE.items() if k not in LINE_KEYS}
    assert {k: v4[k] for k in same} == pytest.approx(same)
    assert all(math.isnan(v4[k]) for k in LINE_KEYS)
    for k in (
        "team_out_min_share",
        "own_min_share",
        "exp_minutes",
        "starter_rate_10",
        "minutes_trend",
        "games_since_return",
    ):
        assert k in v4


def test_short_current_sample_borrows_last_season_and_is_flagged(db):
    for i in range(30):
        db.add(row(7, date(2026, 2, 1) + timedelta(days=i)))
    for i in range(2):
        db.add(row(7, OPENER + timedelta(days=2 * i)))
    db.commit()
    feats = fe.build_features(db, 7, date(2026, 11, 7), OPP, "points")
    assert feats is not None and feats["low_sample"] == 1
    assert feats["sample_games"] == 32
    # Expected minutes use the same borrowed sample, not 0.
    assert feats["exp_minutes"] > 0


def test_under_five_games_in_total_is_none(db):
    for i in range(4):
        db.add(row(7, OPENER + timedelta(days=2 * i)))
    db.commit()
    assert fe.build_features(db, 7, date(2026, 11, 7), OPP, "points") is None


def test_games_since_return_counts_across_a_gap(db):
    old = [OPENER + timedelta(days=2 * i) for i in range(4)]  # Oct 20-26
    new = [OPENER + timedelta(days=21 + 2 * i) for i in range(5)]  # gap of 15 days
    db.add_all(row(7, d) for d in old + new)
    db.commit()
    soon = new[-1] + timedelta(days=2)
    assert fe.build_features(db, 7, soon, OPP, "points")["games_since_return"] == 5
    later = new[-1] + timedelta(days=12)
    assert fe.build_features(db, 7, later, OPP, "points")["games_since_return"] == 0


def test_is_home_falls_back_to_the_box_row_then_todays_list(db):
    _v3_fixture(db)
    day = date(2026, 11, 20)
    # no box row, no line, no list: unknown is NaN (v4), never 0
    assert math.isnan(fe.build_features(db, 7, day, OPP, "points")["is_home"])
    assert fe.build_features(db, 7, day, OPP, "points", version=3)["is_home"] == 0
    db.add(
        TodayActivePlayers(
            player_id=7,
            player_name="7",
            team_id=OWN,
            team_name="o",
            opponent_team_id=OPP,
            opponent_team_name="p",
            game_date=day,
            is_home_game=True,
        )
    )
    db.commit()
    assert fe.build_features(db, 7, day, OPP, "points")["is_home"] == 1


# ---- model metadata --------------------------------------------------------------------


def test_features_version_reads_metadata_and_defaults_to_3(monkeypatch):
    monkeypatch.setattr(_ml_predict, "get_metadata", lambda stat=None: {})
    assert _ml_predict.features_version("points") == 3
    monkeypatch.setattr(
        _ml_predict, "get_metadata", lambda stat=None: {"features_version": 4}
    )
    assert _ml_predict.features_version("points") == 4


def test_trainer_metadata_records_the_feature_version():
    assert run_train_props._enrich_metadata("points", {})["features_version"] == 4
    kept = run_train_props._enrich_metadata("points", {"features_version": 3})
    assert kept["features_version"] == 3


def test_features_version_falls_back_to_the_feature_list(monkeypatch):
    monkeypatch.setattr(
        _ml_predict,
        "get_metadata",
        lambda stat=None: {"features": ["points_avg_5", "team_out_min_share"]},
    )
    assert _ml_predict.features_version("points") == 4


# ---- train/serve parity of the game-line features (training AC5) -------------------


def _nan_equal(a: dict, b: dict) -> bool:
    return a.keys() == b.keys() and all(
        (
            isinstance(x, float)
            and isinstance(y, float)
            and math.isnan(x)
            and math.isnan(y)
        )
        or x == pytest.approx(y)
        for x, y in ((a[k], b[k]) for k in a)
    )


def _line(db, total=225.5, spread_home=-6.5):
    db.add(
        NBAGameLines(
            game_date=TARGET,
            home_team_name="Own Home",
            away_team_name="Opp Away",
            spread_home=spread_home,
            spread_away=-spread_home if spread_home is not None else None,
            total=total,
        )
    )
    db.commit()


def _training_vector(db, monkeypatch):
    """The training path: build_training_dataset._build_chunk with NBA_ML_CONFIG."""
    from app.services.ml import build_training_dataset as btd
    from app.services.etl.nba.ml_training.config import NBA_ML_CONFIG

    monkeypatch.setattr(btd, "SessionLocal", lambda: _Shared(db))
    feats, targets, _keys = btd._build_chunk(
        NBA_ML_CONFIG, "points", [(P, TARGET, OPP, 21.0)], "t"
    )
    assert targets == [21.0]
    return feats[0]


class _Shared:
    """The fixture session, kept open when the builder closes its own."""

    def __init__(self, db):
        self._db = db

    def close(self):
        pass

    def __getattr__(self, name):
        return getattr(self._db, name)


def test_training_and_serving_give_the_same_vector_with_a_stored_line(
    monkeypatch,
):
    monkeypatch.setattr(
        fe, "_game_line_vs", lambda db, opp, day: (db.query(NBAGameLines).one(), True)
    )
    past, serving = new_db(), new_db()
    for db in (past, serving):
        season(db)
        _line(db)
    played_target(past, absent=[STAR])
    tonight(serving, out=[STAR])
    a = _training_vector(past, monkeypatch)
    b = fe.build_features(serving, P, TARGET, OPP, "points", version=4)
    assert _nan_equal(a, b)
    assert (a["spread"], a["total"], a["is_home"], a["is_favorite"]) == (
        -6.5,
        225.5,
        1,
        1,
    )


def test_no_stored_line_gives_nan_line_features_and_the_box_is_home(monkeypatch):
    past = new_db()
    season(past)
    played_target(past)
    past.query(RecentGames).filter_by(player_id=P, game_date=TARGET).update(
        {"home_game": False}
    )
    past.commit()
    a = _training_vector(past, monkeypatch)
    assert all(
        math.isnan(a[k]) for k in ("spread", "total", "is_favorite", "blowout_risk")
    )
    assert a["is_home"] == 0  # from the box row, not a 0 fill
    v3 = fe.build_features(past, P, TARGET, OPP, "points", version=3)
    assert (v3["spread"], v3["total"], v3["blowout_risk"]) == (0, 0, 0.15)


def _stub_model(monkeypatch, version):
    seen = {}

    class _Model:
        def predict(self, X):
            seen["X"] = X
            return np.array([1.0])

    meta = {"feature_names": ["spread", "points_avg_5"], "features_version": version}
    monkeypatch.setattr(_ml_predict, "_ensure_loaded", lambda stat: (_Model(), meta))
    monkeypatch.setattr(_ml_predict, "get_metadata", lambda stat=None: meta)
    return seen


def test_predict_keeps_nan_for_v4_models_and_zero_fills_v3(monkeypatch):
    seen = _stub_model(monkeypatch, 4)
    _ml_predict.predict("points", {"spread": float("nan")})
    assert seen["X"].isna().all().all()  # missing key and NaN both stay NaN
    seen = _stub_model(monkeypatch, 3)
    _ml_predict.predict("points", {"spread": float("nan")})
    assert (seen["X"].to_numpy() == 0).all()
