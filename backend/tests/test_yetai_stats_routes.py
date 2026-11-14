"""B11 (503 on failure) and B14 (public panel == history stats)."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import main
from app.services import platform_stats as ps
from app.services.yetai_bets_service_db import YetAIBetsServiceDB
from tests.test_yetai_bets_history import _settled


def _boom():
    svc = MagicMock()
    svc.get_yetai_bets_history_for_user.side_effect = RuntimeError("db down")
    svc.get_yetai_bets_for_user.side_effect = RuntimeError("db down")
    return svc


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["history", "live"])
async def test_routes_503_when_service_raises(route):
    user = {"subscription_tier": "free"}
    fn = main.get_yetai_bets_history if route == "history" else main.get_yetai_bets
    with (
        patch.object(main, "is_service_available", return_value=True),
        patch.object(main, "get_service", return_value=_boom()),
        patch("app.core.database.get_db", return_value=iter([MagicMock()])),
    ):
        with pytest.raises(HTTPException) as e:
            await fn(current_user=user)
    assert e.value.status_code == 503
    assert e.value.detail == "YetAI Bets temporarily unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["history", "live"])
async def test_routes_503_when_service_unavailable(route):
    fn = main.get_yetai_bets_history if route == "history" else main.get_yetai_bets
    with patch.object(main, "is_service_available", return_value=False):
        with pytest.raises(HTTPException) as e:
            await fn(current_user={"subscription_tier": "free"})
    assert e.value.status_code == 503


def test_platform_record_equals_history_stats_and_has_label():
    now = datetime.utcnow()
    rows = [
        _settled(1, "won", now - timedelta(days=2)),
        _settled(2, "lost", now - timedelta(days=3)),
        _settled(3, "lost", now - timedelta(days=100)),  # outside 90d
    ]
    svc = YetAIBetsServiceDB()

    def fake(tier, db, statuses, *, since=None, limit=None, order_by="x"):
        return [r for r in rows if r.status in statuses and r.created_at >= since]

    with patch.object(svc, "_query_yetai_bets_for_user", side_effect=fake):
        record = ps.public_record(MagicMock(), service=svc)
        _, hist, _ = svc.get_yetai_bets_history_for_user("elite", None, days=90)
    assert record["label"] == "Last 90 days, all YetAI Bets"
    assert {k: record["stats"][k] for k in ("won", "lost", "win_rate", "units")} == {
        k: hist[k] for k in ("won", "lost", "win_rate", "units")
    }
