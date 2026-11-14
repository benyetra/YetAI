"""Unit tests for QB actuals PBP fallback helpers."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pandas as pd

from app.services.etl.nfl.backfill_qb_actuals import (
    _normalize_name,
    _weekly_qb_rows,
    _weekly_qb_rows_from_pbp,
)


def test_normalize_name_strips_punctuation():
    assert _normalize_name("J. Allen") == "j allen"
    assert _normalize_name("  Patrick  Mahomes ") == "patrick mahomes"


def test_weekly_qb_rows_falls_back_when_weekly_empty():
    with patch(
        "app.services.etl.nfl.backfill_qb_actuals._weekly_qb_rows_from_pbp"
    ) as pbp:
        pbp.return_value = [
            {
                "qb_player_id": "00-1",
                "qb_player_name": "Test QB",
                "team_name": "BUF",
                "opponent_team_name": "MIA",
                "venue_name": "Stadium",
                "game_date": date(2025, 9, 7),
                "season": 2025,
                "week": 1,
                "actual_passing_yards": 250.0,
                "actual_attempts": 30,
                "actual_completions": 20,
                "actual_touchdowns": 2,
                "actual_interceptions": 0,
                "actual_completion_pct": 66.7,
                "actual_yards_per_attempt": 8.3,
                "actual_passer_rating": 0.0,
                "epa_per_play": 0.1,
                "cpoe": None,
                "air_yards_per_attempt": None,
            }
        ]
        out = _weekly_qb_rows(2025, 1, weekly=pd.DataFrame(), schedules=None)
        assert len(out) == 1
        assert out[0]["qb_player_name"] == "Test QB"
        pbp.assert_called_once()


def test_weekly_qb_rows_from_pbp_filters_low_attempts():
    pbp = pd.DataFrame(
        [
            {
                "season_type": "REG",
                "week": 1,
                "play_type": "pass",
                "passer_player_id": "00-1",
                "passer_player_name": "A. Starter",
                "posteam": "BUF",
                "passing_yards": 20.0,
                "complete_pass": 1,
                "pass_attempt": 1,
                "pass_touchdown": 0,
                "interception": 0,
                "epa": 0.1,
            }
            for _ in range(3)  # only 3 attempts → filtered
        ]
        + [
            {
                "season_type": "REG",
                "week": 1,
                "play_type": "pass",
                "passer_player_id": "00-2",
                "passer_player_name": "B. Volume",
                "posteam": "KC",
                "passing_yards": 12.0,
                "complete_pass": 1,
                "pass_attempt": 1,
                "pass_touchdown": 0,
                "interception": 0,
                "epa": 0.2,
            }
            for _ in range(10)
        ]
    )
    schedules = pd.DataFrame(
        [
            {
                "week": 1,
                "game_type": "REG",
                "home_team": "KC",
                "away_team": "BAL",
                "gameday": "2025-09-07",
                "stadium": "Arrowhead",
            },
            {
                "week": 1,
                "game_type": "REG",
                "home_team": "BUF",
                "away_team": "MIA",
                "gameday": "2025-09-07",
                "stadium": "Highmark",
            },
        ]
    )
    with patch("app.services.etl.nfl.backfill_qb_actuals.nfl") as nfl_mod:
        nfl_mod.import_pbp_data.return_value = pbp
        nfl_mod.import_schedules.return_value = schedules
        rows = _weekly_qb_rows_from_pbp(2025, 1)
    assert len(rows) == 1
    assert rows[0]["qb_player_name"] == "B. Volume"
    assert rows[0]["actual_attempts"] == 10
    assert rows[0]["actual_passing_yards"] == 120.0


def _actual_row(yards: float) -> dict:
    return {
        "qb_player_id": "00-1",
        "qb_player_name": "Test QB",
        "team_name": "BUF",
        "opponent_team_name": "MIA",
        "venue_name": "Stadium",
        "game_date": date(2025, 9, 7),
        "actual_passing_yards": yards,
        "actual_attempts": 30,
        "actual_completions": 20,
        "actual_touchdowns": 2,
        "actual_interceptions": 0,
        "actual_completion_pct": 66.7,
        "actual_yards_per_attempt": 8.3,
        "actual_passer_rating": 0.0,
    }


def test_upsert_qb_actuals_corrects_an_existing_partial_row():
    """H-8 / NFL-6: an existing row is updated, not skipped."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.services.etl.nfl import backfill_qb_actuals as mod

    existing = SimpleNamespace(actual_passing_yards=10.0)
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = existing
    with (
        patch.object(mod, "db_session", session),
        patch.object(mod, "_weekly_qb_rows", return_value=[_actual_row(280.0)]),
        patch.object(mod, "_find_prediction", return_value=None),
        patch.object(
            mod,
            "predict_qb_passing_yards",
            return_value={"predicted_passing_yards": 250.0},
        ),
    ):
        out = mod.upsert_qb_actuals_for_week(2025, 1)

    assert out["updated"] == 1 and out["inserted"] == 0
    assert existing.actual_passing_yards == 280.0
    session.add.assert_not_called()


def test_upsert_qb_actuals_inserts_when_missing():
    from unittest.mock import MagicMock

    from app.services.etl.nfl import backfill_qb_actuals as mod

    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None
    with (
        patch.object(mod, "db_session", session),
        patch.object(mod, "_weekly_qb_rows", return_value=[_actual_row(280.0)]),
        patch.object(mod, "_find_prediction", return_value=None),
        patch.object(
            mod,
            "predict_qb_passing_yards",
            return_value={"predicted_passing_yards": 250.0},
        ),
    ):
        out = mod.upsert_qb_actuals_for_week(2025, 1)

    assert out["inserted"] == 1
    assert session.add.call_args[0][0].actual_passing_yards == 280.0


def test_qb_collector_grades_current_and_previous_week():
    """H-8 / NFL-6: weeks N-1 and N are both graded each run."""
    from app.services.etl.nfl import collect_qb_actuals as mod

    calls = []
    with (
        patch.object(mod, "get_nfl_season", return_value=2025),
        patch.object(mod, "get_current_nfl_week", return_value=10),
        patch(
            "app.services.etl.nfl.backfill_qb_actuals.upsert_qb_actuals_for_week",
            side_effect=lambda s, w: calls.append((s, w)) or {"inserted": 1},
        ),
    ):
        stats = mod._run_qb_actuals_core()

    assert calls == [(2025, 9), (2025, 10)]
    assert stats["inserted"] == len(calls)
