"""
Sleeper league history ingest: walk previous_league_id chain oldest→newest.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.league_vault_models import LvLeagueLineage, LvSyncJob
from app.services.league_vault.ingest.normalizer import (
    get_or_create_lineage_and_site,
    normalize_sleeper_season,
)

logger = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"


def _get_json(client: httpx.Client, path: str) -> Any:
    resp = client.get(f"{SLEEPER_BASE}{path}", timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def walk_league_chain(client: httpx.Client, league_id: str) -> list[str]:
    """
    Walk previous_league_id links from newest league back to root.
    Returns league ids oldest→newest.
    """
    chain: list[str] = []
    seen: set[str] = set()
    current = league_id
    while current and current not in seen:
        seen.add(current)
        chain.append(current)
        league = _get_json(client, f"/league/{current}")
        current = league.get("previous_league_id")
    chain.reverse()
    return chain


def fetch_season_bundle(client: httpx.Client, league_id: str) -> dict[str, Any]:
    """Fetch league, rosters, users, all matchups, drafts, transactions, brackets."""
    league = _get_json(client, f"/league/{league_id}")
    rosters = _get_json(client, f"/league/{league_id}/rosters")
    users = _get_json(client, f"/league/{league_id}/users")
    transactions = _get_json(
        client, f"/league/{league_id}/transactions/{league.get('season', 0)}"
    )

    matchups_by_week: dict[int, list] = {}
    reg_weeks = (league.get("settings") or {}).get("reg_season_count") or 14
    playoff_weeks = (league.get("settings") or {}).get(
        "playoff_week_start"
    ) or reg_weeks + 4
    for week in range(1, int(playoff_weeks) + 1):
        try:
            rows = _get_json(client, f"/league/{league_id}/matchups/{week}")
            if rows:
                matchups_by_week[week] = rows
        except httpx.HTTPStatusError:
            break

    drafts: list[dict] = []
    for draft_id in league.get("draft_id") and [league["draft_id"]] or []:
        try:
            draft = _get_json(client, f"/draft/{draft_id}")
            picks = _get_json(client, f"/draft/{draft_id}/picks")
            draft["picks"] = picks
            drafts.append(draft)
        except httpx.HTTPStatusError as exc:
            logger.warning("Draft fetch failed for %s: %s", draft_id, exc)

    winners_bracket = None
    losers_bracket = None
    try:
        winners_bracket = _get_json(client, f"/league/{league_id}/winners_bracket")
    except httpx.HTTPStatusError:
        pass
    try:
        losers_bracket = _get_json(client, f"/league/{league_id}/losers_bracket")
    except httpx.HTTPStatusError:
        pass

    return {
        "league": league,
        "rosters": rosters,
        "users": users,
        "matchups_by_week": matchups_by_week,
        "drafts": drafts,
        "transactions": transactions if isinstance(transactions, list) else [],
        "winners_bracket": winners_bracket,
        "losers_bracket": losers_bracket,
    }


def ingest_sleeper_league(
    db: Session,
    *,
    league_id: str,
    slug: str,
    display_name: str,
    tagline: str | None = None,
    last_place_label: str | None = "Sacko",
) -> dict[str, Any]:
    """
    Ingest full Sleeper league chain (oldest season first) into lv_* tables.
    """
    job = LvSyncJob(
        platform="sleeper",
        root_platform_league_id=league_id,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.flush()

    stats: dict[str, Any] = {"seasons": []}
    try:
        with httpx.Client() as client:
            chain = walk_league_chain(client, league_id)
            root_id = chain[0] if chain else league_id
            lineage, site = get_or_create_lineage_and_site(
                db,
                platform="sleeper",
                root_platform_league_id=root_id,
                slug=slug,
                display_name=display_name,
                tagline=tagline,
                last_place_label=last_place_label,
            )
            job.lineage_id = lineage.id

            for lid in chain:
                bundle = fetch_season_bundle(client, lid)
                league = bundle["league"]
                season = int(league.get("season") or 0)
                result = normalize_sleeper_season(
                    db,
                    lineage=lineage,
                    site=site,
                    season=season,
                    platform_league_id=lid,
                    league=league,
                    rosters=bundle["rosters"],
                    users=bundle["users"],
                    matchups_by_week=bundle["matchups_by_week"],
                    drafts=bundle["drafts"],
                    transactions=bundle["transactions"],
                    winners_bracket=bundle["winners_bracket"],
                    losers_bracket=bundle["losers_bracket"],
                )
                stats["seasons"].append(result)

        db.commit()
        job.status = "success"
        job.stats = stats
        job.finished_at = datetime.utcnow()
        db.commit()
        return stats
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.utcnow()
        db.add(job)
        db.commit()
        raise
