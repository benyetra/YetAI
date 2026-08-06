"""
ESPN league history ingest via lm-api-reads (cookie auth).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models.league_vault_models import LvSyncJob
from app.services.league_vault.ingest.normalizer import (
    get_or_create_lineage_and_site,
    normalize_espn_season,
)

logger = logging.getLogger(__name__)

ESPN_VIEWS = "mSettings,mTeam,mMatchup,mDraftDetail,mTransactions2"
ESPN_READS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"


def espn_cookies_from_env() -> dict[str, str]:
    """Build ESPN cookie header from ESPN_S2 and ESPN_SWID env vars."""
    s2 = os.environ.get("ESPN_S2") or os.environ.get("ESPN_S2_COOKIE")
    swid = os.environ.get("ESPN_SWID") or os.environ.get("SWID")
    if not s2 or not swid:
        raise ValueError("ESPN_S2 and ESPN_SWID must be set for ESPN ingest")
    return {"espn_s2": s2, "SWID": swid}


def fetch_espn_season(
    client: httpx.Client,
    league_id: str,
    season: int,
) -> dict[str, Any]:
    """
    Fetch one ESPN season. Pre-2018 uses leagueHistory; 2018+ uses seasons endpoint.
    """
    if season < 2018:
        url = (
            f"{ESPN_READS}/leagueHistory/{league_id}"
            f"?seasonId={season}&view={ESPN_VIEWS}"
        )
        data = client.get(url, timeout=60.0)
        data.raise_for_status()
        payload = data.json()
        if isinstance(payload, list) and payload:
            return payload[0]
        return payload if isinstance(payload, dict) else {}

    url = (
        f"{ESPN_READS}/seasons/{season}/segments/0/leagues/{league_id}"
        f"?view={ESPN_VIEWS}"
    )
    resp = client.get(url, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def discover_espn_seasons(
    client: httpx.Client,
    league_id: str,
    start_season: int,
    end_season: int,
) -> list[int]:
    """Return seasons that respond successfully for the league."""
    found: list[int] = []
    for season in range(start_season, end_season + 1):
        try:
            fetch_espn_season(client, league_id, season)
            found.append(season)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue
            logger.warning("ESPN season %s failed: %s", season, exc)
    return found


def espn_league_name_from_payload(payload: dict[str, Any]) -> str | None:
    """ESPN mSettings puts the public league name at ``settings.name``."""
    settings = payload.get("settings") if isinstance(payload, dict) else None
    if not isinstance(settings, dict):
        return None
    name = settings.get("name")
    if isinstance(name, str):
        cleaned = name.strip().strip('"').strip("'")
        return cleaned or None
    return None


def ingest_espn_league(
    db: Session,
    *,
    league_id: str,
    slug: str,
    display_name: str,
    start_season: int,
    end_season: int,
    tagline: str | None = None,
    last_place_label: str | None = "Sacko",
) -> dict[str, Any]:
    """Ingest ESPN league seasons into lv_* tables."""
    cookies = espn_cookies_from_env()
    job = LvSyncJob(
        platform="espn",
        root_platform_league_id=league_id,
        status="running",
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.flush()

    stats: dict[str, Any] = {"seasons": []}
    try:
        with httpx.Client(cookies=cookies) as client:
            seasons = discover_espn_seasons(client, league_id, start_season, end_season)
            lineage, site = get_or_create_lineage_and_site(
                db,
                platform="espn",
                root_platform_league_id=league_id,
                slug=slug,
                display_name=display_name,
                tagline=tagline,
                last_place_label=last_place_label,
            )
            job.lineage_id = lineage.id

            resolved_name: str | None = None
            for season in sorted(seasons):
                payload = fetch_espn_season(client, league_id, season)
                if not resolved_name:
                    resolved_name = espn_league_name_from_payload(payload)
                    if resolved_name and resolved_name != site.display_name:
                        site.display_name = resolved_name
                        site.updated_at = datetime.utcnow()
                        db.add(site)
                        db.flush()
                        stats["display_name"] = resolved_name
                result = normalize_espn_season(
                    db,
                    lineage=lineage,
                    site=site,
                    season=season,
                    platform_league_id=league_id,
                    payload=payload,
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
