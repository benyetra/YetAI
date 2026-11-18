"""Beat entries must all carry `expires`, and the NFL MNF/TNF refreshes run before the 17:30 pick."""

import importlib
import os

from app import celery_app as mod
from app.core.db_scheduler import apply_overrides

S = mod.celery_app.conf.beat_schedule


def test_every_entry_has_expires():
    assert all("expires" in e["options"] for e in S.values())


def test_auto_pick_entries_keep_their_expiry():
    picks = [e for e in S.values() if e["task"].startswith("auto_pick.yetai_bets")]
    assert picks and all(e["options"]["expires"] == 10800 for e in picks)


def test_pipelines_get_default():
    for k in (
        "nba-update-pipeline-daily",
        "nfl-update-pipeline-daily",
        "nhl-update-pipeline-daily",
    ):
        assert S[k]["options"]["expires"] == mod.DEFAULT_BEAT_EXPIRES_S


def test_helper_keeps_existing_and_fills_missing():
    d = {"a": {"task": "x"}, "b": {"task": "y", "options": {"expires": 5}}}
    mod.apply_default_expires(d)
    assert d["a"]["options"]["expires"] == mod.DEFAULT_BEAT_EXPIRES_S
    assert d["b"]["options"]["expires"] == 5


def test_mlb_wnba_entries_covered(monkeypatch):
    monkeypatch.setenv("MLB_JOBS_ENABLED", "true")
    monkeypatch.setenv("WNBA_JOBS_ENABLED", "true")
    try:
        m = importlib.reload(mod)
        sched = m.celery_app.conf.beat_schedule
        assert (
            "mlb-projections-daily" in sched and "wnba-update-pipeline-daily" in sched
        )
        assert all("expires" in e["options"] for e in sched.values())
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_db_scheduler_override_keeps_options():
    class O:
        enabled, hour, minute = True, 4, 0

    out = apply_overrides(S, {"nba-update-pipeline-daily": O()})
    assert (
        out["nba-update-pipeline-daily"]["options"]["expires"]
        == mod.DEFAULT_BEAT_EXPIRES_S
    )


def _cron(key):
    c = S[key]["schedule"]
    return (min(c.hour), min(c.minute), min(c.day_of_week))


def test_nfl_mon_thu_refresh_before_last_pick():
    assert _cron("nfl-gameday-availability-mon-pre-pick") == (17, 0, 1)
    assert _cron("nfl-gameday-availability-thu-pre-pick") == (17, 0, 4)
    # informational MNF run moved off the 18:00 pick run
    assert _cron("nfl-gameday-availability-mon") == (18, 15, 1)
    assert _cron("nfl-gameday-availability-thu-pm") == (19, 0, 4)
