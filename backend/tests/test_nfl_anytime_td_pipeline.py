"""NFL anytime-TD pipeline: phase membership + actuals/scheme pure helpers."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.services.etl.nfl.anytime_td_actuals import (
    aggregate_player_td_count,
    build_actual_upsert_row,
    grade_correct_prediction,
    player_scored_anytime_td,
    run as run_actuals,
)
from app.services.etl.nfl.scheme_loader import yaml_entry_to_db_row
from app.services.etl.nfl.sync_defense_schemes import run as run_sync_schemes
from app.tasks.etl_pipeline import NFL_PHASES

EXPECTED_PHASE_ORDER = [
    "actuals",
    "game_lines",
    "game_projections",
    "anytime_td",
    "predictions",
]

ANYTIME_TD_ACTUALS_TASK = "app.tasks.etl_pipeline.nfl.anytime_td_actuals"
SYNC_DEFENSE_SCHEMES_TASK = "app.tasks.etl_pipeline.nfl.sync_defense_schemes"
ANYTIME_TD_PROJECTOR_TASK = "app.tasks.etl_pipeline.nfl.anytime_td_projector"
ANYTIME_TD_BETTING_TASK = "app.tasks.etl_pipeline.nfl.anytime_td_betting"


def _phase_task_names(phase: str) -> list[str]:
    return [
        t.name for phase_name, tasks in NFL_PHASES if phase_name == phase for t in tasks
    ]


def test_nfl_phases_include_anytime_td_phase():
    names = [phase for phase, _ in NFL_PHASES]
    assert names == EXPECTED_PHASE_ORDER


def test_nfl_phases_actuals_include_anytime_td_actuals():
    assert ANYTIME_TD_ACTUALS_TASK in _phase_task_names("actuals")


def test_nfl_phases_anytime_td_tasks_order():
    tasks = _phase_task_names("anytime_td")
    assert tasks == [
        SYNC_DEFENSE_SCHEMES_TASK,
        ANYTIME_TD_PROJECTOR_TASK,
        ANYTIME_TD_BETTING_TASK,
    ]


def test_player_scored_anytime_td():
    assert player_scored_anytime_td(0) is False
    assert player_scored_anytime_td(1) is True
    assert player_scored_anytime_td(3) is True


def test_aggregate_player_td_count_sums_rush_and_receiving_only():
    stat = {
        "passing_tds": 2,
        "rushing_tds": 1,
        "receiving_tds": 0,
    }
    assert aggregate_player_td_count(stat) == 1


def test_aggregate_player_td_count_qb_passing_only_is_zero():
    stat = {
        "passing_tds": 3,
        "rushing_tds": 0,
        "receiving_tds": 0,
    }
    assert aggregate_player_td_count(stat) == 0
    assert player_scored_anytime_td(aggregate_player_td_count(stat)) is False


def test_grade_correct_prediction_threshold():
    assert grade_correct_prediction(scored=True, td_probability=0.6) is True
    assert grade_correct_prediction(scored=False, td_probability=0.6) is False
    assert grade_correct_prediction(scored=True, td_probability=0.4) is False


def test_grade_correct_prediction_over_recommendation():
    assert (
        grade_correct_prediction(
            scored=True,
            td_probability=0.55,
            recommendation="OVER",
        )
        is True
    )
    assert (
        grade_correct_prediction(
            scored=False,
            td_probability=0.55,
            recommendation="OVER",
        )
        is False
    )


def test_grade_correct_prediction_no_play_is_none():
    assert (
        grade_correct_prediction(
            scored=True,
            td_probability=0.55,
            recommendation="NO_PLAY",
        )
        is None
    )


def test_build_actual_upsert_row_with_prediction():
    now = datetime(2025, 10, 8, 12, 0, 0)
    player_stat = {
        "player_id": "p1",
        "player_name": "Travis Kelce",
        "position": "TE",
        "team_name": "Kansas City Chiefs",
        "opponent_team_name": "Buffalo Bills",
        "game_date": date(2025, 10, 6),
        "passing_tds": 0,
        "rushing_tds": 0,
        "receiving_tds": 1,
    }
    prediction = MagicMock(
        td_probability=0.42,
        expected_tds=0.35,
        recommendation="NO_PLAY",
    )
    row = build_actual_upsert_row(
        player_stat,
        season=2025,
        week=5,
        prediction=prediction,
        now=now,
    )
    assert row["season"] == 2025
    assert row["week"] == 5
    assert row["player_id"] == "p1"
    assert row["scored_anytime_td"] is True
    assert row["actual_td_count"] == 1
    assert row["predicted_td_probability"] == 0.42
    assert row["expected_tds"] == 0.35
    assert row["correct_prediction"] is None
    assert row["created_at"] == now


def test_yaml_entry_to_db_row_encodes_tags():
    row = yaml_entry_to_db_row(
        "KC",
        {
            "cover_base": "cover_3",
            "man_zone_lean": "zone",
            "pressure_lean": "high",
            "as_of": "2026-08-01",
        },
        season=2026,
    )
    assert row["team_name"] == "Kansas City Chiefs"
    assert row["season"] == 2026
    assert row["week"] == 0
    assert row["cover_base"] == 3
    assert row["man_zone_lean"] == 0.0
    assert row["pressure_lean"] == 0.75
    assert row["source"] == "yaml"


def test_run_actuals_with_injected_stats_upserts():
    stats = [
        {
            "player_id": "p1",
            "player_name": "Player One",
            "position": "RB",
            "team_name": "Kansas City Chiefs",
            "opponent_team_name": "Buffalo Bills",
            "game_date": date(2025, 10, 6),
            "passing_tds": 0,
            "rushing_tds": 1,
            "receiving_tds": 0,
        }
    ]
    mock_pred = MagicMock(
        player_id="p1",
        td_probability=0.55,
        expected_tds=0.5,
        recommendation="OVER",
    )
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value.filter_by.return_value.all.return_value = [mock_pred]

    with (
        patch(
            "app.services.etl.nfl.anytime_td_actuals.SessionLocal",
            return_value=mock_db,
        ),
        patch("app.services.etl.nfl.anytime_td_actuals.upsert_many") as um,
    ):
        um.return_value = 1
        result = run_actuals(season=2025, week=5, player_stats=stats)

    assert result["status"] == "ok"
    assert result["actuals"] == 1
    um.assert_called_once()
    rows = um.call_args[0][2]
    assert rows[0]["correct_prediction"] is True


def test_run_sync_schemes_delegates_to_loader():
    with patch(
        "app.services.etl.nfl.sync_defense_schemes.upsert_schemes_from_yaml",
        return_value={"status": "ok", "upserted": 32},
    ) as upsert:
        result = run_sync_schemes(season=2026)

    upsert.assert_called_once_with(season=2026, week=0)
    assert result["upserted"] == 32
