"""Celery broker settings that prevent long MLB tasks from blocking pipelines."""

from app.celery_app import celery_app


def test_redis_visibility_timeout_covers_profile_rebuild():
    """mlb.rebuild_profiles runs 2–3h; default Redis visibility is 1h."""
    opts = celery_app.conf.broker_transport_options or {}
    assert opts.get("visibility_timeout", 3600) >= 43200


def test_mlb_profile_rebuild_is_not_on_beat():
    """Always-on worker must not hold the 5 GB rebuild; Railway cron owns it."""
    assert "mlb-profile-rebuild" not in celery_app.conf.beat_schedule


def test_expire_pending_is_not_on_beat():
    assert "expire_pending_yetai_picks" not in celery_app.conf.beat_schedule


def test_worker_recycles_after_heavy_rss():
    assert celery_app.conf.worker_max_memory_per_child == 800000
    assert celery_app.conf.worker_max_tasks_per_child == 8


def test_mlb_rebuild_profiles_time_limits():
    from app.tasks.etl_pipeline import mlb_rebuild_profiles

    # Soft limit must cover multi-hour Statcast load + 4 window aggregates.
    assert mlb_rebuild_profiles.soft_time_limit >= 14400
    assert mlb_rebuild_profiles.time_limit >= mlb_rebuild_profiles.soft_time_limit
