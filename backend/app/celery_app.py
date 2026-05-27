"""
Celery application + Beat schedule for YetAI background workers.

Two task groups:
- live_pollers (Development-9gk): poll sportsbook/league feeds every N seconds,
  surface prop events to alerting + user notifications.
- etl_pipeline (Development-u9t): nightly run of the prediction-generation
  pipeline (ports YetiBets's nba_update_runner.py + sibling sport orchestrators).

Per Development-vir (2026-05-17): no Discord notifications. Alerts route through
WebSocket + Twilio only.
"""

from celery import Celery
from celery.schedules import crontab

from app.core.redis_broker import pick_redis_url

_broker_url = pick_redis_url()

celery_app = Celery(
    "yetai",
    broker=_broker_url,
    backend=_broker_url,
    include=[
        "app.tasks.live_pollers",
        "app.tasks.etl_pipeline",
        "app.tasks.games_sync",
        "app.tasks.health",
        "app.tasks.auto_pick",
        "app.tasks.expire_pending_picks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="America/New_York",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=15,
    redis_socket_connect_timeout=15,
    redis_socket_timeout=15,
)

# Use the custom DB-backed scheduler so admin edits to the 7 catalog
# orchestrators' schedules take effect within ~30s without restarting beat.
celery_app.conf.beat_scheduler = "app.core.db_scheduler.DatabaseScheduler"

celery_app.conf.beat_schedule = {
    # === Live pollers (9gk) — fire frequently during games ===
    "mlb-live-poll-every-20s": {
        "task": "app.tasks.live_pollers.poll_mlb_live",
        "schedule": 20.0,
        "options": {"expires": 25},
    },
    "nhl-live-poll-every-20s": {
        "task": "app.tasks.live_pollers.poll_nhl_live",
        "schedule": 20.0,
        "options": {"expires": 25},
    },
    "refresh-prop-watchlist-every-5m": {
        "task": "app.tasks.live_pollers.refresh_prop_watchlist",
        "schedule": 300.0,
    },
    # Popular-games DB cache (Odds API + ESPN broadcast metadata).
    # One Odds API request per sport per run (4 sports). Cap at 3 runs/day
    # to stay within Odds API quota goals.
    "sync-games-cache-thrice-daily": {
        "task": "app.tasks.games_sync.sync_games_cache",
        "schedule": crontab(hour=[6, 14, 22], minute=0),
        "options": {"expires": 10800},
    },
    # === ETL pipeline (u9t) — overnight orchestrator ===
    "nba-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
        "schedule": crontab(hour=3, minute=30),
    },
    "nba-spreads-accuracy-morning": {
        "task": "app.tasks.etl_pipeline.nba.spreads_accuracy",
        "schedule": crontab(hour=5, minute=5),
    },
    # === WNBA ETL pipeline (Phase 1) — added 2026-05-21 ===
    # All entries are season-gated within the task body (May 1 – October 31).
    "wnba-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_wnba_update_pipeline",
        "schedule": crontab(hour=3, minute=0),
    },
    "wnba-update-game-lines-thrice-daily": {
        "task": "app.tasks.etl_pipeline.wnba.update_game_lines",
        "schedule": crontab(hour=[6, 14, 22], minute=10),
        "options": {"expires": 10800},
    },
    "wnba-update-injuries-every-2h": {
        "task": "app.tasks.etl_pipeline.wnba.update_injury_status",
        "schedule": crontab(minute=0, hour="*/2"),
        "options": {"expires": 6600},
    },
    "wnba-projectors-pregame-hourly": {
        "task": "app.tasks.etl_pipeline.run_wnba_update_pipeline",
        "schedule": crontab(minute=0, hour="9-22"),
        "options": {"expires": 7200},
    },
    "wnba-store-actuals-morning": {
        "task": "app.tasks.etl_pipeline.wnba.store_actuals",
        "schedule": crontab(hour=4, minute=0),
    },
    "wnba-totals-accuracy-morning": {
        "task": "app.tasks.etl_pipeline.wnba.totals_accuracy",
        "schedule": crontab(hour=5, minute=0),
    },
    "wnba-spreads-accuracy-morning": {
        "task": "app.tasks.etl_pipeline.wnba.spreads_accuracy",
        "schedule": crontab(hour=5, minute=10),
    },
    # First run at 10 AM ET — MLB probable starters are usually complete by
    # then. Safety net at 2 PM ET catches anything that wasn't posted earlier
    # (the pipeline preserves existing rows when the schedule API is empty,
    # so the later run effectively retries).
    "mlb-statcast-incremental": {
        "task": "app.tasks.etl_pipeline.mlb.statcast_incremental",
        "schedule": crontab(hour=9, minute=30),
    },
    "mlb-profile-rebuild": {
        "task": "app.tasks.etl_pipeline.mlb.rebuild_profiles",
        "schedule": crontab(hour=10, minute=0),
    },
    "mlb-projections-daily": {
        "task": "app.tasks.etl_pipeline.run_mlb_update_pipeline",
        "schedule": crontab(hour=14, minute=0),
    },
    "mlb-projections-safety-net": {
        "task": "app.tasks.etl_pipeline.run_mlb_update_pipeline",
        "schedule": crontab(hour=18, minute=0),
    },
    "mlb-actuals-daily": {
        "task": "app.tasks.etl_pipeline.run_mlb_store_actuals",
        "schedule": crontab(hour=4, minute=30),
    },
    # === Auto-pick orchestrator (Task 14) — gated by AUTO_YETAI_PICKS_ENABLED ===
    # Beat entries below are added conditionally after this dict is built.
    "nfl-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_nfl_update_pipeline",
        "schedule": crontab(hour=4, minute=30),
    },
    "nhl-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_nhl_update_pipeline",
        "schedule": crontab(hour=5, minute=0),
    },
}


import os

# Register Celery signal handlers for admin pipeline notifications. Import
# side effect: @task_prerun / @task_postrun / @task_failure decorators run.
from app.core import celery_signals  # noqa: E402,F401


if os.getenv("AUTO_YETAI_PICKS_ENABLED", "false").lower() == "true":
    celery_app.conf.beat_schedule["auto_pick_yetai_bets_daily"] = {
        "task": "auto_pick.yetai_bets",
        "schedule": crontab(hour=13, minute=0),  # 9:00 AM ET
    }
    celery_app.conf.beat_schedule["expire_pending_yetai_picks"] = {
        "task": "auto_pick.expire_pending",
        "schedule": crontab(minute="*/5"),
    }
