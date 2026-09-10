from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


def _bet(id, commence_time, status="pending_approval"):
    b = MagicMock()
    b.id = id
    b.status = status
    b.commence_time = commence_time
    return b


def test_expires_only_after_tipoff_grace_window():
    now = datetime.utcnow()
    in_progress = _bet("a", now - timedelta(hours=1))
    past_grace = _bet("b", now - timedelta(hours=5))
    future = _bet("c", now + timedelta(hours=2))
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        in_progress,
        past_grace,
        future,
    ]

    with patch("app.services.expire_pending_picks.SessionLocal", return_value=db):
        from app.services.expire_pending_picks import expire_unapproved_picks

        count = expire_unapproved_picks()

    assert count == 1
    assert in_progress.status == "pending_approval"
    assert past_grace.status == "rejected"
    assert future.status == "pending_approval"
    db.commit.assert_called_once()


def test_returns_zero_when_nothing_to_expire():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    with patch("app.services.expire_pending_picks.SessionLocal", return_value=db):
        from app.services.expire_pending_picks import expire_unapproved_picks

        count = expire_unapproved_picks()
    assert count == 0
    db.commit.assert_not_called()


def test_celery_task_delegates_to_service():
    with patch(
        "app.tasks.expire_pending_picks.expire_unapproved_picks", return_value=2
    ) as run:
        from app.tasks.expire_pending_picks import expire_pending_picks

        assert expire_pending_picks() == 2
        run.assert_called_once()
