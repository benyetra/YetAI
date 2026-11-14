"""B6 (settle/auto-pick not schedule-overridable) and B7 (stuck/void alert)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from celery.schedules import crontab
from fastapi import HTTPException

from app.celery_app import celery_app
from app.core.db_scheduler import apply_overrides
from app.data.celery_tasks import FIREABLE_CATALOG
from app.models.database_models import PipelineSchedule
from app.services import pipeline_schedule_overrides as ovr
from app.tasks import yetai_settlement_alert as alert

PROTECTED = ["yetai_bets.settle", "auto_pick.yetai_bets"]


# ---- B6 ----


@pytest.mark.parametrize("task", PROTECTED)
def test_protected_tasks_ignore_overrides_but_stay_fireable(task):
    entry = {"task": task, "schedule": crontab(hour=11, minute=0)}
    for enabled, hour in ((False, 11), (True, 5)):
        o = PipelineSchedule(
            beat_key="k", task_name=task, hour=hour, minute=7, enabled=enabled
        )
        out = apply_overrides({"k": entry}, {"k": o})
        assert out["k"] is entry
    assert task in {e["task_name"] for e in FIREABLE_CATALOG}


def test_real_beat_entries_not_editable_via_admin_api():
    beat = celery_app.conf.beat_schedule
    keys = [k for k, e in beat.items() if e["task"] in PROTECTED]
    assert keys
    for k in keys:
        with pytest.raises(HTTPException):
            ovr.resolve_beat_keys(k)


def test_normal_orchestrator_override_still_applies():
    task = "app.tasks.etl_pipeline.run_nba_update_pipeline"
    entry = {"task": task, "schedule": crontab(hour=3, minute=30)}
    o = PipelineSchedule(beat_key="k", task_name=task, hour=6, minute=15, enabled=True)
    assert apply_overrides({"k": entry}, {"k": o})["k"]["schedule"].hour == {6}


# ---- B7 ----


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def all(self):
        return self.rows


def _bet(id, status, commence=None, created=None, settled=None, result=None):
    return SimpleNamespace(
        id=id,
        status=status,
        commence_time=commence,
        created_at=created or datetime(2026, 1, 1),
        settled_at=settled,
        result=result,
        title="t",
        description="",
        reasoning="",
        selection="s",
    )


NOW = datetime(2026, 11, 13, 12, 0)


def test_collect_counts_stuck_and_voids_skips_demo(monkeypatch):
    rows = [
        _bet("a", "active", commence=NOW - timedelta(hours=30)),  # stuck
        _bet("b", "pending", commence=NOW - timedelta(hours=5)),  # not yet
        _bet("c", "active", created=NOW - timedelta(hours=60)),  # no commence, stuck
        _bet("d", "void", settled=NOW - timedelta(hours=2), result="postponed"),
    ]
    monkeypatch.setattr(alert, "is_demo_yetai_bet", lambda b: False)
    stuck, voids = alert.collect(rows, NOW, stuck_after=timedelta(hours=24))
    assert stuck == ["a", "c"]
    assert voids == [("d", "postponed")]
    monkeypatch.setattr(alert, "is_demo_yetai_bet", lambda b: True)
    assert alert.collect(rows, NOW, stuck_after=timedelta(hours=24)) == ([], [])


@pytest.fixture
def sent(monkeypatch):
    out, last = [], {"sig": None}
    monkeypatch.setattr(alert, "_load_bets", lambda db: [])
    monkeypatch.setattr(alert, "_last_signature", lambda db: last["sig"])

    def send(db, message, signature):
        out.append(message)
        last["sig"] = signature

    monkeypatch.setattr(alert, "_send", send)
    monkeypatch.setattr(
        alert, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.delenv("YETAI_SETTLEMENT_ALERTS_ENABLED", raising=False)

    def run(rows):
        monkeypatch.setattr(alert, "_load_bets", lambda db: rows)
        monkeypatch.setattr(alert, "_now", lambda: NOW)
        monkeypatch.setattr(alert, "is_demo_yetai_bet", lambda b: False)
        return alert.settlement_alert()

    return out, run


def test_no_alert_when_zero(sent):
    out, run = sent
    run([_bet("x", "active", commence=NOW)])
    assert out == []


def test_alert_once_for_stuck_then_dedup(sent):
    out, run = sent
    rows = [_bet("a", "active", commence=NOW - timedelta(hours=30))]
    run(rows)
    run(rows)
    assert len(out) == 1 and "1 stuck" in out[0]


def test_new_void_triggers_new_alert_with_reason(sent):
    out, run = sent
    stuck = _bet("a", "active", commence=NOW - timedelta(hours=30))
    run([stuck])
    v = _bet("v1", "void", settled=NOW - timedelta(hours=1), result="game cancelled")
    run([stuck, v])
    assert len(out) == 2
    assert "v1" in out[1] and "game cancelled" in out[1]


def test_new_stuck_bet_alerts_after_earlier_one_cleared(sent):
    out, run = sent
    stale = NOW - timedelta(hours=30)
    run([_bet("a", "active", commence=stale)])
    run([_bet("a", "won", commence=stale)])  # A settled: back to zero
    run([_bet("b", "active", commence=stale)])  # B stuck: same count as before
    assert len(out) == 2


def test_shrinking_set_does_not_realert(sent):
    out, run = sent
    stale = NOW - timedelta(hours=30)
    old_void = lambda: _bet("v1", "void", settled=NOW - timedelta(hours=23), result="r")  # noqa: E731
    run([_bet("a", "active", commence=stale), _bet("b", "active", commence=stale), old_void()])
    run([_bet("b", "active", commence=stale)])  # A settled and the void aged out
    assert len(out) == 1
    run([_bet("b", "active", commence=stale), _bet("c", "active", commence=stale)])
    assert len(out) == 2


def test_kill_switch(sent, monkeypatch):
    out, run = sent
    monkeypatch.setenv("YETAI_SETTLEMENT_ALERTS_ENABLED", "false")
    run([_bet("a", "active", commence=NOW - timedelta(hours=30))])
    assert out == []


def test_beat_entry_always_on():
    e = celery_app.conf.beat_schedule["yetai-settlement-alert"]
    assert e["task"] == "yetai_bets.settlement_alert"
    assert e["schedule"].minute == {15}
