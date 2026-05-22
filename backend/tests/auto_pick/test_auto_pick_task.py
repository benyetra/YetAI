"""
Tests for the auto_pick Celery task entry point.

Lightweight: mocks AutoPickOrchestrator and SessionLocal so no real DB or
broker is needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from app.models.database_models import AutoPickRunStatus


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
