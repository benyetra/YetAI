import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.celery_app import celery_app
from app.services import bet_scheduler_service as bss
from app.services.bet_scheduler_service import BetSchedulerService, ScheduleConfig
from app.services.game_sync_service import GameSyncService
from app.tasks import settle_yetai_bets as task_mod

YETAI = {"success": True, "verified": 2, "settled": 1}


def test_task_returns_service_result():
    svc = MagicMock(verify_pending_yetai_bets=MagicMock(return_value=YETAI))
    with patch.object(task_mod, "YetAIBetsServiceDB", return_value=svc):
        assert task_mod.settle_yetai_bets() == YETAI


def test_task_swallows_exceptions():
    svc = MagicMock(verify_pending_yetai_bets=MagicMock(side_effect=RuntimeError("x")))
    with patch.object(task_mod, "YetAIBetsServiceDB", return_value=svc):
        assert task_mod.settle_yetai_bets() == {"success": False, "error": "x"}


def test_beat_entry():
    e = celery_app.conf.beat_schedule["settle-yetai-bets"]
    assert e["task"] == "yetai_bets.settle"
    assert e["options"] == {"expires": 600}
    assert e["schedule"]._orig_minute == "*/15"
    assert "app.tasks.settle_yetai_bets" in celery_app.conf.include


def _run(quiet, unified):
    svc = MagicMock(verify_pending_yetai_bets=MagicMock(return_value=YETAI))
    sched = BetSchedulerService(ScheduleConfig(max_retries=0))
    with (
        patch.object(bss, "YetAIBetsServiceDB", return_value=svc),
        patch.object(bss, "unified_bet_verification_service", unified),
        patch.object(sched, "_is_quiet_hours", return_value=quiet),
        patch("app.core.database.SessionLocal"),
        patch(
            "app.services.player_prop_verification_service.PlayerPropVerificationService"
        ) as props,
    ):
        props.return_value.verify_pending_unified_props = AsyncMock(
            return_value={"verified": 0, "settled": 0}
        )
        out = asyncio.run(sched._run_verification())
    return svc, out


def test_yetai_runs_when_unified_raises():
    unified = MagicMock(verify_all_pending_bets=AsyncMock(side_effect=RuntimeError))
    svc, _ = _run(False, unified)
    svc.verify_pending_yetai_bets.assert_called_once()


def test_yetai_runs_in_quiet_hours_and_skips_unified():
    unified = MagicMock(verify_all_pending_bets=AsyncMock())
    svc, out = _run(True, unified)
    svc.verify_pending_yetai_bets.assert_called_once()
    unified.verify_all_pending_bets.assert_not_awaited()
    assert out["success"] and out["yetai_bets"]["settled"] == 1


def test_sync_scores_without_api_key_skips():
    with patch("app.services.game_sync_service.SessionLocal") as sl:
        svc = GameSyncService()
        svc.odds_api_service = None
        out = asyncio.run(svc.sync_game_scores())
    assert out["status"] == "skipped" and out["reason"] == "no_api_key"
    sl.assert_not_called()
    assert not hasattr(svc, "sync_game_scores_mock")


def test_settlement_core_is_sync_and_async_callers_use_a_thread():
    import inspect

    from app.services.yetai_bets_service_db import YetAIBetsServiceDB

    assert not inspect.iscoroutinefunction(YetAIBetsServiceDB.verify_pending_yetai_bets)
    for mod in ("app/services/bet_scheduler_service.py", "app/main.py"):
        src = open(mod).read()
        assert (
            "asyncio.to_thread(" in src
            and "await yetai_service.verify_pending_yetai_bets()" not in src
        )


def test_scheduler_runs_settlement_off_the_event_loop():
    import threading

    seen = {}

    def record():
        seen["thread"] = threading.current_thread()
        return YETAI

    unified = MagicMock(
        verify_all_pending_bets=AsyncMock(return_value={"success": True})
    )
    svc = MagicMock(verify_pending_yetai_bets=MagicMock(side_effect=record))
    sched = BetSchedulerService(ScheduleConfig(max_retries=0))
    with (
        patch.object(bss, "YetAIBetsServiceDB", return_value=svc),
        patch.object(bss, "unified_bet_verification_service", unified),
        patch.object(sched, "_is_quiet_hours", return_value=True),
    ):
        asyncio.run(sched._run_verification())
    assert seen["thread"] is not threading.main_thread()
