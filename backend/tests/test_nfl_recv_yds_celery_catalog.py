from app.tasks import etl_pipeline


def test_recv_yds_weekly_task_registered():
    assert hasattr(etl_pipeline, "nfl_recv_yds_weekly")
    assert etl_pipeline.nfl_recv_yds_weekly.name == (
        "app.tasks.etl_pipeline.nfl.recv_yds_weekly"
    )


def test_recv_yds_in_nfl_phases_predictions_and_actuals():
    phases = {name: tasks for name, tasks in etl_pipeline.NFL_PHASES}
    pred_names = [t.name for t in phases["predictions"]]
    actual_names = [t.name for t in phases["actuals"]]
    assert "app.tasks.etl_pipeline.nfl.recv_yds_weekly" in pred_names
    assert "app.tasks.etl_pipeline.nfl.collect_recv_yds_actuals" in actual_names
    # After kickers in predictions:
    assert pred_names.index(
        "app.tasks.etl_pipeline.nfl.recv_yds_weekly"
    ) > pred_names.index("app.tasks.etl_pipeline.nfl.kickers")


def test_recv_yds_in_gameday_predictions():
    phases = {
        name: tasks for name, tasks in etl_pipeline.NFL_GAMEDAY_AVAILABILITY_PHASES
    }
    names = [t.name for t in phases["predictions"]]
    assert "app.tasks.etl_pipeline.nfl.recv_yds_weekly" in names
