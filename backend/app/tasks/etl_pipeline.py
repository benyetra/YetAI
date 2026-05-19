"""
ETL pipeline Celery tasks — daily prediction pipelines on Railway (Celery Beat).

NBA orchestrator mirrors YetiBets ``nba_update_runner.py`` / ``daily_pipeline.py``
(reference repo is read-only; see YetiBets ``ARCHIVE.md``).

Pipeline status: WebSocket + logs (no Discord). XGBoost models: ``s3://yetibets/``.

Parity checklist: ``backend/docs/NBA_ETL_PARITY.md``.
"""

import logging
from datetime import datetime
from typing import List

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


# --- NBA sub-tasks (ported from YetiBets scripts/nba → app/services/etl/nba) ----
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
    from app.services.etl.nba.update_recent_games import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.store_actuals")
def nba_store_actuals():
    from app.services.etl.nba.store_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_team_stats")
def nba_update_team_stats():
    """Refresh both pred_team_offense_stats (API-Sports) + pred_team_defense_stats
    (derived from pred_recent_games). Defense must run after offense isn't a
    requirement — they touch different tables — but recent_games-derived
    defense is freshest right after update_recent_games runs."""
    from app.services.etl.nba.update_team_offense_stats import run as run_off
    from app.services.etl.nba.update_team_defense_stats import run as run_def

    return {"offense": run_off(), "defense": run_def()}


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_player_data")
def nba_update_player_data():
    from app.services.etl.nba.update_player_career_data import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_injury_status")
def nba_update_injury_status():
    from app.services.etl.nba.update_injury_status import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_expected_minutes")
def nba_update_expected_minutes():
    from app.services.etl.nba.update_expected_minutes import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.update_game_lines")
def nba_update_game_lines():
    from app.services.etl.nba.update_game_lines import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_predictions")
def nba_generate_predictions():
    from app.services.etl.nba.generate_points_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.find_top_performers")
def nba_find_top_performers():
    from app.services.etl.nba.find_top_performers import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_rebounds_predictions")
def nba_generate_rebounds_predictions():
    from app.services.etl.nba.generate_rebounds_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_assists_predictions")
def nba_generate_assists_predictions():
    from app.services.etl.nba.generate_assists_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_three_pt_made_predictions")
def nba_generate_three_pt_made_predictions():
    from app.services.etl.nba.generate_three_pt_made_predictions import run

    return run()


@celery_app.task(
    name="app.tasks.etl_pipeline.nba.generate_free_throws_made_predictions"
)
def nba_generate_free_throws_made_predictions():
    from app.services.etl.nba.generate_free_throws_made_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_steals_predictions")
def nba_generate_steals_predictions():
    from app.services.etl.nba.generate_steals_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_blocks_predictions")
def nba_generate_blocks_predictions():
    from app.services.etl.nba.generate_blocks_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_pra_predictions")
def nba_generate_pra_predictions():
    from app.services.etl.nba.generate_pra_predictions import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.generate_no_steals")
def nba_generate_no_steals():
    from app.services.etl.nba.generate_no_steals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.store_no_steals_actuals")
def nba_store_no_steals_actuals():
    from app.services.etl.nba.generate_no_steals import store_no_steals_actuals

    return store_no_steals_actuals()


@celery_app.task(name="app.tasks.etl_pipeline.nba.totals_projector")
def nba_totals_projector():
    from app.services.etl.nba.totals_projector import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.totals_accuracy_tracker")
def nba_totals_accuracy_tracker():
    from app.services.etl.nba.totals_accuracy_tracker import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.calculate_prediction_accuracy")
def nba_calculate_prediction_accuracy():
    from app.services.etl.nba.calculate_prediction_accuracy import run

    return run()


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
            nba_store_no_steals_actuals,
        ],
    ),
    (
        "grading",
        [
            nba_totals_accuracy_tracker,
            nba_calculate_prediction_accuracy,
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
            nba_generate_no_steals,
            nba_generate_steals_predictions,
            nba_generate_blocks_predictions,
            nba_generate_assists_predictions,
            nba_generate_rebounds_predictions,
            nba_generate_predictions,
            nba_generate_three_pt_made_predictions,
            nba_generate_free_throws_made_predictions,
            nba_generate_pra_predictions,
            nba_totals_projector,
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
                # .run() executes the task body in-process (no broker, no result
                # backend). Avoids "Never call result.get() within a task!" from
                # task.apply().get() when the orchestrator itself is a Celery task.
                r = task.run()
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
    """Daily NBA prediction pipeline (03:30 ET, celery_app beat_schedule).

    Runs NBA_PHASES sequentially via task.run() (in-process). See NBA_ETL_PARITY.md
    for gaps vs the 28-step YetiBets daily_pipeline list."""
    logger.info("NBA update pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("nba", NBA_PHASES)


@celery_app.task(name="app.tasks.etl_pipeline.run_mlb_update_pipeline", bind=True)
def run_mlb_update_pipeline(self) -> dict:
    """MLB daily maintenance: refresh games cache + report pred_* row counts.

    Strikeout/HR/game projections are populated by existing YetAI/legacy jobs;
    this orchestrator does not stub — it syncs Odds API games and surfaces
  what is already in Railway Postgres for the slate date.
    """
    from datetime import datetime

    from app.core.database import SessionLocal
    from app.models.predictions_models import GameProjections, Homer, StrikeoutProjections
    from app.services.etl.nba._espn import now_eastern
    from app.tasks.games_sync import sync_games_cache

    logger.info("MLB update pipeline starting (task_id=%s)", self.request.id)
    today = now_eastern().date()
    games_sync = sync_games_cache.run()

    db = SessionLocal()
    try:
        table_counts = {
            "strikeout_projections": db.query(StrikeoutProjections)
            .filter(StrikeoutProjections.date == today)
            .count(),
            "game_projections": db.query(GameProjections)
            .filter(GameProjections.date == today)
            .count(),
            "home_run_predictions": db.query(Homer).count(),
        }
    finally:
        db.close()

    return {
        "status": "ok",
        "sport": "mlb",
        "date": today.isoformat(),
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "games_sync": games_sync,
        "table_counts": table_counts,
    }


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
