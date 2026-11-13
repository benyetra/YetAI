"""
Tests for the auto_pick Celery task entry point.

Lightweight: mocks AutoPickOrchestrator and SessionLocal so no real DB or
broker is needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.database_models import AutoPickRunStatus


def test_build_providers_includes_wnba_sources():
    from app.tasks.auto_pick import _build_providers

    db = MagicMock()
    providers = _build_providers(db)
    names = {type(p.source).__name__ for p in providers}
    assert len(providers) == 15
    assert {
        "NHLGoalieSavesSource",
        "WNBAPlayerPropSource",
        "NFLSpreadSource",
        "NFLTotalsSource",
        "NFLReceivingYardsSource",
        "MLBGameMoneylineSource",
    } <= names
    assert "MLBHitsSource" not in names


def test_celery_task_invokes_orchestrator():
    fake_result = MagicMock(id=42, pick_count=2, status=AutoPickRunStatus.SUCCESS)
    with (
        patch("app.tasks.auto_pick.AutoPickOrchestrator") as Orch,
        patch("app.tasks.auto_pick.SessionLocal") as Session,
    ):
        instance = Orch.return_value
        instance.run = AsyncMock(return_value=fake_result)
        Session.return_value = MagicMock()

        from app.tasks.auto_pick import auto_pick_yetai_bets

        result = auto_pick_yetai_bets()

        assert result["run_id"] == 42
        assert result["picks"] == 2
        assert result["status"] == "success"
        Orch.assert_called_once()


def test_celery_task_closes_db_on_exception():
    """DB session is closed even when the orchestrator raises."""
    mock_db = MagicMock()
    with (
        patch("app.tasks.auto_pick.AutoPickOrchestrator") as Orch,
        patch("app.tasks.auto_pick.SessionLocal", return_value=mock_db),
    ):
        Orch.return_value.run = AsyncMock(side_effect=RuntimeError("boom"))

        from app.tasks.auto_pick import auto_pick_yetai_bets
        import pytest

        with pytest.raises(RuntimeError, match="boom"):
            auto_pick_yetai_bets()

        mock_db.close.assert_called_once()


def test_celery_task_returns_status_value():
    """status in return dict is the .value string, not the enum itself."""
    for status in AutoPickRunStatus:
        fake_result = MagicMock(id=1, pick_count=0, status=status)
        with (
            patch("app.tasks.auto_pick.AutoPickOrchestrator") as Orch,
            patch("app.tasks.auto_pick.SessionLocal") as Session,
        ):
            Orch.return_value.run = AsyncMock(return_value=fake_result)
            Session.return_value = MagicMock()

            from app.tasks.auto_pick import auto_pick_yetai_bets

            result = auto_pick_yetai_bets()

            assert result["status"] == status.value
            assert isinstance(result["status"], str)


def test_celery_task_passes_reserve_slots():
    fake_result = MagicMock(id=1, pick_count=2, status=AutoPickRunStatus.SUCCESS)
    with (
        patch("app.tasks.auto_pick.AutoPickOrchestrator") as Orch,
        patch("app.tasks.auto_pick.SessionLocal"),
    ):
        Orch.return_value.run = AsyncMock(return_value=fake_result)
        from app.tasks.auto_pick import auto_pick_yetai_bets

        auto_pick_yetai_bets(reserve_slots=1)
        assert Orch.call_args.kwargs["reserve_slots"] == 1
        auto_pick_yetai_bets()  # admin "fire now" path: no kwargs
        assert Orch.call_args.kwargs["reserve_slots"] == 0


def _beat_keys(flag):
    # Fresh interpreter: the beat block is evaluated at import time.
    import json
    import os
    import subprocess
    import sys

    code = (
        "import json; from app.celery_app import celery_app as c; "
        "s = c.conf.beat_schedule; "
        "print(json.dumps([sorted(k for k in s if k.startswith(('auto_pick', 'expire_pending'))), "
        "s.get('auto_pick_yetai_bets_daily', {}).get('kwargs'), "
        "s.get('auto_pick_yetai_bets_topup', {}).get('kwargs')]))"
    )
    env = {k: v for k, v in os.environ.items() if k != "AUTO_YETAI_PICKS_ENABLED"}
    if flag is not None:
        env["AUTO_YETAI_PICKS_ENABLED"] = flag
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_beat_default_on_morning_reserves_one_slot_evening_none():
    keys, daily, topup = _beat_keys(None)  # flag unset = on
    assert "auto_pick_yetai_bets_daily" in keys and "auto_pick_yetai_bets_topup" in keys
    assert daily == {"reserve_slots": 1} and topup is None


def test_beat_kill_switch_removes_auto_pick_entries():
    for flag in ("false", "0", "no", "OFF"):
        keys, daily, topup = _beat_keys(flag)
        assert "auto_pick_yetai_bets_daily" not in keys and daily is None
        assert "auto_pick_yetai_bets_topup" not in keys
