"""Tests for pipeline_schedule_service.

Read-only serialization of celery_app.conf.beat_schedule for the admin
calendar view. Pure functions; no DB or Celery worker required.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from celery.schedules import crontab

from app.services import pipeline_schedule_service as svc


ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# serialize_crontab
# ---------------------------------------------------------------------------


def test_serialize_crontab_specific_hour_minute():
    """crontab(hour=3, minute=30) → sorted lists for hour/minute, wildcards otherwise."""
    result = svc.serialize_crontab(crontab(hour=3, minute=30))
    assert result == {
        "minute": [30],
        "hour": [3],
        "day_of_week": "*",
        "day_of_month": "*",
        "month_of_year": "*",
    }


def test_serialize_crontab_minute_range():
    """crontab(minute='*/30') expands to {0, 30} on minute; all hours wildcard."""
    result = svc.serialize_crontab(crontab(minute="*/30"))
    assert result["minute"] == [0, 30]
    assert result["hour"] == "*"


def test_serialize_crontab_hour_range():
    """crontab(hour='9-22', minute=0) expands hour into the full range."""
    result = svc.serialize_crontab(crontab(hour="9-22", minute=0))
    assert result["hour"] == list(range(9, 23))
    assert result["minute"] == [0]


# ---------------------------------------------------------------------------
# fire_times_today_et
# ---------------------------------------------------------------------------


def test_fire_times_today_et_single_daily():
    """A 3:30 AM ET crontab fires once today."""
    today = datetime(2026, 5, 23, 10, 0, tzinfo=ET)
    fires = svc.fire_times_today_et(crontab(hour=3, minute=30), now_et=today)
    assert fires == [datetime(2026, 5, 23, 3, 30, tzinfo=ET)]


def test_fire_times_today_et_multiple_hours():
    """crontab(hour='9-22', minute=0) fires 14 times today (9..22 inclusive)."""
    today = datetime(2026, 5, 23, 0, 0, tzinfo=ET)
    fires = svc.fire_times_today_et(crontab(hour="9-22", minute=0), now_et=today)
    assert len(fires) == 14
    assert fires[0] == datetime(2026, 5, 23, 9, 0, tzinfo=ET)
    assert fires[-1] == datetime(2026, 5, 23, 22, 0, tzinfo=ET)


def test_fire_times_today_et_every_30m():
    """*/30 minute crontab fires 48 times in a day."""
    today = datetime(2026, 5, 23, 12, 0, tzinfo=ET)
    fires = svc.fire_times_today_et(crontab(minute="*/30"), now_et=today)
    assert len(fires) == 48


# ---------------------------------------------------------------------------
# human_readable
# ---------------------------------------------------------------------------


def test_human_readable_single_daily():
    """Single hour + single minute → 'Daily at H:MM AM/PM ET'."""
    assert svc.human_readable(crontab(hour=3, minute=30)) == "Daily at 3:30 AM ET"
    assert svc.human_readable(crontab(hour=14, minute=0)) == "Daily at 2:00 PM ET"


def test_human_readable_every_n_minutes():
    """Wildcard hour + */N minute → 'Every N minutes'."""
    assert svc.human_readable(crontab(minute="*/30")) == "Every 30 minutes"


def test_human_readable_hourly_in_range():
    """crontab(hour='9-22', minute=0) → 'Hourly from 9 AM to 10 PM ET'."""
    assert (
        svc.human_readable(crontab(hour="9-22", minute=0))
        == "Hourly from 9 AM to 10 PM ET"
    )


def test_human_readable_every_n_hours():
    """crontab(minute=0, hour='*/2') → 'Every 2 hours'."""
    assert svc.human_readable(crontab(minute=0, hour="*/2")) == "Every 2 hours"


def test_human_readable_falls_back_to_repr_for_unsupported():
    """A complex crontab we don't pretty-print gets the repr form back."""
    result = svc.human_readable(crontab(hour=3, minute=30, day_of_week=1))
    # We don't try to pretty-print weekday filters in v1; result is the raw
    # repr so it's still useful in the UI.
    assert "3" in result and "30" in result


# ---------------------------------------------------------------------------
# serialize_schedule (the top-level entry)
# ---------------------------------------------------------------------------


def test_serialize_schedule_splits_crontab_and_float():
    """beat_schedule entries with crontab go to 'scheduled', floats to 'continuous'."""
    beat = {
        "nba-daily": {
            "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
            "schedule": crontab(hour=3, minute=30),
        },
        "games-cache": {
            "task": "app.tasks.games_sync.sync_games_cache",
            "schedule": 300.0,
            "options": {"expires": 600},
        },
    }
    today = datetime(2026, 5, 23, 0, 0, tzinfo=ET)
    out = svc.serialize_schedule(beat, now_et=today)

    assert len(out["scheduled"]) == 1
    s = out["scheduled"][0]
    assert s["key"] == "nba-daily"
    assert s["task_name"] == "app.tasks.etl_pipeline.run_nba_update_pipeline"
    assert s["schedule_type"] == "crontab"
    assert s["next_fires_today_et"] == ["2026-05-23T03:30:00-04:00"]

    assert len(out["continuous"]) == 1
    c = out["continuous"][0]
    assert c["key"] == "games-cache"
    assert c["interval_seconds"] == 300.0


def test_serialize_schedule_marks_orchestrators():
    """Entries whose task_name is in PIPELINE_ENQUEUE_CATALOG are flagged as orchestrators."""
    beat = {
        "nba-daily": {
            "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
            "schedule": crontab(hour=3, minute=30),
        },
        "nba-accuracy": {
            "task": "app.tasks.etl_pipeline.nba.spreads_accuracy",
            "schedule": crontab(hour=5, minute=5),
        },
    }
    out = svc.serialize_schedule(beat, now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET))
    items = {s["key"]: s for s in out["scheduled"]}
    assert items["nba-daily"]["is_orchestrator"] is True
    # spreads_accuracy is in the catalog as a sub-task entry — also flagged.
    # The deciding question is "is this in PIPELINE_ENQUEUE_CATALOG", which
    # for spreads_accuracy → False (it's not in the catalog, only in beat).
    assert items["nba-accuracy"]["is_orchestrator"] is False


def test_serialize_schedule_uses_auto_pick_label_when_registered():
    beat = {
        "auto-pick-daily": {
            "task": "auto_pick.yetai_bets",
            "schedule": crontab(hour=13, minute=0),
        },
    }
    out = svc.serialize_schedule(beat, now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET))
    assert out["scheduled"][0]["label"] == "YetAI auto-pick (daily)"


def test_serialize_schedule_uses_catalog_label_when_available():
    """Tasks in the catalog get the catalog's friendly label."""
    beat = {
        "nba-daily": {
            "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
            "schedule": crontab(hour=3, minute=30),
        },
    }
    out = svc.serialize_schedule(beat, now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET))
    assert out["scheduled"][0]["label"] == "NBA daily pipeline"


def test_serialize_schedule_demotes_high_frequency_crontab_to_continuous():
    """A crontab that fires >12 times a day (e.g. every 30 min) is treated as
    continuous, not scheduled — otherwise the calendar fills with noise."""
    beat = {
        "every-30m": {
            "task": "x.poll",
            "schedule": crontab(minute="*/30"),
        },
    }
    out = svc.serialize_schedule(beat, now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET))
    assert out["scheduled"] == []
    assert len(out["continuous"]) == 1
    entry = out["continuous"][0]
    assert entry["key"] == "every-30m"
    assert entry["schedule_type"] == "crontab_frequent"
    assert entry["human"] == "Every 30 minutes"


def test_serialize_schedule_flags_overridden_entries():
    """When overrides arg is passed, entries whose task_name has a row get
    is_overridden=True and is_enabled mirrors the row's enabled flag."""

    class _Ovr:
        def __init__(self, enabled):
            self.enabled = enabled

    beat = {
        "nba-daily": {
            "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
            "schedule": crontab(hour=3, minute=30),
        },
    }
    overrides = {"app.tasks.etl_pipeline.run_nba_update_pipeline": _Ovr(enabled=True)}
    out = svc.serialize_schedule(
        beat,
        now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET),
        overrides=overrides,
    )
    entry = out["scheduled"][0]
    assert entry["is_overridden"] is True
    assert entry["is_enabled"] is True


def test_serialize_schedule_no_overrides_arg_marks_all_not_overridden():
    """Backward compatible: omit overrides → is_overridden=False on all."""
    beat = {
        "nba-daily": {
            "task": "app.tasks.etl_pipeline.run_nba_update_pipeline",
            "schedule": crontab(hour=3, minute=30),
        },
    }
    out = svc.serialize_schedule(beat, now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET))
    assert out["scheduled"][0]["is_overridden"] is False
    assert out["scheduled"][0]["is_enabled"] is True


def test_serialize_schedule_sorts_scheduled_by_first_fire_time():
    """Scheduled entries are returned sorted by their first today-fire time."""
    beat = {
        "late": {
            "task": "x.late",
            "schedule": crontab(hour=22, minute=0),
        },
        "early": {
            "task": "x.early",
            "schedule": crontab(hour=3, minute=30),
        },
    }
    out = svc.serialize_schedule(beat, now_et=datetime(2026, 5, 23, 0, 0, tzinfo=ET))
    keys = [s["key"] for s in out["scheduled"]]
    assert keys == ["early", "late"]
