"""Admin Celery task catalogs.

Static data shared by the admin Celery ops router. Kept in its own module
so the router file stays focused on request handling.

- `ADMIN_FIREABLE_TASKS`: allow-list of task names for sync fire-and-wait
  (POST /run-task), mapped to per-task timeout in seconds.
- `PIPELINE_ENQUEUE_CATALOG`: orchestrator-level tasks shown in the admin UI.
- `FIREABLE_CATALOG`: curated sub-tasks exposed for one-off debug runs.
- `ADMIN_ENQUEUE_TASKS`: the full allow-list (orchestrators ∪ allow-listed
  individual tasks), used for membership checks on POST /enqueue.
"""

from __future__ import annotations

# Allow-list of ETL tasks for POST /run-task (sync fire-and-wait).
ADMIN_FIREABLE_TASKS: dict[str, float] = {
    "app.tasks.health.ping": 10.0,
    "app.tasks.games_sync.sync_games_cache": 180.0,
    "app.tasks.etl_pipeline.nba.yesterdays_players": 120.0,
    "app.tasks.etl_pipeline.nba.today_active_players": 120.0,
    "app.tasks.etl_pipeline.nba.update_team_roster": 300.0,
    "app.tasks.etl_pipeline.nba.update_recent_games": 900.0,
    "app.tasks.etl_pipeline.nba.update_injury_status": 120.0,
    "app.tasks.etl_pipeline.nba.update_game_lines": 120.0,
    "app.tasks.etl_pipeline.nba.update_team_stats": 300.0,
    "app.tasks.etl_pipeline.nba.update_player_data": 900.0,
    "app.tasks.etl_pipeline.nba.update_expected_minutes": 120.0,
    "app.tasks.etl_pipeline.nba.generate_predictions": 300.0,
    "app.tasks.etl_pipeline.nba.generate_rebounds_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_assists_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_three_pt_made_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_steals_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.generate_blocks_predictions": 600.0,
    "app.tasks.etl_pipeline.nba.store_actuals": 600.0,
    "app.tasks.etl_pipeline.nba.find_top_performers": 180.0,
    "app.tasks.etl_pipeline.nba.totals_projector": 300.0,
    "app.tasks.etl_pipeline.nba.spread_projector": 300.0,
    "app.tasks.etl_pipeline.nba.store_spread_actuals": 300.0,
    "app.tasks.etl_pipeline.nba.spreads_accuracy": 300.0,
    "app.tasks.etl_pipeline.mlb.strikeouts": 600.0,
    "app.tasks.etl_pipeline.mlb.hits": 600.0,
    "app.tasks.etl_pipeline.mlb.store_strikeout_projections": 600.0,
    "app.tasks.etl_pipeline.mlb.store_strikeout_actuals": 600.0,
    "app.tasks.etl_pipeline.mlb.game_projections": 300.0,
    "app.tasks.etl_pipeline.mlb.batter_projections": 300.0,
    "app.tasks.etl_pipeline.mlb.weather": 180.0,
    "app.tasks.etl_pipeline.mlb.blowouts": 180.0,
    "app.tasks.etl_pipeline.mlb.hr_predictions": 900.0,
    "app.tasks.etl_pipeline.mlb.ev": 600.0,
    "app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier": 3600.0,
    "app.tasks.etl_pipeline.mlb.hr_rebuild_stage": 7200.0,
    "app.tasks.etl_pipeline.mlb.backtest_quick": 1800.0,
    "app.tasks.etl_pipeline.mlb.statcast_backfill_season": 14400.0,
    "app.tasks.etl_pipeline.mlb.statcast_incremental": 900.0,
    "app.tasks.etl_pipeline.mlb.rebuild_profiles": 3600.0,
    "app.tasks.etl_pipeline.nhl.collect_ingest": 1200.0,
    "app.tasks.etl_pipeline.nhl.update_daily_stats": 600.0,
    "app.tasks.etl_pipeline.nhl.daily_predictions": 900.0,
    "app.tasks.etl_pipeline.nhl.collect_goalie_actuals": 300.0,
    "app.tasks.etl_pipeline.nhl.collect_team_shots_actuals": 300.0,
    "app.tasks.etl_pipeline.nhl.collect_player_shots_actuals": 600.0,
    "app.tasks.etl_pipeline.nhl.collect_team_totals_actuals": 300.0,
    "app.tasks.etl_pipeline.nfl.collect_qb_actuals": 600.0,
    "app.tasks.etl_pipeline.nfl.collect_kicker_actuals": 300.0,
    "app.tasks.etl_pipeline.nfl.qb_dynamic": 600.0,
    "app.tasks.etl_pipeline.nfl.qb_betting": 300.0,
    "app.tasks.etl_pipeline.nfl.qb_weekly": 900.0,
    "app.tasks.etl_pipeline.nfl.kickers": 600.0,
    "app.tasks.etl_pipeline.wnba.update_game_lines": 120.0,
    "app.tasks.etl_pipeline.wnba.today_active_players": 120.0,
    "app.tasks.etl_pipeline.wnba.totals_projector": 300.0,
    "app.tasks.etl_pipeline.wnba.spread_projector": 300.0,
    "auto_pick.yetai_bets": 600.0,
}

PIPELINE_ENQUEUE_CATALOG: list[dict[str, str]] = [
    {
        "task_name": "app.tasks.etl_pipeline.run_mlb_update_pipeline",
        "label": "MLB daily projections",
        "sport": "mlb",
        "description": "Strikeouts, hits, boards, weather, blowouts, value bets (EV); optional HR ML when S3 CSVs set.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_mlb_store_actuals",
        "label": "MLB store actuals",
        "sport": "mlb",
        "description": "Post-game actuals for game, strikeout, and batter projection tables.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_nba_update_pipeline",
        "label": "NBA daily pipeline",
        "sport": "nba",
        "description": "Full NBA ETL: roster, stats, injury, all prop models, game totals + spreads.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.nba.spread_projector",
        "label": "NBA spread projector",
        "sport": "nba",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.nba.spread_projector"
        ],
        "description": "Elo+pace spread / win-probability (needs game lines).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_wnba_update_pipeline",
        "label": "WNBA daily pipeline",
        "sport": "wnba",
        "description": (
            "Full WNBA ETL: roster, stats, injury, game lines, totals/spread "
            "projectors, points/assists/rebounds props (May–Oct ET)."
        ),
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_nfl_update_pipeline",
        "label": "NFL weekly pipeline",
        "sport": "nfl",
        "description": "QB actuals + kicker actuals, QB yards/lines, kicker projections (optional ML blend).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.run_nhl_update_pipeline",
        "label": "NHL daily pipeline",
        "sport": "nhl",
        "description": "Ingest + goalie/SOG/totals with DraftKings edges.",
    },
]

# Subset exposed in admin UI for one-off debug runs (sync, blocks until timeout).
FIREABLE_CATALOG: list[dict[str, str | float]] = [
    {
        "task_name": "auto_pick.yetai_bets",
        "label": "YetAI auto-pick now",
        "sport": "yetai",
        "timeout_s": ADMIN_FIREABLE_TASKS["auto_pick.yetai_bets"],
        "description": (
            "Score today's candidates and write up to 4 picks as pending_approval. "
            "Requires AUTO_YETAI_PICKS_ENABLED on worker; approve at /admin/yetai-picks."
        ),
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.ev",
        "label": "MLB value bets (EV)",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.ev"],
        "description": "Refresh pred_value_bets for today (requires ODDS_API_KEY + projections).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.hr_predictions",
        "label": "MLB HR ML",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.hr_predictions"],
        "description": "HR ML: build lineup/features (MLB_HR_AUTO_BUILD=1) then predict_today → pred_daily_hr_predictions.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.strikeouts",
        "label": "MLB strikeouts",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.strikeouts"],
        "description": "Rebuild pred_pitcher for today's slate (run before store K).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.store_strikeout_projections",
        "label": "MLB archive K projections",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.store_strikeout_projections"
        ],
        "description": "Copy pred_pitcher → pred_strikeout_projections for today.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.store_strikeout_actuals",
        "label": "MLB archive K actuals",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.store_strikeout_actuals"
        ],
        "description": "Post-game K actuals → pred_strikeout_actuals (yesterday).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier",
        "label": "MLB retrain K classifier",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.retrain_strikeout_classifier"
        ],
        "description": "Retrain strikeout model on prod DB (requires joined rows ≥ MLB_STRIKEOUT_MIN_JOINED_ROWS).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.backtest_quick",
        "label": "MLB backtest (--quick)",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.mlb.backtest_quick"],
        "description": "20-game backtest; JSON under scripts/mlb_backtest_results/runs/ on worker.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.statcast_backfill_season",
        "label": "MLB Statcast backfill (season)",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.statcast_backfill_season"
        ],
        "description": "Monthly Statcast pitch parquet backfill for one season (Mar–Oct).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.statcast_incremental",
        "label": "MLB Statcast incremental",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.statcast_incremental"
        ],
        "description": "Refresh current month Statcast partition (yesterday's games).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.mlb.rebuild_profiles",
        "label": "MLB rebuild profiles",
        "sport": "mlb",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.mlb.rebuild_profiles"
        ],
        "description": "Rebuild batter/pitcher profile snapshots from S3 parquet for as_of_date.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.nhl.daily_predictions",
        "label": "NHL daily predictions",
        "sport": "nhl",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.nhl.daily_predictions"
        ],
        "description": "Goalie, SOG, team totals automation.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.nfl.kickers",
        "label": "NFL kickers",
        "sport": "nfl",
        "timeout_s": ADMIN_FIREABLE_TASKS["app.tasks.etl_pipeline.nfl.kickers"],
        "description": "Kicker projections; ML blend when NFL_MODELS_S3_PREFIX or local models.",
    },
    {
        "task_name": "app.tasks.etl_pipeline.wnba.update_game_lines",
        "label": "WNBA game lines",
        "sport": "wnba",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.wnba.update_game_lines"
        ],
        "description": "Consensus O/U and spreads from Odds API (basketball_wnba).",
    },
    {
        "task_name": "app.tasks.etl_pipeline.wnba.totals_projector",
        "label": "WNBA totals projector",
        "sport": "wnba",
        "timeout_s": ADMIN_FIREABLE_TASKS[
            "app.tasks.etl_pipeline.wnba.totals_projector"
        ],
        "description": "Game totals O/U projections (needs game lines + team stats).",
    },
]

# Orchestrators + curated sub-tasks (same names as POST /run-task allow-list).
ADMIN_ENQUEUE_TASKS: frozenset[str] = frozenset(
    {entry["task_name"] for entry in PIPELINE_ENQUEUE_CATALOG}
    | set(ADMIN_FIREABLE_TASKS.keys())
)
