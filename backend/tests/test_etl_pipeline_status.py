"""Pipeline orchestrator status semantics (no broker required)."""

from unittest.mock import MagicMock

from app.tasks.etl_pipeline import CRITICAL_PIPELINE_TASKS, _run_phases


def test_run_phases_ok_when_all_tasks_succeed():
    task = MagicMock()
    task.name = "app.tasks.etl_pipeline.mlb.weather"
    task.run.return_value = {"status": "ok"}

    result = _run_phases("mlb", [("enrichment", [task])])

    assert result["status"] == "ok"
    assert result["failed_tasks"] == []
    assert result["phases"][0]["status"] == "ok"
    assert result["phases"][0]["results"][0]["critical"] is False


def test_run_phases_partial_failure_on_any_error():
    ok = MagicMock()
    ok.name = "app.tasks.etl_pipeline.mlb.weather"
    ok.run.return_value = {"status": "ok"}

    bad = MagicMock()
    bad.name = "app.tasks.etl_pipeline.mlb.strikeouts"
    bad.run.side_effect = RuntimeError("statsapi down")

    result = _run_phases("mlb", [("props", [ok, bad])])

    assert result["status"] == "partial_failure"
    assert bad.name in result["failed_tasks"]
    assert bad.name in result["critical_failed_tasks"]
    assert result["phases"][0]["status"] == "error"
    assert result["phases"][0]["errors"] == 1
    assert result["phases"][0]["results"][1]["critical"] is True
    assert "error" in result["phases"][0]["results"][1]


def test_critical_tasks_include_mlb_strikeouts():
    assert "app.tasks.etl_pipeline.mlb.strikeouts" in CRITICAL_PIPELINE_TASKS


def test_critical_tasks_include_nba_totals():
    assert "app.tasks.etl_pipeline.nba.totals_projector" in CRITICAL_PIPELINE_TASKS
