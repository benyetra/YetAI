"""Odds credit run-out alert: once per UTC day, only when running out before reset."""

from datetime import date

import pytest

from app.tasks import odds_credit_alert as t

TODAY = date(2026, 11, 15)


def _summary(before=True, **kw):
    return {
        "remaining": 12345,
        "rate_7d": 650.0,
        "rate_source": "bill",
        "projected_runout": "2026-12-02",
        "next_reset": "2026-12-14",
        "recommended_daily": 300,
        "runs_out_before_reset": before,
        **kw,
    }


@pytest.fixture
def env(monkeypatch):
    class DB:
        def close(self):
            pass

    st = {"sent": [], "last": None, "summary": _summary(), "quota": {"remaining": 1}}
    monkeypatch.setattr(t, "SessionLocal", lambda: DB())
    monkeypatch.setattr(t, "read_live_quota", lambda: st["quota"])
    monkeypatch.setattr(t.cr, "snapshot_quota", lambda q, d: None)
    monkeypatch.setattr(t.cr, "utc_today", lambda: TODAY)
    monkeypatch.setattr(t.cr, "credits_summary", lambda d, q: st["summary"])
    monkeypatch.setattr(t, "_last_alert", lambda db, name: st["last"])

    def send(db, msg, sig, **kw):
        st["sent"].append((msg, sig, kw))
        st["last"] = type("R", (), {"extra": {"signature": sig}})()

    monkeypatch.setattr(t, "_send", send)
    monkeypatch.delenv("ODDS_CREDIT_ALERTS_ENABLED", raising=False)
    return st


def test_sends_once_per_day(env):
    assert t.runout_alert()["sent"] is True
    assert t.runout_alert() == {"sent": False, "reason": "already sent today"}
    msg, sig, kw = env["sent"][0]
    assert sig == "odds-runout:2026-11-15" and kw["task_name"] == t.TASK_NAME
    assert msg == (
        "[YetAI] Odds API credits: 12,345 left, ~650/day (bill, 7d) -> run out "
        "~2026-12-02, before reset 2026-12-14. Recommended daily budget 300."
    )
    env["last"].extra["signature"] = "odds-runout:2026-11-14"  # yesterday's
    assert t.runout_alert()["sent"] is True


def test_quiet_when_runout_after_reset(env):
    env["summary"] = _summary(before=False)
    assert t.runout_alert()["sent"] is False and not env["sent"]


def test_quiet_when_quota_unavailable(env):
    env["quota"] = None
    assert t.runout_alert()["reason"] == "quota unavailable" and not env["sent"]


def test_kill_switch(env, monkeypatch):
    monkeypatch.setenv("ODDS_CREDIT_ALERTS_ENABLED", "false")
    assert t.runout_alert() == {"sent": False, "reason": "disabled"}
    assert not env["sent"]


def test_beat_entry():
    from app.celery_app import celery_app

    e = celery_app.conf.beat_schedule["odds_credits_runout_alert"]
    assert e["task"] == t.TASK_NAME
    assert (e["schedule"].hour, e["schedule"].minute) == ({9}, {40})
