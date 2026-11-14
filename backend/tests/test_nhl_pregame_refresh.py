"""NHL pregame goalie refresh: scheduled, switchable off, goalies-only."""

from unittest.mock import patch

from app.celery_app import celery_app
from app.data.celery_tasks import ADMIN_FIREABLE_TASKS, PIPELINE_ENQUEUE_CATALOG
from app.services.etl.nhl import daily_predictions as dp
from app.tasks import etl_pipeline as ep


def test_beat_entry_at_1645():
    entry = celery_app.conf.beat_schedule["nhl-pregame-refresh"]
    assert entry["task"] == ep.run_nhl_pregame_refresh.name
    assert (entry["schedule"].hour, entry["schedule"].minute) == ({16}, {45})
    assert entry["options"]["expires"] == 3600
    assert "nhl-update-pipeline-daily" in celery_app.conf.beat_schedule


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("NHL_PREGAME_REFRESH_ENABLED", "0")
    assert ep.run_nhl_pregame_refresh.run() == {"status": "disabled"}


def test_phases_are_goalie_only():
    names = [t.name for _, tasks in ep.NHL_PREGAME_PHASES for t in tasks]
    assert names == ["app.tasks.etl_pipeline.nhl.goalie_pregame_refresh"]


def test_catalog_rows():
    assert ADMIN_FIREABLE_TASKS[ep.nhl_goalie_pregame_refresh.name] == 600.0
    row = next(
        r
        for r in PIPELINE_ENQUEUE_CATALOG
        if r["task_name"] == ep.run_nhl_pregame_refresh.name
    )
    assert row["label"] == "NHL pregame goalie refresh" and row["sport"] == "nhl"
    assert "NHL_PREGAME_REFRESH_ENABLED" in row["description"]
    assert "credits" in row["description"]


def test_run_goalie_refresh_keeps_only_unstarted_games_and_saves_market():
    sched = {
        "gameWeek": [
            {
                "games": [
                    {
                        "id": 1,
                        "gameState": "FUT",
                        "startTimeUTC": "2026-11-13T23:00:00Z",
                    },
                    {
                        "id": 2,
                        "gameState": "LIVE",
                        "startTimeUTC": "2026-11-13T23:00:00Z",
                    },
                    {
                        "id": 3,
                        "gameState": "PRE",
                        "startTimeUTC": "2026-11-13T23:30:00Z",
                    },
                    {
                        "id": 4,
                        "gameState": "FUT",
                        "startTimeUTC": "2026-11-14T23:00:00Z",
                    },
                ]
            }
        ]
    }
    from datetime import date

    with (
        patch.object(dp, "now_eastern") as now,
        patch.object(dp.NHLAPIClient, "get_schedule", return_value=sched),
        patch.object(dp, "get_nhl_events_from_odds_api", return_value=[]),
        patch.object(dp, "generate_goalie_predictions", return_value=2) as gen,
        patch.object(dp, "generate_player_predictions", return_value=3),
        patch.object(dp, "generate_team_totals_predictions", return_value=1),
        patch("app.services.etl.nhl._db.init_session"),
        patch("app.services.etl.nhl._db.close_session"),
    ):
        now.return_value.date.return_value = date(2026, 11, 13)
        out = dp.run_goalie_refresh()
    games = gen.call_args.args[0]
    assert [g["id"] for g in games] == [1, 3]
    assert gen.call_args.kwargs == {}
    assert out["goalie_predictions"] == 2 and out["status"] == "ok"
    assert out["player_predictions"] == 3 and out["team_totals_predictions"] == 1
