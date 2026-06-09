"""
Daily Celery task that runs the auto-pick orchestrator.

Scheduled by celery beat (see celery_app.py): 9:00 AM ET = 13:00 UTC.
On completion, sends an admin notification with the number of pending picks.
"""

import asyncio
import logging
from datetime import datetime

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.providers.moneyline_provider import (
    MoneylineCandidateProvider,
)
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.sources.mlb_hits_source import MLBHitsSource
from app.services.auto_pick.sources.mlb_strikeout_source import MLBStrikeoutSource
from app.services.auto_pick.sources.nba_moneyline_source import NBAMoneylineSource
from app.services.auto_pick.sources.nba_spread_source import NBASpreadSource
from app.services.auto_pick.sources.nba_totals_source import NBATotalsSource
from app.services.auto_pick.sources.nfl_qb_passing_source import NFLQBPassingSource
from app.services.auto_pick.sources.nhl_goalie_saves_source import NHLGoalieSavesSource
from app.services.auto_pick.sources.nhl_totals_source import NHLTotalsSource
from app.services.auto_pick.sources.player_prop_source import PlayerPropSource
from app.services.auto_pick.sources.wnba_player_prop_source import WNBAPlayerPropSource
from app.services.auto_pick.sources.wnba_spread_source import WNBASpreadSource
from app.services.auto_pick.sources.wnba_totals_source import WNBATotalsSource

log = logging.getLogger(__name__)


def _build_providers(db):
    return [
        # NBA
        PlayerPropCandidateProvider(source=PlayerPropSource(db)),
        SpreadCandidateProvider(source=NBASpreadSource(db)),
        TotalsCandidateProvider(source=NBATotalsSource(db)),
        MoneylineCandidateProvider(source=NBAMoneylineSource(db)),
        # MLB
        PlayerPropCandidateProvider(source=MLBStrikeoutSource(db)),
        PlayerPropCandidateProvider(source=MLBHitsSource(db)),
        # NHL
        PlayerPropCandidateProvider(source=NHLGoalieSavesSource(db)),
        TotalsCandidateProvider(source=NHLTotalsSource(db)),
        # NFL
        PlayerPropCandidateProvider(source=NFLQBPassingSource(db)),
        # WNBA
        PlayerPropCandidateProvider(source=WNBAPlayerPropSource(db)),
        SpreadCandidateProvider(source=WNBASpreadSource(db)),
        TotalsCandidateProvider(source=WNBATotalsSource(db)),
    ]


def _notify_admin(subject: str, body: str) -> None:
    """
    Send an admin notification. Uses existing notification_router if it has
    an admin channel; otherwise just logs at INFO level. Does NOT block on a
    failing channel.
    """
    try:
        # No admin notification channel is wired yet (per Development-vir:
        # no Discord; WebSocket + Twilio only). Log at INFO so it surfaces in
        # the worker log and can be tail-followed or shipped to the log aggregator.
        log.info("ADMIN NOTIFICATION: %s — %s", subject, body)
    except Exception:
        log.exception("admin notification failed (non-fatal)")


@celery_app.task(name="auto_pick.yetai_bets")
def auto_pick_yetai_bets():
    db = SessionLocal()
    try:
        orch = AutoPickOrchestrator(
            db=db,
            providers=_build_providers(db),
            now=datetime.utcnow(),
        )
        result = asyncio.run(orch.run())
        _notify_admin(
            subject=f"YetAI auto-picks: {result.pick_count} pending approval",
            body=f"Run {result.id} completed with status {result.status.value}.",
        )
        return {
            "run_id": result.id,
            "picks": result.pick_count,
            "status": result.status.value,
        }
    finally:
        db.close()
