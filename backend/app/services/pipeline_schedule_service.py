"""Pipeline schedule serialization for the admin calendar view.

Pure functions over `celery_app.conf.beat_schedule`. Read-only: no DB,
no Celery worker invocation. Splits beat entries into:

- "scheduled": ones using `crontab(...)`, renderable as discrete daily
  fire times on a 24-hour timeline.
- "continuous": ones using a float/int seconds interval (live pollers,
  cache refreshers). These don't fit a calendar view.

Edits to the schedule are not supported here — the source of truth is
the Python config. The follow-up PR replaces beat_scheduler with a
DB-backed scheduler so the admin UI can also write.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from celery.schedules import crontab as _crontab_cls

from app.data.celery_tasks import PIPELINE_ENQUEUE_CATALOG

ET = ZoneInfo("America/New_York")


_PIPELINE_LABELS: dict[str, str] = {
    entry["task_name"]: entry["label"] for entry in PIPELINE_ENQUEUE_CATALOG
}
_PIPELINE_SPORTS: dict[str, str] = {
    entry["task_name"]: entry.get("sport", "")
    for entry in PIPELINE_ENQUEUE_CATALOG
    if entry.get("sport")
}
PIPELINE_TASK_NAMES: frozenset[str] = frozenset(_PIPELINE_LABELS.keys())


# Domain sizes for each crontab field, used to detect "wildcard" (the set
# covers every possible value).
# Max fire-times-per-day for a crontab to stay in the "scheduled" calendar
# bucket. Anything firing more often gets bucketed as continuous.
_CRONTAB_CALENDAR_LIMIT = 12


_FIELD_DOMAINS: dict[str, set[int]] = {
    "minute": set(range(60)),
    "hour": set(range(24)),
    "day_of_week": set(range(7)),
    "day_of_month": set(range(1, 32)),
    "month_of_year": set(range(1, 13)),
}


def _field_value(field_set: Any, domain: set[int]) -> Any:
    """Return either '*' (covers whole domain) or a sorted list of ints."""
    if not isinstance(field_set, (set, frozenset)):
        return "*"
    if set(field_set) >= domain:
        return "*"
    return sorted(int(x) for x in field_set)


def serialize_crontab(c: Any) -> dict[str, Any]:
    """Serialize a `celery.schedules.crontab` to a JSON-friendly dict."""
    return {
        "minute": _field_value(c.minute, _FIELD_DOMAINS["minute"]),
        "hour": _field_value(c.hour, _FIELD_DOMAINS["hour"]),
        "day_of_week": _field_value(c.day_of_week, _FIELD_DOMAINS["day_of_week"]),
        "day_of_month": _field_value(c.day_of_month, _FIELD_DOMAINS["day_of_month"]),
        "month_of_year": _field_value(c.month_of_year, _FIELD_DOMAINS["month_of_year"]),
    }


def fire_times_today_et(c: Any, *, now_et: Optional[datetime] = None) -> list[datetime]:
    """Compute the timestamps this crontab fires today (in ET).

    v1 ignores day_of_week / day_of_month / month_of_year filters — every
    schedule we ship today uses defaults for those. If we ever introduce a
    weekday-filtered task we'll need to extend this.
    """
    if now_et is None:
        now_et = datetime.now(ET)
    today = now_et.astimezone(ET).date()
    hours = (
        sorted(int(h) for h in c.hour) if isinstance(c.hour, (set, frozenset)) else [0]
    )
    minutes = (
        sorted(int(m) for m in c.minute)
        if isinstance(c.minute, (set, frozenset))
        else [0]
    )
    return [
        datetime(today.year, today.month, today.day, h, m, tzinfo=ET)
        for h in hours
        for m in minutes
    ]


def human_readable(c: Any) -> str:
    """Render a short English description for the calendar UI.

    Covers the two patterns we actually use:
      - Single hour + single minute → 'Daily at H:MM AM/PM ET'
      - Wildcard hour + every-N-minute → 'Every N minutes'
    Anything else falls back to crontab's repr so the UI still has
    something readable.
    """
    minute_set = c.minute if isinstance(c.minute, (set, frozenset)) else set()
    hour_set = c.hour if isinstance(c.hour, (set, frozenset)) else set()
    hour_is_wild = set(hour_set) >= _FIELD_DOMAINS["hour"]

    if len(minute_set) == 1 and len(hour_set) == 1:
        m = next(iter(minute_set))
        h = next(iter(hour_set))
        ampm = "AM" if h < 12 else "PM"
        display_h = h % 12 or 12
        return f"Daily at {display_h}:{m:02d} {ampm} ET"

    if hour_is_wild and len(minute_set) >= 2:
        sorted_m = sorted(int(x) for x in minute_set)
        # Detect regular intervals (e.g. {0, 30} → step 30).
        if sorted_m[0] == 0:
            step = sorted_m[1] - sorted_m[0]
            expected = list(range(0, 60, step))
            if sorted_m == expected:
                return f"Every {step} minutes"

    # Hour-range with single minute (e.g. crontab(hour='9-22', minute=0)).
    if len(minute_set) == 1 and len(hour_set) >= 2 and not hour_is_wild:
        sorted_h = sorted(int(x) for x in hour_set)
        # Consecutive run → "Hourly from H1 AM/PM to H2 AM/PM ET".
        if sorted_h == list(range(sorted_h[0], sorted_h[-1] + 1)):
            return (
                f"Hourly from {_fmt_hour(sorted_h[0])} to {_fmt_hour(sorted_h[-1])} ET"
            )

    # Every-N-hours (minute=0 + hour stride evenly divides 24).
    if len(minute_set) == 1 and next(iter(minute_set)) == 0 and len(hour_set) >= 2:
        sorted_h = sorted(int(x) for x in hour_set)
        if sorted_h[0] == 0:
            step = sorted_h[1] - sorted_h[0]
            expected = list(range(0, 24, step))
            if sorted_h == expected:
                return f"Every {step} hours"

    return repr(c).strip("<>").strip()


def serialize_schedule(
    beat_schedule: dict[str, dict[str, Any]],
    *,
    now_et: Optional[datetime] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Split a `beat_schedule` dict into scheduled (crontab) and continuous (float).

    Returned shape:
      {
        "scheduled": [
          {key, task_name, label, sport, is_orchestrator, schedule_type,
           crontab, human, next_fires_today_et}
        ],
        "continuous": [
          {key, task_name, label, is_orchestrator, schedule_type,
           interval_seconds, human}
        ]
      }
    `scheduled` is sorted by the first today-fire-time so the calendar can
    render top-down.
    """
    scheduled: list[dict[str, Any]] = []
    continuous: list[dict[str, Any]] = []

    for key, entry in beat_schedule.items():
        task_name = entry.get("task", "")
        is_orch = task_name in PIPELINE_TASK_NAMES
        label = _PIPELINE_LABELS.get(task_name) or _humanize_key(key)
        sport = _PIPELINE_SPORTS.get(task_name) or _sport_from_key(key)
        sched = entry.get("schedule")

        if isinstance(sched, _crontab_cls):
            fires = fire_times_today_et(sched, now_et=now_et)
            # High-frequency crontabs (every 30 min, hourly) would clutter the
            # calendar with dozens of markers. Demote to the continuous panel
            # so the calendar only shows truly daily/twice-daily tasks.
            if len(fires) > _CRONTAB_CALENDAR_LIMIT:
                continuous.append(
                    {
                        "key": key,
                        "task_name": task_name,
                        "label": label,
                        "sport": sport,
                        "is_orchestrator": is_orch,
                        "schedule_type": "crontab_frequent",
                        "crontab": serialize_crontab(sched),
                        "interval_seconds": (86400.0 / len(fires) if fires else 0.0),
                        "human": human_readable(sched),
                    }
                )
            else:
                scheduled.append(
                    {
                        "key": key,
                        "task_name": task_name,
                        "label": label,
                        "sport": sport,
                        "is_orchestrator": is_orch,
                        "schedule_type": "crontab",
                        "crontab": serialize_crontab(sched),
                        "human": human_readable(sched),
                        "next_fires_today_et": [f.isoformat() for f in fires],
                    }
                )
        elif isinstance(sched, (int, float)):
            secs = float(sched)
            continuous.append(
                {
                    "key": key,
                    "task_name": task_name,
                    "label": label,
                    "sport": sport,
                    "is_orchestrator": is_orch,
                    "schedule_type": "interval",
                    "interval_seconds": secs,
                    "human": _humanize_interval(secs),
                }
            )

    scheduled.sort(
        key=lambda s: s["next_fires_today_et"][0] if s["next_fires_today_et"] else ""
    )
    continuous.sort(key=lambda c: c["interval_seconds"])
    return {"scheduled": scheduled, "continuous": continuous}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _fmt_hour(h: int) -> str:
    """12-hour clock with AM/PM, no zero-padding."""
    ampm = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12} {ampm}"


def _humanize_key(key: str) -> str:
    """Turn 'nba-update-pipeline-daily' into 'Nba Update Pipeline Daily'."""
    return key.replace("-", " ").replace("_", " ").title()


def _sport_from_key(key: str) -> str:
    for sport in ("nba", "wnba", "mlb", "nhl", "nfl"):
        if sport in key.lower():
            return sport
    return ""


def _humanize_interval(seconds: float) -> str:
    if seconds < 60:
        return f"Every {int(seconds)} seconds"
    if seconds < 3600:
        m = int(seconds // 60)
        return f"Every {m} minute{'s' if m != 1 else ''}"
    h = seconds / 3600.0
    if h == int(h):
        return f"Every {int(h)} hour{'s' if int(h) != 1 else ''}"
    return f"Every {h:g} hours"
