"""
ETL pipeline Celery tasks — daily prediction pipelines on Railway (Celery Beat).

NBA orchestrator mirrors YetiBets ``nba_update_runner.py`` / ``daily_pipeline.py``
(reference repo is read-only; see YetiBets ``ARCHIVE.md``).

Pipeline status: WebSocket + logs (no Discord). XGBoost models: ``s3://yetibets/``.

Parity checklists: ``backend/docs/NBA_ETL_PARITY.md``, ``backend/docs/MLB_ETL_PARITY.md``,
``backend/docs/NHL_ETL_PARITY.md``, ``backend/docs/NFL_ETL_PARITY.md``.
"""

import logging
import os
from datetime import datetime
from typing import List

from app.celery_app import celery_app

logger = logging.getLogger(__name__)

# Tasks whose failure should surface as pipeline partial_failure and block
# treating the run as fully healthy. Enrichment / grading / optional ML are not critical.
CRITICAL_PIPELINE_TASKS: frozenset[str] = frozenset(
    {
        # NBA — slate + core projections
        "app.tasks.etl_pipeline.nba.update_team_roster",
        "app.tasks.etl_pipeline.nba.today_active_players",
        "app.tasks.etl_pipeline.nba.update_recent_games",
        "app.tasks.etl_pipeline.nba.update_team_stats",
        "app.tasks.etl_pipeline.nba.update_injury_status",
        "app.tasks.etl_pipeline.nba.update_expected_minutes",
        "app.tasks.etl_pipeline.nba.update_game_lines",
        "app.tasks.etl_pipeline.nba.generate_predictions",
        "app.tasks.etl_pipeline.nba.generate_rebounds_predictions",
        "app.tasks.etl_pipeline.nba.generate_assists_predictions",
        "app.tasks.etl_pipeline.nba.generate_three_pt_made_predictions",
        "app.tasks.etl_pipeline.nba.generate_steals_predictions",
        "app.tasks.etl_pipeline.nba.generate_blocks_predictions",
        "app.tasks.etl_pipeline.nba.generate_pra_predictions",
        "app.tasks.etl_pipeline.nba.totals_projector",
        "app.tasks.etl_pipeline.nba.spread_projector",
        # MLB — prop boards + persist
        "app.tasks.etl_pipeline.mlb.strikeouts",
        "app.tasks.etl_pipeline.mlb.hits",
        "app.tasks.etl_pipeline.mlb.store_strikeout_projections",
        "app.tasks.etl_pipeline.mlb.game_projections",
        "app.tasks.etl_pipeline.mlb.batter_projections",
        # MLB actuals orchestrator
        "app.tasks.etl_pipeline.mlb.store_game_actuals",
        "app.tasks.etl_pipeline.mlb.store_strikeout_actuals",
        "app.tasks.etl_pipeline.mlb.store_batter_actuals",
        # NHL — ingest, stats, predictions, actuals
        "app.tasks.etl_pipeline.nhl.collect_ingest",
        "app.tasks.etl_pipeline.nhl.update_daily_stats",
        "app.tasks.etl_pipeline.nhl.daily_predictions",
        "app.tasks.etl_pipeline.nhl.collect_goalie_actuals",
        # NFL — weekly QB + kicker boards
        "app.tasks.etl_pipeline.nfl.qb_weekly",
        "app.tasks.etl_pipeline.nfl.kickers",
    }
)


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


@celery_app.task(name="app.tasks.etl_pipeline.yetiwatch.nba")
def nba_yetiwatch():
    from app.services.etl.yetiwatch.run import run_for_sport

    return run_for_sport("nba")


@celery_app.task(name="app.tasks.etl_pipeline.yetiwatch.mlb")
def mlb_yetiwatch():
    from app.services.etl.yetiwatch.run import run_for_sport

    return run_for_sport("mlb")


@celery_app.task(name="app.tasks.etl_pipeline.yetiwatch.nfl")
def nfl_yetiwatch():
    from app.services.etl.yetiwatch.run import run_for_sport

    return run_for_sport("nfl")


@celery_app.task(name="app.tasks.etl_pipeline.yetiwatch.nhl")
def nhl_yetiwatch():
    from app.services.etl.yetiwatch.run import run_for_sport

    return run_for_sport("nhl")


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


@celery_app.task(name="app.tasks.etl_pipeline.nba.spread_projector")
def nba_spread_projector():
    from app.services.etl.nba.spread_projector import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.store_spread_actuals")
def nba_store_spread_actuals():
    from app.services.etl.nba.store_spread_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.spreads_accuracy")
def nba_spreads_accuracy():
    from app.services.etl.nba.spreads_accuracy_tracker import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nba.calculate_prediction_accuracy")
def nba_calculate_prediction_accuracy():
    from app.services.etl.nba.calculate_prediction_accuracy import run

    return run()


# --- MLB sub-tasks (ported from YetiBets scripts/mlb → app/services/etl/mlb) ----
@celery_app.task(name="app.tasks.etl_pipeline.mlb.strikeouts")
def mlb_strikeouts():
    from app.services.etl.mlb.strikeouts import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.hits")
def mlb_hits():
    from app.services.etl.mlb.hits import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.store_strikeout_projections")
def mlb_store_strikeout_projections():
    from app.services.etl.mlb.daily_projection_update import (
        run_store_strikeout_projections,
    )

    return run_store_strikeout_projections()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.game_projections")
def mlb_game_projections():
    from app.services.etl.mlb.game_projection_pipeline import run_game_projections

    return run_game_projections()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.batter_projections")
def mlb_batter_projections():
    from app.services.etl.mlb.daily_batter_projection import run_projections

    return run_projections()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.weather")
def mlb_weather():
    from app.services.etl.mlb.weather import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.blowouts")
def mlb_blowouts():
    from app.services.etl.mlb.blowouts import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.hr_predictions")
def mlb_hr_predictions():
    from app.services.etl.mlb.pipeline import _run_hr_predictions_optional

    return _run_hr_predictions_optional()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.ev")
def mlb_ev():
    from app.services.etl.mlb.mlb_ev import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.store_strikeout_actuals")
def mlb_store_strikeout_actuals():
    from app.services.etl.mlb.daily_projection_update import run_store_strikeout_actuals

    return run_store_strikeout_actuals()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.store_game_actuals")
def mlb_store_game_actuals():
    from app.services.etl.mlb.game_projection_pipeline import run_store_game_actuals

    return run_store_game_actuals()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.store_batter_actuals")
def mlb_store_batter_actuals():
    from app.services.etl.mlb.daily_batter_projection import run_store_batter_actuals

    return run_store_batter_actuals()


@celery_app.task(name="app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier")
def mlb_retrain_strikeout_classifier(dry_run: bool = False):
    from app.services.etl.mlb.strikeout_training import run_retrain_strikeouts

    try:
        return run_retrain_strikeouts(dry_run=dry_run)
    except RuntimeError as exc:
        return {"status": "blocked", "error": str(exc), "dry_run": dry_run}


@celery_app.task(name="app.tasks.etl_pipeline.mlb.hr_rebuild_stage")
def mlb_hr_rebuild_stage(
    stage: str,
    season: int = 2024,
    holdout_date: str = "2024-07-01",
    use_existing_s3: bool = False,
):
    from app.services.etl.mlb.hr_rebuild_runner import run_hr_rebuild_stage

    return run_hr_rebuild_stage(
        stage,
        season=season,
        holdout_date=holdout_date,
        use_existing_s3=use_existing_s3,
    )


@celery_app.task(name="app.tasks.etl_pipeline.mlb.backtest_quick")
def mlb_backtest_quick():
    """Admin/offline quick backtest (20 games). Long runs: use CLI on a worker shell."""
    from app.services.etl.mlb.backtest.cli import parse_args, run_backtest

    args = parse_args(["--quick"])
    backtest_id = run_backtest(args)
    return {"status": "ok", "backtest_id": backtest_id, "preset": "quick"}


@celery_app.task(name="app.tasks.etl_pipeline.mlb.statcast_backfill_season")
def mlb_statcast_backfill_season(season: int, force: bool = False) -> dict:
    from app.services.etl.mlb.statcast_ingest.backfill import backfill_month

    uris: list[str] = []
    errors: list[str] = []
    for month in range(3, 11):
        try:
            uri = backfill_month(season, month, force=force)
            if uri:
                uris.append(uri)
        except Exception as exc:
            errors.append(f"{season}-{month:02d}: {exc}")
    return {"season": season, "partitions": len(uris), "errors": errors}


@celery_app.task(name="app.tasks.etl_pipeline.mlb.statcast_incremental")
def mlb_statcast_incremental() -> dict:
    from app.services.etl.mlb.statcast_ingest.incremental import statcast_incremental

    return statcast_incremental()


@celery_app.task(
    name="app.tasks.etl_pipeline.mlb.rebuild_profiles",
    soft_time_limit=14400,  # 4h — full Statcast load + 4 windows routinely exceeds 1h
    time_limit=16200,  # 4.5h hard kill
)
def mlb_rebuild_profiles(as_of_date: str | None = None) -> dict:
    from datetime import date

    from app.services.etl.mlb.profiles.profile_builder import rebuild_all_profiles

    as_of = date.fromisoformat(as_of_date) if as_of_date else date.today()
    logger.info("mlb.rebuild_profiles starting as_of=%s", as_of)
    counts = rebuild_all_profiles(as_of_date=as_of)
    logger.info("mlb.rebuild_profiles complete as_of=%s counts=%s", as_of, counts)
    return counts


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
            nba_store_spread_actuals,
            nba_store_no_steals_actuals,
        ],
    ),
    (
        "grading",
        [
            nba_totals_accuracy_tracker,
            nba_spreads_accuracy,
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
            nba_yetiwatch,
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
            nba_spread_projector,
            nba_find_top_performers,
        ],
    ),
]


# YetiBets mlb_daily_projections.yml — strikeouts before archiving K projections.
def _mlb_projection_phases():
    """Build MLB projection phases; optional HR ML after weather when enabled."""
    from app.services.etl.mlb.hr_ml_build import hr_ml_enabled

    persist = [
        mlb_store_strikeout_projections,
        mlb_game_projections,
        mlb_batter_projections,
    ]
    enrichment = [mlb_weather]
    if hr_ml_enabled():
        enrichment.append(mlb_hr_predictions)
    enrichment.extend([mlb_blowouts, mlb_ev])
    return [
        ("sync", []),  # games cache runs on its own 3h beat; optional inline below
        ("props", [mlb_yetiwatch, mlb_strikeouts, mlb_hits]),
        ("persist", persist),
        ("enrichment", enrichment),
    ]


# Static snapshot for docs/tests; daily orchestrator uses _mlb_projection_phases().
MLB_PROJECTION_PHASES = _mlb_projection_phases()

MLB_ACTUALS_PHASES = [
    (
        "actuals",
        [
            mlb_store_game_actuals,
            mlb_store_strikeout_actuals,
            mlb_store_batter_actuals,
        ],
    ),
]


def _run_phases(sport: str, phases: List) -> dict:
    started = datetime.utcnow()
    phase_results = []
    failed_tasks: list[str] = []
    critical_failed_tasks: list[str] = []

    for phase_name, tasks in phases:
        phase_started = datetime.utcnow()
        results = []
        phase_errors = 0
        for task in tasks:
            critical = task.name in CRITICAL_PIPELINE_TASKS
            try:
                # .run() executes the task body in-process (no broker, no result
                # backend). Avoids "Never call result.get() within a task!" from
                # task.apply().get() when the orchestrator itself is a Celery task.
                r = task.run()
                results.append({"task": task.name, "critical": critical, "result": r})
            except Exception as e:
                logger.exception("Task %s failed in phase %s", task.name, phase_name)
                results.append(
                    {"task": task.name, "critical": critical, "error": str(e)}
                )
                failed_tasks.append(task.name)
                phase_errors += 1
                if critical:
                    critical_failed_tasks.append(task.name)
        phase_results.append(
            {
                "phase": phase_name,
                "status": "error" if phase_errors else "ok",
                "errors": phase_errors,
                "duration_s": (datetime.utcnow() - phase_started).total_seconds(),
                "results": results,
            }
        )

    status = "partial_failure" if failed_tasks else "ok"

    return {
        "status": status,
        "sport": sport,
        "started_at": started.isoformat() + "Z",
        "finished_at": datetime.utcnow().isoformat() + "Z",
        "duration_s": (datetime.utcnow() - started).total_seconds(),
        "failed_tasks": failed_tasks,
        "critical_failed_tasks": critical_failed_tasks,
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
    """MLB pre-game projections (10:00 ET beat). See MLB_ETL_PARITY.md.

    Games cache (Odds API, 4 sports) is refreshed by ``sync-games-cache-thrice-daily``
    only — avoid embedding ``sync_games_cache`` here so MLB's twice-daily beat does
    not multiply Odds API usage.
    """
    logger.info("MLB projections pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("mlb", _mlb_projection_phases())


@celery_app.task(name="app.tasks.etl_pipeline.run_mlb_store_actuals", bind=True)
def run_mlb_store_actuals(self) -> dict:
    """MLB post-game actuals (04:30 ET beat)."""
    logger.info("MLB actuals pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("mlb", MLB_ACTUALS_PHASES)


# --- NFL sub-tasks (ported from YetiBets scripts/nfl → app/services/etl/nfl) ----
@celery_app.task(name="app.tasks.etl_pipeline.nfl.collect_qb_actuals")
def nfl_collect_qb_actuals():
    from app.services.etl.nfl.collect_qb_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.collect_kicker_actuals")
def nfl_collect_kicker_actuals():
    from app.services.etl.nfl.collect_kicker_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.qb_dynamic")
def nfl_qb_dynamic():
    from app.services.etl.nfl.qb_dynamic import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.qb_betting")
def nfl_qb_betting():
    from app.services.etl.nfl.qb_betting import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.qb_weekly")
def nfl_qb_weekly():
    """Dynamic QB yards from nflverse, then Odds API O/U lines (YetiBets chain)."""
    from app.services.etl.nfl.qb_weekly import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.kickers")
def nfl_kickers():
    from app.services.etl.nfl.kickers import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.update_game_lines")
def nfl_update_game_lines():
    from app.services.etl.nfl.update_game_lines import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.spread_projector")
def nfl_spread_projector():
    from app.services.etl.nfl.spread_projector import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.totals_projector")
def nfl_totals_projector():
    from app.services.etl.nfl.totals_projector import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.store_game_actuals")
def nfl_store_game_actuals():
    from app.services.etl.nfl.store_game_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.seed_elo_history")
def nfl_seed_elo_history():
    from app.services.etl.nfl.seed_elo_history import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.sync_defense_schemes")
def nfl_sync_defense_schemes():
    from app.services.etl.nfl.sync_defense_schemes import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.anytime_td_projector")
def nfl_anytime_td_projector():
    from app.services.etl.nfl.anytime_td_projector import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.anytime_td_betting")
def nfl_anytime_td_betting():
    from app.services.etl.nfl.anytime_td_betting import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nfl.anytime_td_actuals")
def nfl_anytime_td_actuals():
    from app.services.etl.nfl.anytime_td_actuals import run

    return run()


# Grade last week, refresh game board, then current-week props.
NFL_PHASES = [
    (
        "actuals",
        [
            nfl_collect_qb_actuals,
            nfl_collect_kicker_actuals,
            nfl_store_game_actuals,
            nfl_anytime_td_actuals,
        ],
    ),
    (
        "game_lines",
        [
            nfl_update_game_lines,
        ],
    ),
    (
        "game_projections",
        [
            nfl_spread_projector,
            nfl_totals_projector,
        ],
    ),
    (
        "anytime_td",
        [
            nfl_sync_defense_schemes,
            nfl_anytime_td_projector,
            nfl_anytime_td_betting,
        ],
    ),
    (
        "predictions",
        [
            nfl_yetiwatch,
            nfl_qb_weekly,
            nfl_kickers,
        ],
    ),
]


@celery_app.task(name="app.tasks.etl_pipeline.run_nfl_update_pipeline", bind=True)
def run_nfl_update_pipeline(self) -> dict:
    """NFL weekly pipeline — actuals, game lines/projections, anytime TD, QB + kicker props.

    Phases: actuals → game_lines → game_projections → anytime_td → predictions.
    Scheduled on Beat as ``nfl-update-pipeline-daily`` (4:30 ET). See ``NFL_ETL_PARITY.md``.
    """
    logger.info("NFL update pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("nfl", NFL_PHASES)


# Gameday slice — re-pull injuries, refresh QB + kicker boards, then reprice
# spreads/totals. QB weekly stays before spread so backup flags exist.
NFL_GAMEDAY_AVAILABILITY_PHASES = [
    (
        "predictions",
        [
            nfl_qb_weekly,
            nfl_kickers,
        ],
    ),
    (
        "game_projections",
        [
            nfl_spread_projector,
            nfl_totals_projector,
        ],
    ),
]


@celery_app.task(name="app.tasks.etl_pipeline.run_nfl_gameday_availability", bind=True)
def run_nfl_gameday_availability(self) -> dict:
    """Refresh QB/kicker props and reprice the game board for late Out/backup.

    Beat: Sun 10:00 / 12:30 / 15:30, Mon 18:00, Thu 10:00 / 19:00, Sat 12:30 ET.
    See ``qb_late_availability`` and ``qb_spread_adjustment``.
    """
    logger.info(
        "NFL gameday availability refresh starting (task_id=%s)", self.request.id
    )
    return _run_phases("nfl_gameday", NFL_GAMEDAY_AVAILABILITY_PHASES)


# Admin / midweek slice — anytime TD only (also runs inside NFL_PHASES).
NFL_ANYTIME_TD_PHASES = [
    (
        "actuals",
        [
            nfl_anytime_td_actuals,
        ],
    ),
    (
        "anytime_td",
        [
            nfl_update_game_lines,
            nfl_sync_defense_schemes,
            nfl_anytime_td_projector,
            nfl_anytime_td_betting,
        ],
    ),
]


@celery_app.task(name="app.tasks.etl_pipeline.run_nfl_anytime_td_pipeline", bind=True)
def run_nfl_anytime_td_pipeline(self) -> dict:
    """NFL anytime-TD pipeline — actuals, schemes, projector, Odds attach.

    Enqueue from admin to refresh the anytime board without the full weekly NFL
    pipeline. See ``NFL_ANYTIME_TD.md``.
    """
    logger.info("NFL anytime TD pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("nfl", NFL_ANYTIME_TD_PHASES)


# --- Fantasy sub-tasks -------------------------------------------------------
@celery_app.task(name="app.tasks.etl_pipeline.fantasy.sync_player_analytics")
def fantasy_sync_player_analytics(season: int | None = None):
    """Backfill ``player_analytics`` from nflverse weekly data for start/sit."""
    from app.services.etl.fantasy.sync_player_analytics import run

    return run(season=season, sync_fantasy_players=True)


# --- NHL sub-tasks (ported from YetiBets scripts/nhl → app/services/etl/nhl) ----
@celery_app.task(name="app.tasks.etl_pipeline.nhl.collect_ingest")
def nhl_collect_ingest():
    from app.services.etl.nhl.collect_historical_data import run_ingest

    return run_ingest()


@celery_app.task(name="app.tasks.etl_pipeline.nhl.update_daily_stats")
def nhl_update_daily_stats():
    from app.services.etl.nhl.collect_historical_data import run_update_daily_stats

    return run_update_daily_stats()


@celery_app.task(name="app.tasks.etl_pipeline.nhl.collect_goalie_actuals")
def nhl_collect_goalie_actuals():
    from app.services.etl.nhl.collect_goalie_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nhl.collect_team_shots_actuals")
def nhl_collect_team_shots_actuals():
    from app.services.etl.nhl.collect_team_shots_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nhl.collect_player_shots_actuals")
def nhl_collect_player_shots_actuals():
    from app.services.etl.nhl.collect_player_shots_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nhl.collect_team_totals_actuals")
def nhl_collect_team_totals_actuals():
    from app.services.etl.nhl.collect_team_totals_actuals import run

    return run()


@celery_app.task(name="app.tasks.etl_pipeline.nhl.daily_predictions")
def nhl_daily_predictions():
    from app.services.etl.nhl.daily_predictions import run

    return run()


# Ingest refreshes game/goalie/team tables; daily_predictions mirrors YetiBets
# automated_daily_predictions (stats refresh + goalie/player/totals + actuals).
NHL_PHASES = [
    ("ingest", [nhl_collect_ingest]),
    (
        "actuals",
        [
            nhl_collect_goalie_actuals,
            nhl_collect_team_shots_actuals,
            nhl_collect_player_shots_actuals,
            nhl_collect_team_totals_actuals,
        ],
    ),
    ("automation", [nhl_yetiwatch, nhl_daily_predictions]),
]


@celery_app.task(name="app.tasks.etl_pipeline.run_nhl_update_pipeline", bind=True)
def run_nhl_update_pipeline(self) -> dict:
    """NHL daily pipeline — ingest, stats, yesterday actuals, today's predictions.

    Mirrors YetiBets ``run_daily_automation.sh`` + ``automated_daily_predictions.py``.
    See ``backend/docs/NHL_ETL_PARITY.md``.
    """
    logger.info("NHL update pipeline starting (task_id=%s)", self.request.id)
    return _run_phases("nhl", NHL_PHASES)


# =============================================================================
# WNBA sub-tasks (Phase 1 — added 2026-05-21)
# Spec: docs/superpowers/specs/2026-05-21-wnba-support-design.md
# Plan: docs/superpowers/plans/2026-05-21-wnba-phase-1.md
# =============================================================================

from datetime import date as _date  # noqa: E402

from app.services.etl.wnba import (  # noqa: E402
    spread_projector as _wnba_spread_projector,
    spreads_accuracy_tracker as _wnba_spreads_accuracy,
    store_actuals as _wnba_store_actuals,
    totals_accuracy_tracker as _wnba_totals_accuracy,
    totals_projector as _wnba_totals_projector,
    update_game_lines as _wnba_update_game_lines,
    update_injury_status as _wnba_update_injury,
    update_team_defense_stats as _wnba_update_def,
    update_team_offense_stats as _wnba_update_off,
    update_team_roster as _wnba_update_roster,
)


def _wnba_in_season() -> bool:
    """WNBA runs May 1 – October 31 (Eastern). Outside this window all WNBA
    jobs no-op. Recomputed each call so workers do not need a restart at the
    season boundary.
    """
    today = _date.today()
    return _date(today.year, 5, 1) <= today <= _date(today.year, 10, 31)


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_team_roster")
def wnba_update_team_roster():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_update_roster.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_team_offense_stats")
def wnba_update_team_offense_stats():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_update_off.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_team_defense_stats")
def wnba_update_team_defense_stats():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_update_def.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_injury_status")
def wnba_update_injury_status():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_update_injury.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_game_lines")
def wnba_update_game_lines():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_update_game_lines.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.totals_projector")
def wnba_totals_projector():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_totals_projector.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.spread_projector")
def wnba_spread_projector():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_spread_projector.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.store_actuals")
def wnba_store_actuals():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_store_actuals.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.totals_accuracy")
def wnba_totals_accuracy():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_totals_accuracy.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.spreads_accuracy")
def wnba_spreads_accuracy():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_spreads_accuracy.run()


from app.services.etl.wnba import (  # noqa: E402
    calculate_prediction_accuracy as _wnba_prop_accuracy,
    generate_assists_predictions as _wnba_gen_assists,
    generate_points_predictions as _wnba_gen_points,
    generate_pra_predictions as _wnba_gen_pra,
    generate_rebounds_predictions as _wnba_gen_rebounds,
    generate_three_pt_made_predictions as _wnba_gen_threes,
    today_active_players as _wnba_today_active,
    update_expected_minutes as _wnba_expected_minutes,
    update_recent_games as _wnba_update_recent,
)
from app.services.etl.yetiwatch.run import run_for_sport as _yetiwatch_for_sport


class _YetiWatchRunner:
    def run(self):
        return _yetiwatch_for_sport("wnba")


_wnba_yetiwatch = _YetiWatchRunner()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_recent_games")
def wnba_update_recent_games():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_update_recent.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.today_active_players")
def wnba_today_active_players():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_today_active.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.update_expected_minutes")
def wnba_update_expected_minutes():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_expected_minutes.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.generate_points")
def wnba_generate_points():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_gen_points.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.generate_assists")
def wnba_generate_assists():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_gen_assists.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.generate_rebounds")
def wnba_generate_rebounds():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_gen_rebounds.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.generate_three_pt_made")
def wnba_generate_three_pt_made():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_gen_threes.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.generate_pra")
def wnba_generate_pra():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_gen_pra.run()


@celery_app.task(name="app.tasks.etl_pipeline.wnba.prop_accuracy")
def wnba_prop_accuracy():
    if not _wnba_in_season():
        return {"status": "out_of_season"}
    return _wnba_prop_accuracy.run()


@celery_app.task(name="app.tasks.etl_pipeline.run_wnba_team_stats_daily", bind=True)
def run_wnba_team_stats_daily(self) -> dict:
    """Refresh WNBA team offense/defense dashboards and roster from stats.wnba.com.

    Uses the default (longer) HTTP retry profile. Scheduled once daily so the
    hourly pregame orchestrator is not blocked on slow NBA Stats responses.
    """
    if not _wnba_in_season():
        return {"status": "out_of_season"}

    logger.info("WNBA team stats daily refresh starting (task_id=%s)", self.request.id)
    results: dict[str, dict] = {}
    for label, mod in [
        ("update_team_offense_stats", _wnba_update_off),
        ("update_team_defense_stats", _wnba_update_def),
        ("update_team_roster", _wnba_update_roster),
    ]:
        try:
            results[label] = mod.run(profile="default")
        except Exception as exc:
            logger.exception("WNBA team stats step %s failed", label)
            results[label] = {"status": "error", "error": str(exc)}
    return {"status": "ok", "results": results}


@celery_app.task(name="app.tasks.etl_pipeline.run_wnba_update_pipeline", bind=True)
def run_wnba_update_pipeline(self) -> dict:
    """WNBA pregame orchestrator (daily + hourly beat).

    Odds API game lines are **not** pulled here — they are capped at 3x/day via the
    ``wnba-update-game-lines-thrice-daily`` beat entry. Team offense/defense/roster
    refresh runs on ``wnba-update-team-stats-daily`` instead. This task refreshes
    injuries (ESPN), slate, projectors, and props using rows in ``pred_wnba_game_lines``.
    """
    if not _wnba_in_season():
        return {"status": "out_of_season"}

    logger.info("WNBA update pipeline starting (task_id=%s)", self.request.id)
    results: dict[str, dict] = {}
    for label, mod in [
        ("update_injury_status", _wnba_update_injury),
        ("update_recent_games", _wnba_update_recent),
        ("today_active_players", _wnba_today_active),
        ("update_expected_minutes", _wnba_expected_minutes),
        ("yetiwatch", _wnba_yetiwatch),
        ("totals_projector", _wnba_totals_projector),
        ("spread_projector", _wnba_spread_projector),
        ("generate_points", _wnba_gen_points),
        ("generate_assists", _wnba_gen_assists),
        ("generate_rebounds", _wnba_gen_rebounds),
        ("generate_three_pt_made", _wnba_gen_threes),
        ("generate_pra", _wnba_gen_pra),
        ("store_actuals", _wnba_store_actuals),
        ("totals_accuracy", _wnba_totals_accuracy),
        ("spreads_accuracy", _wnba_spreads_accuracy),
        ("prop_accuracy", _wnba_prop_accuracy),
    ]:
        try:
            results[label] = mod.run()
        except Exception as exc:
            logger.exception("WNBA pipeline step %s failed", label)
            results[label] = {"status": "error", "error": str(exc)}
    return {"status": "ok", "results": results}
