from app.data.celery_tasks import ADMIN_FIREABLE_TASKS


def test_mlb_statcast_tasks_in_admin_allow_list():
    assert "app.tasks.etl_pipeline.mlb.statcast_backfill_season" in ADMIN_FIREABLE_TASKS
    assert "app.tasks.etl_pipeline.mlb.statcast_incremental" in ADMIN_FIREABLE_TASKS
    assert "app.tasks.etl_pipeline.mlb.rebuild_profiles" in ADMIN_FIREABLE_TASKS
