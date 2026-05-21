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
    # Popular-games DB cache (Odds API + ESPN broadcast metadata)
    "sync-games-cache-every-3h": {
        "task": "app.tasks.games_sync.sync_games_cache",
        "schedule": 10800.0,  # 3 hours — matches GamesSyncService design
    },
    # === ETL pipeline (u9t) — overnight orchestrator ===
    "nba-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
        "schedule": crontab(hour=3, minute=30),
    },
    # First run at 10 AM ET — MLB probable starters are usually complete by
    # then. Safety net at 2 PM ET catches anything that wasn't posted earlier
    # (the pipeline preserves existing rows when the schedule API is empty,
    # so the later run effectively retries).
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
    "nfl-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_nfl_update_pipeline",
        "schedule": crontab(hour=4, minute=30),
    },
    "nhl-update-pipeline-daily": {
        "task": "app.tasks.etl_pipeline.run_nhl_update_pipeline",
        "schedule": crontab(hour=5, minute=0),
    },
}
