"""YetAI bets history API helpers."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

from app.models.database_models import BetType, SubscriptionTier, YetAIBet
from app.services.yetai_bets_service_db import YetAIBetsServiceDB, _utc_iso


def test_compute_history_stats_win_rate_and_units():
    service = YetAIBetsServiceDB()
    bets = [
        {"status": "won", "odds": "+100"},
        {"status": "won", "odds": "-110"},
        {"status": "lost", "odds": "-110"},
        {"status": "pushed", "odds": "-110"},
    ]
    stats = service.compute_history_stats(bets, period_days=30)
    assert stats["total"] == 4
    assert stats["won"] == 2
    assert stats["lost"] == 1
    assert stats["pushed"] == 1
    assert stats["win_rate"] == 66.7
    assert stats["units"] == 0.91


def test_utc_iso_appends_z_for_naive_datetime():
    dt = datetime(2026, 6, 5, 21, 49, 28)
    assert _utc_iso(dt) == "2026-06-05T21:49:28Z"


def test_history_stats_use_settled_subset_only():
    service = YetAIBetsServiceDB()
    bets = [
        {"status": "won", "odds": "+100"},
        {"status": "pending", "odds": "-110"},
    ]
    stats = service.compute_history_stats(
        [b for b in bets if b["status"] in service.YETAI_HISTORY_STATUSES],
        period_days=90,
    )
    assert stats["total"] == 1
    assert stats["won"] == 1


def _pick(i, status="won", **kw):
    return YetAIBet(
        id=f"p{i}",
        title="t",
        description="",
        bet_type=kw.pop("bet_type", BetType.MONEYLINE),
        selection="Toronto Raptors ML",
        odds=100,
        confidence=80,
        sport="NBA",
        status=status,
        tier_requirement=SubscriptionTier.FREE,
        created_at=datetime.utcnow() - timedelta(minutes=i),
        **kw,
    )


def test_stats_exclude_void_like_push():
    stats = YetAIBetsServiceDB().compute_history_stats(
        [{"status": s, "odds": "+100"} for s in ("won", "lost", "void", "pushed")], 30
    )
    assert (stats["won"], stats["lost"], stats["pushed"], stats["void"]) == (1, 1, 1, 1)
    assert stats["win_rate"] == 50.0 and stats["units"] == 0.0
    assert "void" in YetAIBetsServiceDB.YETAI_HISTORY_STATUSES
    assert "void" in YetAIBetsServiceDB.SUBSCRIBER_VISIBLE_STATUSES


def test_history_stats_cover_whole_window_not_just_returned_rows():
    service = YetAIBetsServiceDB()
    rows = [_pick(i) for i in range(150)] + [_pick(200, "void")]

    def fake(tier, db, statuses, *, since=None, limit=None, order_by="x"):
        picked = [r for r in rows if r.status in statuses]
        return picked[:limit] if limit else picked

    async def call():  # inside a running loop: must not asyncio.run() anywhere
        with patch.object(service, "_query_yetai_bets_for_user", side_effect=fake):
            return service.get_yetai_bets_history_for_user("free", None, limit=100)

    bets, stats, _ = asyncio.run(call())
    assert len(bets) == 100 and stats["returned"] == 100
    assert stats["total"] == 151 and stats["won"] == 150 and stats["void"] == 1
    assert not hasattr(service, "_repair_unified_for_evaluation_yetai_picks")


def test_parlay_legs_in_payload_default_to_pending():
    bet = _pick(
        1,
        "active",
        bet_type=BetType.PARLAY,
        parlay_legs=[
            {
                "sport": "NBA",
                "game": "A @ H",
                "pick": "H ML",
                "odds": "-110",
                "bet_type": "Moneyline",
                "game_id": "g1",
            },
            {"sport": "NBA", "pick": "x", "leg_status": "won", "leg_result": "ok"},
        ],
    )
    legs = YetAIBetsServiceDB()._yetai_bet_to_dict(bet)["parlay_legs"]
    assert legs[0] == {
        "sport": "NBA",
        "game": "A @ H",
        "pick": "H ML",
        "odds": "-110",
        "bet_type": "Moneyline",
        "leg_status": "pending",
        "leg_result": None,
    }
    assert legs[1]["leg_status"] == "won" and legs[1]["leg_result"] == "ok"


# ---- B10 tiles / B11 errors / B14 public panel ----
def _rows_service(rows):
    service = YetAIBetsServiceDB()

    def fake(tier, db, statuses, *, since=None, limit=None, order_by="x"):
        picked = [
            r
            for r in rows
            if r.status in statuses and (since is None or r.created_at >= since)
        ]
        return picked[:limit] if limit else picked

    return service, patch.object(
        service, "_query_yetai_bets_for_user", side_effect=fake
    )


def _settled(i, status, created, odds=100, eff=None):
    b = _pick(
        i,
        status,
        prediction_factors={"settlement": {"effective_odds": eff}} if eff else None,
    )
    b.odds, b.created_at = odds, created
    return b


def test_history_has_today_and_last_7d_blocks():
    now = datetime.utcnow()
    rows = [_settled(1, "lost", now), _settled(2, "lost", now)]
    service, p = _rows_service(rows)
    with p:
        _, _, blocks = service.get_yetai_bets_history_for_user("free", None)
    assert blocks["today"]["win_rate"] == 0.0 and blocks["today"]["graded"] == 2
    assert blocks["last_7d"]["lost"] == 2


def test_no_graded_win_rate_is_none():
    stats = YetAIBetsServiceDB().compute_history_stats([{"status": "void"}], 7)
    assert stats["win_rate"] is None and stats["graded"] == 0


def test_last_7d_uses_effective_odds_and_created_at_window():
    now = datetime.utcnow()
    rows = [
        _settled(1, "won", now - timedelta(days=1), odds=500, eff=100),
        _settled(2, "won", now - timedelta(days=8), odds=100),
    ]
    rows[1].settled_at = now - timedelta(days=1)  # settled recently, created 8d ago
    service, p = _rows_service(rows)
    with p:
        _, _, blocks = service.get_yetai_bets_history_for_user("free", None)
    assert blocks["last_7d"]["total"] == 1 and blocks["last_7d"]["units"] == 1.0
