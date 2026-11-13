"""
Daily Celery task that runs the auto-pick orchestrator.

Scheduled by celery beat (see celery_app.py) at 11:00 and 17:30 ET (celery runs in
America/New_York). The 11:00 run reserves one slot (``reserve_slots=1``) and skips the
fill-to-2 floor; the 17:30 run fills the day to the cap and to 2 from the floor.
On completion, sends an admin notification with the number of published picks
(or pending approval when AUTO_YETAI_PICKS_AUTO_PUBLISH=false).
"""

import asyncio
import logging
import os
from datetime import datetime

from app.celery_app import celery_app
from app.core.database import SessionLocal
from app.services.auto_pick.orchestrator import AutoPickOrchestrator
from app.services.auto_pick.providers.moneyline_provider import (
    MoneylineCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.sources.mlb_game_source import MLBGameMoneylineSource
from app.services.auto_pick.sources.mlb_strikeout_source import MLBStrikeoutSource
from app.services.auto_pick.sources.nba_moneyline_source import NBAMoneylineSource
from app.services.auto_pick.sources.nba_spread_source import NBASpreadSource
from app.services.auto_pick.sources.nba_totals_source import NBATotalsSource
from app.services.auto_pick.sources.nfl_qb_passing_source import NFLQBPassingSource
from app.services.auto_pick.sources.nfl_receiving_yards_source import (
    NFLReceivingYardsSource,
)
from app.services.auto_pick.sources.nfl_spread_source import NFLSpreadSource
from app.services.auto_pick.sources.nfl_totals_source import NFLTotalsSource
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
        MoneylineCandidateProvider(source=MLBGameMoneylineSource(db)),
        # MLBHitsSource is not registered: the hits board stores no market line or
        # price (constant 0.5 / -110), so its picks would publish made-up odds.
        # NHL. Goalie saves need a confirmed starter (probable only with NHL_GOALIE_PROBABLE_PICKS).
        PlayerPropCandidateProvider(source=NHLGoalieSavesSource(db)),
        TotalsCandidateProvider(source=NHLTotalsSource(db)),
        # NFL
        PlayerPropCandidateProvider(source=NFLQBPassingSource(db)),
        PlayerPropCandidateProvider(source=NFLReceivingYardsSource(db)),
        SpreadCandidateProvider(source=NFLSpreadSource(db)),
        TotalsCandidateProvider(source=NFLTotalsSource(db)),
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
def auto_pick_yetai_bets(reserve_slots: int = 0):
    """``reserve_slots``: slots the morning beat run leaves for the evening run."""
    db = SessionLocal()
    try:
        orch = AutoPickOrchestrator(
            db=db,
            providers=_build_providers(db),
            now=datetime.utcnow(),
            reserve_slots=reserve_slots,
        )
        result = asyncio.run(orch.run())
        mode = (
            "published"
            if os.getenv("AUTO_YETAI_PICKS_AUTO_PUBLISH", "true").strip().lower()
            == "true"
            else "pending approval"
        )
        _notify_admin(
            subject=f"YetAI auto-picks: {result.pick_count} {mode}",
            body=f"Run {result.id} completed with status {result.status.value}.",
        )
        return {
            "run_id": result.id,
            "picks": result.pick_count,
            "status": result.status.value,
        }
    finally:
        db.close()
