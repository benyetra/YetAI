"""Admin Celery catalog registration for NFL anytime TD."""

from app.data.celery_tasks import (
    ADMIN_ENQUEUE_TASKS,
    ADMIN_FIREABLE_TASKS,
    FIREABLE_CATALOG,
    PIPELINE_ENQUEUE_CATALOG,
)
from app.tasks.etl_pipeline import NFL_ANYTIME_TD_PHASES


_ANYTIME_TD_ORCH = "app.tasks.etl_pipeline.run_nfl_anytime_td_pipeline"
_ANYTIME_TD_LEAF = (
    "app.tasks.etl_pipeline.nfl.sync_defense_schemes",
    "app.tasks.etl_pipeline.nfl.anytime_td_projector",
    "app.tasks.etl_pipeline.nfl.anytime_td_betting",
    "app.tasks.etl_pipeline.nfl.anytime_td_actuals",
)


def test_anytime_td_orchestrator_in_pipeline_catalog():
    names = {e["task_name"] for e in PIPELINE_ENQUEUE_CATALOG}
    assert _ANYTIME_TD_ORCH in names
    assert _ANYTIME_TD_ORCH in ADMIN_ENQUEUE_TASKS
    entry = next(
        e for e in PIPELINE_ENQUEUE_CATALOG if e["task_name"] == _ANYTIME_TD_ORCH
    )
    assert entry["sport"] == "nfl"
    assert "anytime" in entry["label"].lower()


def test_anytime_td_leaf_tasks_fireable():
    fireable_names = {e["task_name"] for e in FIREABLE_CATALOG}
    for name in _ANYTIME_TD_LEAF:
        assert name in ADMIN_FIREABLE_TASKS
        assert name in fireable_names
        assert name in ADMIN_ENQUEUE_TASKS


def test_anytime_td_pipeline_phases():
    phase_names = [p for p, _ in NFL_ANYTIME_TD_PHASES]
    assert phase_names == ["actuals", "anytime_td"]
    flat = [t.name for _, tasks in NFL_ANYTIME_TD_PHASES for t in tasks]
    assert flat == [
        "app.tasks.etl_pipeline.nfl.anytime_td_actuals",
        "app.tasks.etl_pipeline.nfl.sync_defense_schemes",
        "app.tasks.etl_pipeline.nfl.anytime_td_projector",
        "app.tasks.etl_pipeline.nfl.anytime_td_betting",
    ]


def test_anytime_td_midweek_beat_registered():
    from app.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["nfl-anytime-td-pipeline-midweek"]
    assert entry["task"] == _ANYTIME_TD_ORCH
