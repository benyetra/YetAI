"""Celery broker settings that prevent long MLB tasks from blocking pipelines."""

from app.celery_app import celery_app


def test_redis_visibility_timeout_covers_profile_rebuild():
    """mlb.rebuild_profiles runs 2–3h; default Redis visibility is 1h."""
    opts = celery_app.conf.broker_transport_options or {}
    assert opts.get("visibility_timeout", 3600) >= 43200


def test_mlb_profile_rebuild_scheduled_before_projections():
    schedule = celery_app.conf.beat_schedule
    rebuild_hour = min(schedule["mlb-profile-rebuild"]["schedule"].hour)
    projections_hour = min(schedule["mlb-projections-daily"]["schedule"].hour)
    assert rebuild_hour < projections_hour


def test_mlb_rebuild_profiles_time_limits():
    from app.tasks.etl_pipeline import mlb_rebuild_profiles

    # Soft limit must cover multi-hour Statcast load + 4 window aggregates.
    assert mlb_rebuild_profiles.soft_time_limit >= 14400
    assert mlb_rebuild_profiles.time_limit >= mlb_rebuild_profiles.soft_time_limit
