"""Pregame close capture: one odds call per NBA event in the minutes before tip-off.

Runs every 10 min in the evening (celery beat ``nba-close-capture``). An event is captured
once, when its ``commence_time`` falls in ``(now, now + NBA_CLOSE_CAPTURE_LEAD_MIN]``
(default 25) and no snapshot of a capture market was seen inside that window yet. The
snapshot hook in ``odds_api_sync.sync_odds_get`` stores the rows; this task writes nothing.

Cost: credits = markets returned per event, once per event. Default markets are all seven
NBA prop markets we project and price (7 credits per event, priority order below). Before
each event the call is trimmed to the first ``headroom`` markets when the daily budget
(``odds_api_budget``) has less than 7 credits left, and skipped at 0. The events list is
free. Off with ``NBA_CLOSE_CAPTURE_ENABLED=0``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.services import odds_api_budget
from app.services.etl.nba._fanduel_lines import NBA_SPORT, PROP_BOOKS, _get_events
from app.services.odds_api_sync import sync_odds_get

logger = logging.getLogger(__name__)

# Priority order: rebounds and assists (the residual model's targets) survive any trim.
DEFAULT_MARKETS = (
    "player_rebounds,player_assists,player_points,player_threes,"
    "player_points_rebounds_assists,player_steals,player_blocks"
)
_URL = "https://api.the-odds-api.com/v4/sports/basketball_nba/events/{}/odds"


def _enabled() -> bool:
    return os.getenv("NBA_CLOSE_CAPTURE_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _commence(ev: dict) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(ev.get("commence_time")).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


def run(now: Optional[datetime] = None) -> dict:
    """``now`` is naive UTC (tests freeze it)."""
    if not _enabled():
        return {"status": "disabled"}
    from app.core.database import SessionLocal
    from app.models.predictions_models import OddsLineSnapshot as S

    now = now or datetime.utcnow()
    lead = timedelta(minutes=int(os.getenv("NBA_CLOSE_CAPTURE_LEAD_MIN", "25")))
    markets = os.getenv("NBA_CLOSE_CAPTURE_MARKETS", DEFAULT_MARKETS).strip()
    mkt_list = [m for m in markets.split(",") if m.strip()]
    events = _get_events(NBA_SPORT) or []
    out = {
        "status": "ok",
        "events_seen": len(events),
        "captured": 0,
        "skipped_already": 0,
        "skipped_budget": 0,
        "markets_trimmed": 0,
        "credits": 0,
    }
    for ev in events:
        start, eid = _commence(ev), ev.get("id")
        if not eid or start is None or not (now < start <= now + lead):
            continue
        db = SessionLocal()
        try:
            seen = {
                m
                for (m,) in db.query(S.market)
                .filter(
                    S.event_id == eid,
                    S.market.in_(mkt_list),
                    S.last_seen_at >= start - lead,
                )
                .distinct()
            }
        finally:
            db.close()
        # Per market: a market another fetch already saw inside the window has its close;
        # one the books do not offer is asked again on the next run (at most 2 more calls).
        ask = [m for m in mkt_list if m not in seen]
        if not ask:
            out["skipped_already"] += 1
            continue
        used = odds_api_budget._usage()  # None: Redis down, the call is not counted
        if used is not None:
            headroom = odds_api_budget.DAILY_CREDIT_BUDGET - used
            if headroom <= 0:
                out["skipped_budget"] += 1
                continue
            if headroom < len(ask):
                ask = ask[:headroom]
                out["markets_trimmed"] += 1
        resp = sync_odds_get(
            _URL.format(eid),
            params={
                "regions": "us",
                "oddsFormat": "american",
                "markets": ",".join(ask),
                "bookmakers": PROP_BOOKS,
                "apiKey": settings.ODDS_API_KEY,
            },
            caller="etl.nba.close_capture",
            estimated_cost=len(ask),
            raise_for_status=False,
        )
        if resp is None or not resp.ok:
            logger.warning("nba close capture: no odds for event %s", eid)
            continue
        out["captured"] += 1
        try:
            out["credits"] += int(resp.headers.get("x-requests-last", 0) or 0)
        except ValueError:
            pass
    return out
