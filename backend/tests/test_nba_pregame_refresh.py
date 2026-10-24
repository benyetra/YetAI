"""NBA midday refresh: lines + projectors re-run, switchable off."""

from app.celery_app import celery_app
from app.tasks import etl_pipeline as ep


def _names(phases):
    return [t.name for _, tasks in phases for t in tasks]


def test_pregame_phases_refresh_lines_then_every_projector():
    names = _names(ep.NBA_PREGAME_PHASES)
    assert names.index(ep.nba_update_game_lines.name) < names.index(
        ep.nba_totals_projector.name
    )
    for task in (
        ep.nba_update_injury_status,
        ep.nba_generate_predictions,
        ep.nba_totals_projector,
        ep.nba_spread_projector,
    ):
        assert task.name in names
    # Grading and data collection stay in the overnight run.
    assert ep.nba_store_actuals.name not in names


def test_pregame_refresh_is_scheduled_and_can_be_disabled(monkeypatch):
    entry = celery_app.conf.beat_schedule["nba-pregame-refresh"]
    assert entry["task"] == ep.run_nba_pregame_refresh.name
    monkeypatch.setenv("NBA_PREGAME_REFRESH_ENABLED", "0")
    assert ep.run_nba_pregame_refresh.run() == {"status": "disabled"}
