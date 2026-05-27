from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch


def _bet(id, commence_time, status="pending_approval"):
    b = MagicMock()
    b.id = id
    b.status = status
    b.commence_time = commence_time
    return b


def test_expires_only_started_pending_picks():
    now = datetime.utcnow()
    started = _bet("a", now - timedelta(minutes=5))
    future = _bet("b", now + timedelta(hours=2))
    db = MagicMock()
    # Implementation fetches all pending rows with a single .filter().all(),
    # then classifies them in Python. Return both rows so the task can decide.
    db.query.return_value.filter.return_value.all.return_value = [started, future]

    with patch("app.tasks.expire_pending_picks.SessionLocal", return_value=db):
        from app.tasks.expire_pending_picks import expire_pending_picks

        count = expire_pending_picks()

    assert count == 1
    assert started.status == "rejected"
    assert future.status == "pending_approval"
    db.commit.assert_called_once()


def test_returns_zero_when_nothing_to_expire():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    with patch("app.tasks.expire_pending_picks.SessionLocal", return_value=db):
        from app.tasks.expire_pending_picks import expire_pending_picks

        count = expire_pending_picks()
    assert count == 0
    db.commit.assert_not_called()
