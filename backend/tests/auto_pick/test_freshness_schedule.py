"""Stale-line gate, latest NBA refresh start, and the beat schedule it must match."""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, time

from app.services.auto_pick.candidate import (
    EVENING_RUN_ET,
    MORNING_RUN_ET,
    NBA_REFRESH_STARTS_ET,
    latest_refresh_start,
)
from app.services.auto_pick.selector import hard_gate_reason
from tests.auto_pick.test_selector import _sc

# 2026-05-22 is in EDT: ET = UTC - 4.
DAY = datetime(2026, 5, 22)


def _utc(hour, minute=0, day=DAY):
    return day.replace(hour=hour, minute=minute)


def test_latest_refresh_start_by_et_time():
    assert latest_refresh_start(_utc(6, 0)) == datetime(
        2026, 5, 21, 22, 30
    )  # 02:00 ET -> 18:30
    assert latest_refresh_start(_utc(15, 0)) == _utc(7, 30)  # 11:00 ET -> 03:30 ET
    assert latest_refresh_start(_utc(17, 30)) == _utc(16, 0)  # 13:30 ET -> 12:00 ET
    assert latest_refresh_start(_utc(22, 0)) == _utc(21, 0)  # 18:00 ET -> 17:00 ET
    assert latest_refresh_start(_utc(23, 0)) == _utc(22, 30)  # 19:00 ET -> 18:30 ET


def test_latest_refresh_start_is_exact_at_the_start_and_handles_winter_time():
    assert latest_refresh_start(_utc(16, 0)) == _utc(16, 0)  # 12:00 ET sharp
    # 2026-11-17 is EST (UTC-5): 03:30 ET = 08:30 UTC.
    assert latest_refresh_start(datetime(2026, 11, 17, 9, 0)) == datetime(
        2026, 11, 17, 8, 30
    )


def test_latest_refresh_start_accepts_aware_now():
    from datetime import timezone

    aware = datetime(2026, 5, 22, 22, 0, tzinfo=timezone.utc)
    assert latest_refresh_start(aware) == _utc(21, 0)


NOW = _utc(17, 30)  # 13:30 ET; latest refresh started 16:00 UTC


def _gate(projected_at=..., now=NOW, **kw):
    meta = {} if projected_at is ... else {"projected_at": projected_at}
    sc = _sc("e", 70, meta=meta, commence_time=now + timedelta(hours=5))
    return hard_gate_reason(sc, now, -300, 400, **kw)


def test_projection_older_than_latest_refresh_is_stale():
    assert _gate(_utc(15, 59)) == "stale_line"


def test_projection_after_the_refresh_start_is_fresh():
    assert _gate(_utc(16, 1)) is None
    assert _gate(_utc(16, 0)) is None  # at the start: the refresh wrote it


def test_projection_older_than_three_hours_is_stale_even_after_a_refresh_start():
    # 18:30 UTC: refresh at 16:00 UTC is the latest; a row from 16:10 is only 2h20m old...
    assert _gate(_utc(16, 10), now=_utc(18, 30)) is None
    # ...but at 19:30 UTC (15:30 ET, still before 17:00 ET) the same row is 3h20m old.
    assert _gate(_utc(16, 10), now=_utc(19, 30)) == "stale_line"


def test_missing_timestamp_is_stale_but_missing_key_is_not_checked():
    assert _gate(None) == "stale_line"
    assert _gate() is None  # sources that do not stamp projected_at


def test_aware_projected_at_is_accepted():
    from datetime import timezone

    assert _gate(datetime(2026, 5, 22, 16, 30, tzinfo=timezone.utc)) is None
    assert _gate(datetime(2026, 5, 22, 15, 0, tzinfo=timezone.utc)) == "stale_line"


def test_fresh_false_skips_the_check():
    assert _gate(_utc(10, 0), fresh=False) is None


_NBA_REFRESH_TASKS = (
    "app.tasks.etl_pipeline.run_nba_update_pipeline",
    "app.tasks.etl_pipeline.run_nba_pregame_refresh",
)


def _beat(env_flag=None):
    code = (
        "import json; from app.celery_app import celery_app as c; "
        "s = c.conf.beat_schedule; "
        "t = lambda k: [sorted(s[k]['schedule'].hour), sorted(s[k]['schedule'].minute)]; "
        "print(json.dumps({"
        f"'refreshes': [t(k) for k, e in s.items() if e['task'] in {_NBA_REFRESH_TASKS!r}], "
        "'daily': t('auto_pick_yetai_bets_daily'), 'topup': t('auto_pick_yetai_bets_topup'), "
        "'daily_kwargs': s['auto_pick_yetai_bets_daily']['kwargs'], "
        "'daily_opts': s['auto_pick_yetai_bets_daily']['options'], "
        "'topup_opts': s['auto_pick_yetai_bets_topup']['options']}))"
    )
    env = {k: v for k, v in os.environ.items() if k != "AUTO_YETAI_PICKS_ENABLED"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _starts(entries):
    return {(h, m) for hours, minutes in entries for h in hours for m in minutes}


def test_refresh_starts_match_every_nba_refresh_beat_entry():
    # Every entry that runs an NBA refresh task, including the 18:30 late refresh.
    scheduled = _starts(_beat()["refreshes"])
    assert scheduled == {(t.hour, t.minute) for t in NBA_REFRESH_STARTS_ET}
    assert (18, 30) in scheduled


def test_no_pick_run_starts_inside_an_nba_refresh_window():
    # A refresh needs up to an hour; a pick run inside that hour would price rows the
    # refresh has not reached (the freshness rule would drop them all as stale_line).
    beat = _beat()
    minutes = lambda h, m: h * 60 + m  # noqa: E731
    for run in _starts([beat["daily"], beat["topup"]]):
        for start in _starts(beat["refreshes"]):
            gap = minutes(*run) - minutes(*start)
            assert not 0 <= gap < 60, (run, start)


def test_auto_pick_runs_at_1330_reserving_one_and_1800():
    beat = _beat()
    assert (MORNING_RUN_ET, EVENING_RUN_ET) == (time(13, 30), time(18, 0))
    assert beat["daily"] == [[13], [30]] and beat["topup"] == [[18], [0]]
    assert beat["daily_kwargs"] == {"reserve_slots": 1}
    assert "expires" in beat["daily_opts"] and "expires" in beat["topup_opts"]


def test_a_fresh_projection_with_an_old_quote_is_stale():
    # The 12:00 refresh re-projected the row but found no quotes: the price is from 03:30.
    sc = _sc(
        "e",
        70,
        meta={"projected_at": _utc(16, 5), "quoted_at": _utc(7, 35)},
        commence_time=NOW + timedelta(hours=5),
    )
    assert hard_gate_reason(sc, NOW, -300, 400) == "stale_line"
    sc.candidate.projection_metadata["quoted_at"] = _utc(16, 5)
    assert hard_gate_reason(sc, NOW, -300, 400) is None
    sc.candidate.projection_metadata["quoted_at"] = None  # no best quote at all
    assert hard_gate_reason(sc, NOW, -300, 400) == "stale_line"
