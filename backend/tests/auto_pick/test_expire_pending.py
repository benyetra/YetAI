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
    # Implementation fetches all pending rows with a single .filter().all(),
    # then classifies them in Python. Return both rows so the task can decide.
    db.query.return_value.filter.return_value.all.return_value = [
        in_progress,
        past_grace,
        future,
    ]

    with patch("app.tasks.expire_pending_picks.SessionLocal", return_value=db):
        from app.tasks.expire_pending_picks import expire_pending_picks

        count = expire_pending_picks()

    assert count == 1
    assert in_progress.status == "pending_approval"
    assert past_grace.status == "rejected"
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


def test_never_touches_active_rows(sqlite_db):
    from app.models.database_models import BetSource, BetType, YetAIBet

    now = datetime.utcnow()
    for id_, status in (("act", "active"), ("pend", "pending_approval")):
        sqlite_db.add(
            YetAIBet(
                id=id_,
                title="t",
                bet_type=BetType.MONEYLINE,
                selection="s",
                odds=-110.0,
                confidence=70.0,
                status=status,
                source=BetSource.AUTO,
                commence_time=now - timedelta(hours=10),
            )
        )
    sqlite_db.commit()

    class _NoClose:
        def __getattr__(self, name):
            return getattr(sqlite_db, name)

        def close(self):
            pass

    with patch("app.tasks.expire_pending_picks.SessionLocal", return_value=_NoClose()):
        from app.tasks.expire_pending_picks import expire_pending_picks

        assert expire_pending_picks() == 1

    status = {b.id: b.status for b in sqlite_db.query(YetAIBet).all()}
    assert status == {"act": "active", "pend": "rejected"}
