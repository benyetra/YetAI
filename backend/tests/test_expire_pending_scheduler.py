from unittest.mock import patch

from app.services.expire_pending_scheduler import ExpirePendingScheduler


def test_scheduler_stays_off_when_flag_disabled(monkeypatch):
    monkeypatch.delenv("AUTO_YETAI_PICKS_ENABLED", raising=False)
    sched = ExpirePendingScheduler()
    sched.start()
    assert sched._running is False
    assert sched._task is None


def test_scheduler_starts_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_YETAI_PICKS_ENABLED", "true")
    sched = ExpirePendingScheduler()
    with patch("app.services.expire_pending_scheduler.asyncio.create_task") as create:
        create.return_value = object()
        sched.start()
    assert sched._running is True
    create.assert_called_once()
