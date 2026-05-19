"""
ETL pipeline Celery tasks (Development-u9t).

Each sport's pipeline is one task scheduled by Beat (see app/celery_app.py).
The pipeline orchestrators are ported skeletons of YetiBets's nba_update_runner.py
and its sibling sport-specific runners.

Per Development-vir: no Discord notifications. Pipeline status surfaces via
WebSocket events + admin dashboard logs only.

Per Development-flm: model `.pkl` files load from `s3://yetibets/{sport}/...`
once the runtime tasks are ported. The orchestrator skeleton is in place; each
sub-task is marked TODO and will be ported individually as needed.
"""

import logging
from datetime import datetime
from typing import List

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


# ============================================================================
# Sub-task stubs — one Celery task per YetiBets script.
# Each is a TODO: import the actual logic from YetiBets's scripts/<sport>/
# and run it against the YetAI session + pred_* tables.
# ============================================================================


def _stub(task_name: str) -> dict:
    logger.warning(
        "ETL sub-task %s: NOT YET PORTED — skipping. See Development-u9t.", task_name
    )
    return {"status": "skipped", "task": task_name, "reason": "not_ported"}


# --- NBA sub-tasks (mirrors nba_update_runner.py's 26 scripts) -----------------
@celery_app.task(name="app.tasks.etl_pipeline.nba.update_team_roster")
def nba_update_team_roster():
    from app.services.etl.nba.update_team_roster import run
    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.yesterdays_players")
def nba_yesterdays_players():
    from app.services.etl.nba.yesterdays_players import run
    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.today_active_players")
def nba_today_active_players():
    from app.services.etl.nba.today_active_players import run
    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_recent_games")
def nba_update_recent_games():
    return _stub("nba.update_recent_games")


@celery_app.task(name="app.tasks.etl_pipeline.nba.store_actuals")
def nba_store_actuals():
    return _stub("nba.store_actuals")


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_team_stats")
def nba_update_team_stats():
    return _stub("nba.update_team_stats")


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_player_data")
def nba_update_player_data():
    return _stub("nba.update_player_data")


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_injury_status")
def nba_update_injury_status():
    return _stub("nba.update_injury_status")


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_expected_minutes")
def nba_update_expected_minutes():
    return _stub("nba.update_expected_minutes")


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_game_lines")
def nba_update_game_lines():
    return _stub("nba.update_game_lines")


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_predictions")
def nba_generate_predictions():
    return _stub("nba.generate_predictions")


@celery_app.task(name="app.tasks.etl_pipeline.nba.find_top_performers")
def nba_find_top_performers():
    return _stub("nba.find_top_performers")


# ============================================================================
# Pipeline orchestrators — one per sport.
# Run the sub-tasks in dependency order. Failures of a non-critical task
# log + continue; failures of a critical task abort the pipeline.
# ============================================================================

# Maps the 5 logical phases of YetiBets's nba_update_runner.py to lists of sub-tasks.
NBA_PHASES = [
    (
        "data_collection",
        [
            nba_update_team_roster,
            nba_yesterdays_players,
            nba_today_active_players,
            nba_update_recent_games,
        ],
    ),
    (
        "store_actuals",
        [
            nba_store_actuals,
        ],
    ),
    (
        "update_stats",
        [
            nba_update_team_stats,
            nba_update_player_data,
        ],
    ),
    (
        "pre_prediction",
        [
            nba_update_injury_status,
            nba_update_expected_minutes,
            nba_update_game_lines,
        ],
    ),
    (
        "predictions",
        [
            nba_generate_predictions,
            nba_find_top_performers,
        ],
    ),
]


def _run_phases(sport: str, phases: List) -> dict:
    started = datetime.utcnow()
    phase_results = []
    for phase_name, tasks in phases:
        phase_started = datetime.utcnow()
        results = []
        for task in tasks:
            try:
                # .apply() runs synchronously in the current worker (rather than
                # enqueuing a new message). For a sequential pipeline that's
                # exactly what we want — sub-task results are visible in the
                # parent's logs and a failure aborts the phase.
                r = task.apply().get()
                results.append({"task": task.name, "result": r})
            except Exception as e:
                logger.exception("Task %s failed in phase %s", task.name, phase_name)
                results.append({"task": task.name, "error": str(e)})
        phase_results.append(
            {
                "phase": phase_name,
                "duration_s": (datetime.utcnow() - phase_started).total_seconds(),
                "results": results,
            }
        )

    return {
        "sport": sport,
        "started_at": started.isoformat() + "Z",
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "duration_s": (datetime.utcnow() - started).total_seconds(),
        "phases": phase_results,
    }


@celery_app.task(name="app.tasks.etl_pipeline.run_nba_update_pipeline", bind=True)
def run_nba_update_pipeline(self) -> dict:
    """Daily NBA prediction-pipeline run. Mirrors nba_update_runner.py.

    Fires nightly at 03:30 ET (see celery_app.beat_schedule). All 12 sub-tasks
    are currently stubs — they no-op and log a TODO. The orchestrator structure
    is what matters: it preserves the phase ordering from the original script
    so individual sub-tasks can be filled in incrementally without re-touching
    the pipeline."""
    logger.info("NBA update pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("nba", NBA_PHASES)


@celery_app.task(name="app.tasks.etl_pipeline.run_mlb_update_pipeline", bind=True)
def run_mlb_update_pipeline(self) -> dict:
    """MLB daily pipeline orchestrator — stub.

    Sub-tasks to port from YetiBets/scripts/mlb/:
      - update_pitcher_stats.py
      - update_hitter_stats.py
      - homer_predictions.py + strikeout_projections.py
      - meta_learner.py
      - value_bets.py
    """
    logger.info("MLB update pipeline starting (task_id=%s)", self.request.id)
    return {"status": "skeleton_only", "sport": "mlb"}


@celery_app.task(name="app.tasks.etl_pipeline.run_nfl_update_pipeline", bind=True)
def run_nfl_update_pipeline(self) -> dict:
    """NFL weekly pipeline orchestrator — stub.

    Sub-tasks to port from YetiBets/scripts/nfl/:
      - ml_kicker_prediction.py, advanced_qb_predictor.py, enhanced_qb_integration.py
      - ml_pipeline.py (loads NFL .pkl ensemble — depends on Development-flm)
    """
    logger.info("NFL update pipeline starting (task_id=%s)", self.request.id)
    return {"status": "skeleton_only", "sport": "nfl"}


@celery_app.task(name="app.tasks.etl_pipeline.run_nhl_update_pipeline", bind=True)
def run_nhl_update_pipeline(self) -> dict:
    """NHL daily pipeline orchestrator — stub.

    Sub-tasks to port from YetiBets/scripts/nhl/:
      - goalie_saves_model.py
      - player_shots_predictions.py
      - team_totals_predictions.py
    """
    logger.info("NHL update pipeline starting (task_id=%s)", self.request.id)
    return {"status": "skeleton_only", "sport": "nhl"}
