from datetime import date

import pytest

from app.services.etl.nfl.qb_spread_adjustment import (
    QB_OUT_SPREAD_POINTS,
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
