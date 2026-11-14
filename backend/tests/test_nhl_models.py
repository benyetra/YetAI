"""NHL projections are the formulas the 2026-27 backtest supports, looked up by team id."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    NHLGoalie,
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLPlayer,
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
    NHLTeamStats,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services.etl.nhl import _config
from app.services.etl.nhl import betting_edges as be
from app.services.etl.nhl import goalie_saves_model as gsm
from app.services.etl.nhl import player_shots_model as psm
from app.services.etl.nhl import team_totals_model as ttm
from app.services.etl.nhl.goalie_saves_ml import enrich_goalie_prediction_for_write
from app.services.etl.nhl.ml_training import (
    build_goalie_dataset,
    build_player_shots_dataset,
    build_team_totals_dataset,
)
from app.services.etl.nhl.player_shots_ml import (
    enrich_player_shots_prediction_for_write,
)
from app.services.etl.nhl.team_totals_ml import enrich_team_totals_prediction_for_write

D = date(2026, 11, 13)
RANGERS, ISLANDERS, VAN, UTAH, EMPTY = 3, 2, 23, 68, 99
# id, name, gp, GF, GA, SF, SA  (EMPTY: no current games, NULL rates)
TEAMS = [
    (RANGERS, "New York", 10, 3.4, 2.6, 32.0, 28.0),
    (ISLANDERS, "New York", 10, 2.6, 3.0, 28.0, 31.0),
    (VAN, "Vancouver", 10, 3.0, 3.0, 30.0, 30.0),
    (UTAH, "Utah", 10, 3.0, 3.4, 30.0, 31.0),
]
LEAGUE_GF = (3.4 + 2.6 + 3.0 + 3.0) / 4
LEAGUE_SF = (32.0 + 28.0 + 30.0 + 30.0) / 4


@pytest.fixture
def db(monkeypatch):
    eng = create_engine("sqlite://")
    for m in (
        NHLTeamStats,
        NHLPlayer,
        NHLGoalie,
        NHLGoalieActuals,
        NHLGoaliePredictions,
        NHLPlayerShotsActuals,
        NHLPlayerShotsPredictions,
        NHLTeamTotalsActuals,
        NHLTeamTotalsPredictions,
    ):
        m.__table__.create(eng)
    session = sessionmaker(bind=eng)()
    for tid, name, gp, gf, ga, sf, sa in TEAMS:
        session.add(
            NHLTeamStats(
                team_id=tid,
                team_name=name,
                games_played=gp,
                goals_for_per_game=gf,
                goals_against_per_game=ga,
                shots_for_per_game=sf,
                shots_against_per_game=sa,
            )
        )
    session.add(NHLTeamStats(team_id=EMPTY, team_name="Empty", games_played=0))
    session.add_all(
        [
            NHLGoalie(
                player_id=1,
                name="G One",
                team_id=RANGERS,
                team_name="New York",
                games_played=10,
                saves=270,
                shots_against=300,
            ),
            NHLGoalie(
                player_id=2,
                name="G Two",
                team_id=ISLANDERS,
                team_name="New York",
                games_played=7,
                saves=180,
                shots_against=200,
            ),
            NHLGoalie(  # no games: not in the league save pct
                player_id=3,
                name="G Three",
                team_id=VAN,
                team_name="Vancouver",
                games_played=0,
                saves=0,
                shots_against=0,
            ),
        ]
    )
    session.add_all(
        [
            NHLPlayer(
                player_id=7,
                name="Q Player",
                team_id=RANGERS,
                team_name="New York",
                position="D",
                games_played=25,
                shots_per_game=2.345,
                toi_per_game=1300,
            ),
            NHLPlayer(
                player_id=8,
                name="No Games",
                team_id=RANGERS,
                team_name="New York",
                position="C",
                games_played=0,
                shots_per_game=3.0,
            ),
        ]
    )
    session.commit()
    for mod in (_config, gsm, psm, ttm):
        monkeypatch.setattr(mod, "db_session", session)
    return session


def test_totals_formula_uses_team_rows_by_id(db):
    out = ttm.predict_team_total_goals(RANGERS, ISLANDERS, D)
    home = 3.4 * 3.0 / LEAGUE_GF  # GF_home * GA_away / L
    away = 2.6 * 2.6 / LEAGUE_GF  # GF_away * GA_home / L
    assert out["predicted_home_goals"] == round(home, 2)
    assert out["predicted_away_goals"] == round(away, 2)
    assert out["predicted_total_goals"] == round(home + away, 2)
    assert out["suggested_ou_line"] == round((home + away) * 2) / 2
    assert out["league_goals_per_game"] == pytest.approx(LEAGUE_GF)
    assert out["confidence"] == 65  # 10 games


def test_two_new_york_teams_get_different_projections(db):
    rangers = ttm.predict_team_total_goals(RANGERS, VAN)
    islanders = ttm.predict_team_total_goals(ISLANDERS, VAN)
    assert rangers["predicted_home_goals"] != islanders["predicted_home_goals"]
    g_rangers = gsm.predict_goalie_saves(1, "G One", RANGERS, VAN)
    g_islanders = gsm.predict_goalie_saves(2, "G Two", ISLANDERS, VAN)
    assert (
        g_rangers["predicted_shots_against"] != g_islanders["predicted_shots_against"]
    )


def test_totals_team_without_games_errors(db):
    assert "error" in ttm.predict_team_total_goals(EMPTY, VAN)
    assert "error" in ttm.predict_team_total_goals(VAN, EMPTY)
    assert "error" in ttm.predict_team_total_goals(VAN, 12345)  # missing row


def test_shots_is_the_stored_rate_and_nothing_else(db):
    base = psm.predict_player_shots(7, opponent_team_id=VAN, is_home=True)
    assert base["predicted_shots"] == base["baseline_shots"] == 2.35
    assert base["player_name"] == "Q Player"
    assert base["player_position"] == "D" and base["games_played"] == 25
    assert base["player_toi_per_game"] == 1300 and base["confidence"] == 75
    # opponent, venue and position do not change the number
    away = psm.predict_player_shots(7, opponent_team_id=RANGERS, is_home=False)
    assert away["predicted_shots"] == 2.35


def test_shots_errors(db):
    assert "error" in psm.predict_player_shots(999)
    assert "error" in psm.predict_player_shots(8)  # games_played 0


def test_goalie_formula_league_save_pct(db):
    assert gsm.get_league_save_pct() == pytest.approx(450 / 500)
    out = gsm.predict_goalie_saves(1, "G One", RANGERS, ISLANDERS, D, is_home=True)
    shots = 28.0 * 28.0 / LEAGUE_SF  # opp SF * own SA / league SF
    assert out["predicted_shots_against"] == pytest.approx(shots)
    assert out["predicted_save_pct"] == pytest.approx(0.9)
    assert out["predicted_saves"] == round(shots * 0.9, 2)
    assert out["goalie_season_sv_pct"] == 0.9  # his own 270/300, informational
    assert out["opponent_shots_avg"] == 28.0 and out["is_home"] is True
    assert out["confidence"] == 65


def test_goalie_save_pct_fallback_and_errors(db):
    db.query(NHLGoalie).delete()
    db.commit()
    assert gsm.get_league_save_pct() == 0.900
    assert "error" in gsm.predict_goalie_saves(1, "G", RANGERS, 12345)
    assert "error" in gsm.predict_goalie_saves(1, "G", EMPTY, RANGERS)  # NULL rates
    ok = gsm.predict_goalie_saves(1, "G", RANGERS, ISLANDERS)  # goalie row gone
    assert ok["goalie_season_sv_pct"] is None


def test_written_value_equals_model_goalie(db):
    pred = gsm.predict_goalie_saves(1, "G One", RANGERS, ISLANDERS, D)
    write = enrich_goalie_prediction_for_write(pred, {}, saves_line=24.5)
    assert write["predicted_saves"] == pred["predicted_saves"]
    assert write["model_version"] == "heuristic-v2"


def test_written_value_equals_model_shots(db):
    pred = psm.predict_player_shots(7, VAN)
    write = enrich_player_shots_prediction_for_write(pred, shots_line=2.5)
    assert write["predicted_shots"] == pred["predicted_shots"]
    assert write["model_version"] == "heuristic-v2"


def test_written_value_equals_model_totals(db):
    pred = ttm.predict_team_total_goals(RANGERS, ISLANDERS, D)
    write = enrich_team_totals_prediction_for_write(pred, draftkings_ou_line=5.5)
    assert write["predicted_total_goals"] == pred["predicted_total_goals"]
    assert write["model_version"] == "heuristic-v2"


@pytest.mark.parametrize(
    "fn,edge,line",
    [
        (be.recommendation_for_saves, be.SAVES_CALL_EDGE, 24.5),
        (be.recommendation_for_shots, be.SHOTS_CALL_EDGE, 2.5),
        (be.recommendation_for_total_goals, be.TOTALS_CALL_EDGE, 5.5),
    ],
)
def test_call_thresholds_and_no_edge_tier(fn, edge, line):
    assert (be.SAVES_CALL_EDGE, be.SHOTS_CALL_EDGE, be.TOTALS_CALL_EDGE) == (
        1.5,
        0.5,
        0.25,
    )
    over = fn(line + edge, line)
    under = fn(line - edge, line)
    assert over.recommendation == f"OVER {line}" and under.recommendation == (
        f"UNDER {line}"
    )
    assert fn(line + edge - 0.01, line).recommendation == "PASS"
    assert fn(line + 5, line).edge_category is None
    none = fn(line + 5, None)
    assert none.recommendation == "PASS" and none.edge_category is None
    assert none.edge_value is None


def _builder_db(monkeypatch, module, tables, rows):
    eng = create_engine("sqlite://")
    for t in tables:
        t.__table__.create(eng)
    session = sessionmaker(bind=eng)()
    session.add_all(rows)
    session.commit()
    monkeypatch.setattr(module, "SessionLocal", lambda: session)


@pytest.mark.parametrize(
    "version,kept", [("heuristic-v2", 1), ("heuristic-v1", 0), (None, 0)]
)
def test_goalie_builder_skips_pre_repair_rows(monkeypatch, version, kept):
    _builder_db(
        monkeypatch,
        build_goalie_dataset,
        (NHLGoalieActuals, NHLGoaliePredictions),
        [
            NHLGoalieActuals(
                game_id=1,
                game_date=D,
                goalie_id=1,
                goalie_name="G",
                team_name="A",
                opponent_team_name="B",
                actual_saves=25,
                actual_shots_against=28,
                actual_save_pct=0.89,
                actual_goals_against=3,
            ),
            NHLGoaliePredictions(
                game_date=D,
                goalie_id=1,
                goalie_name="G",
                team_id=1,
                team_name="A",
                opponent_team_id=2,
                opponent_team_name="B",
                predicted_saves=24.0,
                predicted_shots_against=27.0,
                predicted_save_pct=0.9,
                model_version=version,
            ),
        ],
    )
    df, y = build_goalie_dataset.build(D, D)
    assert len(y) == kept


@pytest.mark.parametrize(
    "version,kept", [("heuristic-v2", 1), ("heuristic-v1", 0), (None, 0)]
)
def test_shots_builder_skips_pre_repair_rows(monkeypatch, version, kept):
    _builder_db(
        monkeypatch,
        build_player_shots_dataset,
        (NHLPlayerShotsActuals, NHLPlayerShotsPredictions),
        [
            NHLPlayerShotsActuals(
                game_id=1,
                game_date=D,
                player_id=7,
                player_name="P",
                team_name="A",
                actual_shots=3,
            ),
            NHLPlayerShotsPredictions(
                game_date=D,
                player_id=7,
                player_name="P",
                team_name="A",
                opponent_team_name="B",
                predicted_shots=2.5,
                model_version=version,
            ),
        ],
    )
    df, y = build_player_shots_dataset.build(D, D)
    assert len(y) == kept


@pytest.mark.parametrize(
    "version,kept", [("heuristic-v2", 1), ("heuristic-v1", 0), (None, 0)]
)
def test_totals_builder_skips_pre_repair_rows(monkeypatch, version, kept):
    _builder_db(
        monkeypatch,
        build_team_totals_dataset,
        (NHLTeamTotalsActuals, NHLTeamTotalsPredictions),
        [
            NHLTeamTotalsActuals(
                game_id=1,
                game_date=D,
                home_team_id=1,
                home_team_name="A",
                away_team_id=2,
                away_team_name="B",
                actual_home_goals=3,
                actual_away_goals=2,
                actual_total_goals=5,
            ),
            NHLTeamTotalsPredictions(
                game_date=D,
                home_team_id=1,
                home_team_name="A",
                away_team_id=2,
                away_team_name="B",
                predicted_home_goals=3.0,
                predicted_away_goals=2.8,
                predicted_total_goals=5.8,
                suggested_ou_line=6.0,
                model_version=version,
            ),
        ],
    )
    df, y = build_team_totals_dataset.build(D, D)
    assert len(y) == kept
