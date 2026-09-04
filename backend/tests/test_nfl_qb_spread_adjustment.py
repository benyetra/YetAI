from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.services.etl.nfl.nfl_common import get_current_nfl_week
from app.services.etl.nfl.qb_spread_adjustment import (
    QB_OUT_SPREAD_POINTS,
    qb_out_map_from_rows,
    qb_out_margin_adjustment,
    team_qb_is_out,
)
from app.services.etl.nfl.update_game_lines import GAME_LINES_HORIZON_DAYS
from app.services.etl.nfl.spread_projector import (
    projection_end_date,
    _project_spread_row,
)


def test_qb_out_margin_home_out_hurts_home():
    assert (
        qb_out_margin_adjustment(home_qb_out=True, away_qb_out=False)
        == -QB_OUT_SPREAD_POINTS
    )


def test_qb_out_margin_away_out_helps_home():
    assert (
        qb_out_margin_adjustment(home_qb_out=False, away_qb_out=True)
        == QB_OUT_SPREAD_POINTS
    )


def test_qb_out_margin_both_or_neither_is_zero():
    assert qb_out_margin_adjustment(home_qb_out=False, away_qb_out=False) == 0.0
    assert qb_out_margin_adjustment(home_qb_out=True, away_qb_out=True) == 0.0


def test_team_qb_is_out_from_status_and_backup_flag():
    assert team_qb_is_out({"injury_status": "Out", "is_backup": False}) is True
    assert team_qb_is_out({"injury_status": "IR", "is_backup": False}) is True
    assert team_qb_is_out({"injury_status": "Doubtful", "is_backup": False}) is True
    assert (
        team_qb_is_out({"injury_status": "Questionable", "is_backup": False}) is False
    )
    assert team_qb_is_out({"injury_status": "Healthy", "is_backup": True}) is True
    assert team_qb_is_out({"injury_status": "Healthy", "is_backup": False}) is False


def _qb_row(
    *,
    team_name: str,
    is_backup: bool,
    injury_status: str = "Healthy",
    prediction_date=None,
):
    return SimpleNamespace(
        team_name=team_name,
        feature_importance={"features": {"is_backup": float(is_backup)}},
        injury_status=injury_status,
        prediction_date=prediction_date,
    )


def test_qb_out_map_starter_only_is_false():
    rows = [
        _qb_row(
            team_name="Kansas City Chiefs", is_backup=False, injury_status="Healthy"
        ),
    ]
    assert qb_out_map_from_rows(rows) == {"Kansas City Chiefs": False}


def test_qb_out_map_backup_only_is_true():
    rows = [
        _qb_row(
            team_name="Kansas City Chiefs", is_backup=True, injury_status="Healthy"
        ),
    ]
    assert qb_out_map_from_rows(rows)["Kansas City Chiefs"] is True


def test_qb_out_map_later_healthy_starter_beats_leftover_backup():
    older = datetime(2026, 9, 8, 12, 0, 0)
    newer = datetime(2026, 9, 10, 12, 0, 0)
    rows = [
        _qb_row(
            team_name="Kansas City Chiefs",
            is_backup=True,
            injury_status="Healthy",
            prediction_date=older,
        ),
        _qb_row(
            team_name="Kansas City Chiefs",
            is_backup=False,
            injury_status="Healthy",
            prediction_date=newer,
        ),
    ]
    assert qb_out_map_from_rows(rows)["Kansas City Chiefs"] is False


def test_qb_out_map_later_backup_beats_leftover_starter():
    older = datetime(2026, 9, 8, 12, 0, 0)
    newer = datetime(2026, 9, 10, 12, 0, 0)
    rows = [
        _qb_row(
            team_name="Kansas City Chiefs",
            is_backup=False,
            injury_status="Healthy",
            prediction_date=older,
        ),
        _qb_row(
            team_name="Kansas City Chiefs",
            is_backup=True,
            injury_status="Healthy",
            prediction_date=newer,
        ),
    ]
    assert qb_out_map_from_rows(rows)["Kansas City Chiefs"] is True


def test_qb_out_map_same_date_backup_and_starter_is_out_either_order():
    ts = datetime(2026, 9, 10, 12, 0, 0)
    backup = _qb_row(
        team_name="Kansas City Chiefs",
        is_backup=True,
        injury_status="Healthy",
        prediction_date=ts,
    )
    starter = _qb_row(
        team_name="Kansas City Chiefs",
        is_backup=False,
        injury_status="Healthy",
        prediction_date=ts,
    )
    assert qb_out_map_from_rows([backup, starter])["Kansas City Chiefs"] is True
    assert qb_out_map_from_rows([starter, backup])["Kansas City Chiefs"] is True


def test_qb_out_map_dated_healthy_starter_beats_undated_leftover_backup():
    rows = [
        _qb_row(
            team_name="Kansas City Chiefs",
            is_backup=True,
            injury_status="Healthy",
            prediction_date=None,
        ),
        _qb_row(
            team_name="Kansas City Chiefs",
            is_backup=False,
            injury_status="Healthy",
            prediction_date=datetime(2026, 9, 10, 12, 0, 0),
        ),
    ]
    assert qb_out_map_from_rows(rows)["Kansas City Chiefs"] is False


def _spread_row_kwargs():
    return dict(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        elos={"Kansas City Chiefs": 1600.0, "Baltimore Ravens": 1400.0},
        ppg_stats={
            "Kansas City Chiefs": (24.0, 20.0),
            "Baltimore Ravens": (24.0, 20.0),
        },
    )


def test_current_week_game_receives_qb_out_flags():
    from app.services.etl.nfl.spread_projector import apply_qb_out_for_game

    season = 2026
    game_date = date(2026, 9, 13)
    loaded_week = get_current_nfl_week(season, today=game_date)
    qb_out = {"Kansas City Chiefs": True}
    home_out, away_out = apply_qb_out_for_game(
        game_date,
        loaded_week,
        season,
        qb_out,
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
    )
    assert (home_out, away_out) == (True, False)
    base = _project_spread_row(**_spread_row_kwargs())
    adj = _project_spread_row(
        **_spread_row_kwargs(), home_qb_out=home_out, away_qb_out=away_out
    )
    assert adj["projected_margin"] == pytest.approx(base["projected_margin"] - 3.5)


def test_next_week_game_does_not_receive_qb_out_flags():
    from app.services.etl.nfl.spread_projector import apply_qb_out_for_game

    season = 2026
    current_week_date = date(2026, 9, 13)
    next_week_date = date(2026, 9, 20)
    loaded_week = get_current_nfl_week(season, today=current_week_date)
    assert get_current_nfl_week(season, today=next_week_date) == loaded_week + 1
    qb_out = {"Kansas City Chiefs": True}
    home_out, away_out = apply_qb_out_for_game(
        next_week_date,
        loaded_week,
        season,
        qb_out,
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
    )
    assert (home_out, away_out) == (False, False)
    base = _project_spread_row(**_spread_row_kwargs())
    gated = _project_spread_row(
        **_spread_row_kwargs(), home_qb_out=home_out, away_qb_out=away_out
    )
    assert gated["projected_margin"] == pytest.approx(base["projected_margin"])


def test_projection_end_date_matches_game_lines_horizon():
    today = date(2026, 9, 9)
    end = projection_end_date(today)
    assert (end - today).days == GAME_LINES_HORIZON_DAYS
    assert GAME_LINES_HORIZON_DAYS >= 10


def test_spread_row_applies_home_qb_out():
    base = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        elos={"Kansas City Chiefs": 1600.0, "Baltimore Ravens": 1400.0},
        ppg_stats={
            "Kansas City Chiefs": (24.0, 20.0),
            "Baltimore Ravens": (24.0, 20.0),
        },
    )
    adj = _project_spread_row(
        home_team_name="Kansas City Chiefs",
        away_team_name="Baltimore Ravens",
        spread_home=-3.0,
        elos={"Kansas City Chiefs": 1600.0, "Baltimore Ravens": 1400.0},
        ppg_stats={
            "Kansas City Chiefs": (24.0, 20.0),
            "Baltimore Ravens": (24.0, 20.0),
        },
        home_qb_out=True,
    )
    assert adj["projected_margin"] == pytest.approx(base["projected_margin"] - 3.5)
