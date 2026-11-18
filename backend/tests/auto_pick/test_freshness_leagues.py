"""Freshness uses each league's own refresh times, and they match the beat schedule."""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

from app.services.auto_pick.candidate import (
    NFL_DAILY_REFRESH_STARTS_ET,
    NFL_WEEKDAY_REFRESH_STARTS_ET,
    NHL_REFRESH_STARTS_ET,
    latest_refresh_start,
    refresh_starts_et,
)
from app.services.auto_pick.selector import hard_gate_reason
from tests.auto_pick.test_selector import _sc

# 2026-11-22 is a Sunday in EST (ET = UTC - 5).
SUNDAY = datetime(2026, 11, 22)


def _utc(et_hour, et_minute=0, day=SUNDAY):
    return day.replace(hour=et_hour, minute=et_minute) + timedelta(hours=5)


def test_nfl_sunday_latest_refresh_is_the_game_day_run():
    assert latest_refresh_start(_utc(13, 30), "NFL") == _utc(12, 30)
    assert latest_refresh_start(_utc(18, 0), "NFL") == _utc(15, 30)
    # Tuesday has only the 04:30 pipeline
    tue = SUNDAY + timedelta(days=2)
    assert latest_refresh_start(_utc(13, 30, tue), "NFL") == _utc(4, 30, tue)
    # NBA at the same time keeps its own schedule
    assert latest_refresh_start(_utc(13, 30), "NBA") == _utc(12, 0)


def test_nhl_latest_refresh():
    assert latest_refresh_start(_utc(18, 0), "NHL") == _utc(16, 45)
    assert latest_refresh_start(_utc(9, 0), "NHL") == _utc(5, 0)


def _gate(league, projected_at, now):
    sc = _sc(
        "e",
        70,
        meta={"projected_at": projected_at, "quoted_at": projected_at},
        commence_time=now + timedelta(hours=2),
    )
    sc.candidate.league = league
    return hard_gate_reason(sc, now, -300, 400)


def test_stale_line_uses_the_candidates_league():
    now = _utc(13, 30)
    # Written by the NFL 12:30 refresh: fresh for NFL...
    assert _gate("NFL", _utc(12, 35), now) is None
    # ...but an NFL row from the 10:00 run is older than the 12:30 refresh.
    assert _gate("NFL", _utc(10, 5), now) == "stale_line"
    # An NHL row from the 12:45 refresh is fresh at 13:30; one from 05:00 is not.
    assert _gate("NHL", _utc(12, 50), now) is None
    assert _gate("NHL", _utc(5, 5), now) == "stale_line"


def _beat_entries(tasks):
    code = (
        "import json; from app.celery_app import celery_app as c; "
        "s = c.conf.beat_schedule; "
        "print(json.dumps([[sorted(e['schedule'].hour), sorted(e['schedule'].minute), "
        "sorted(e['schedule'].day_of_week)] "
        f"for e in s.values() if e['task'] in {tuple(tasks)!r}]))"
    )
    env = {k: v for k, v in os.environ.items() if k != "AUTO_YETAI_PICKS_ENABLED"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _starts_by_weekday(entries):
    """{python weekday: {(h, m)}}; celery day_of_week counts from Sunday = 0."""
    out = {d: set() for d in range(7)}
    for hours, minutes, dows in entries:
        for dow in dows:
            for h in hours:
                for m in minutes:
                    out[(dow - 1) % 7].add((h, m))
    return out


def test_nfl_refresh_starts_match_the_beat_schedule():
    beat = _starts_by_weekday(
        _beat_entries(
            (
                "app.tasks.etl_pipeline.run_nfl_update_pipeline",
                "app.tasks.etl_pipeline.run_nfl_gameday_availability",
            )
        )
    )
    for wd in range(7):
        day = date(2026, 11, 16) + timedelta(days=wd)  # a Monday-to-Sunday week
        assert day.weekday() == wd
        mine = {(t.hour, t.minute) for t in refresh_starts_et("NFL", day)}
        assert mine == beat[wd], (wd, mine, beat[wd])
    assert NFL_DAILY_REFRESH_STARTS_ET and NFL_WEEKDAY_REFRESH_STARTS_ET


def test_nhl_refresh_starts_match_the_beat_schedule():
    beat = _starts_by_weekday(
        _beat_entries(
            (
                "app.tasks.etl_pipeline.run_nhl_update_pipeline",
                "app.tasks.etl_pipeline.run_nhl_pregame_refresh",
            )
        )
    )
    want = {(t.hour, t.minute) for t in NHL_REFRESH_STARTS_ET}
    assert all(beat[wd] == want for wd in range(7)), beat
