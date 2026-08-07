"""
Re-ingest + force-recompute for already-synced League Vault sites.

Used by the weekly Celery job (and optionally ops scripts) so public pilots
stay current with ESPN/Sleeper without a manual sync_pilot pass.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy.orm import Session, joinedload

from app.models.league_vault_models import LvLeagueLineage, LvManager, LvSite
from app.services.league_vault.compute.ensure import ensure_pilot_computed
from app.services.league_vault.ingest.espn_history import ingest_espn_league
from app.services.league_vault.ingest.sleeper_history import (
    SLEEPER_BASE,
    ingest_sleeper_league,
)

logger = logging.getLogger(__name__)


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def auto_sync_enabled() -> bool:
    """Master switch for scheduled vault refresh (default on)."""
    return _env_flag("LEAGUE_VAULT_AUTO_SYNC", default=True)


def _current_fantasy_season(as_of: datetime | None = None) -> int:
    """NFL fantasy season year — Aug–Dec count as the new season."""
    now = as_of or datetime.utcnow()
    return now.year if now.month >= 8 else now.year - 1


def sleeper_tip_from_season_map(season_league_ids: dict | None) -> str | None:
    """Newest known platform league id from lineage.season_league_ids."""
    if not season_league_ids:
        return None
    seasons: list[int] = []
    for key in season_league_ids.keys():
        try:
            seasons.append(int(key))
        except (TypeError, ValueError):
            continue
    if not seasons:
        return None
    tip_season = max(seasons)
    tip = season_league_ids.get(str(tip_season)) or season_league_ids.get(tip_season)
    return str(tip) if tip else None


def discover_sleeper_successor_tip(
    client: httpx.Client,
    *,
    tip_league_id: str,
    manager_platform_ids: list[str],
    season_year: int,
) -> str | None:
    """
    Find a newer Sleeper league whose previous_league_id is the current tip.

    Sleeper only links backward, so new seasons are discovered via a manager's
    league list for the target year.
    """
    for user_id in manager_platform_ids:
        if not user_id:
            continue
        try:
            resp = client.get(
                f"{SLEEPER_BASE}/user/{user_id}/leagues/nfl/{season_year}",
                timeout=30.0,
            )
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            leagues = resp.json() or []
        except Exception as exc:
            logger.debug(
                "sleeper tip discover failed user=%s season=%s: %s",
                user_id,
                season_year,
                exc,
            )
            continue
        for lg in leagues:
            if not isinstance(lg, dict):
                continue
            if str(lg.get("previous_league_id") or "") == str(tip_league_id):
                found = lg.get("league_id")
                if found:
                    return str(found)
            if str(lg.get("league_id") or "") == str(tip_league_id):
                # Tip already is this season — keep it
                return tip_league_id
    return None


def sleeper_tip_league_id(
    db: Session,
    site: LvSite,
    lineage: LvLeagueLineage,
) -> str:
    """Resolve the Sleeper league id to walk (newest tip, not root)."""
    env_slug = (os.environ.get("SLEEPER_SITE_SLUG") or "mikes-hard").strip()
    env_tip = (os.environ.get("SLEEPER_LEAGUE_ID") or "").strip()
    if env_tip and site.slug == env_slug:
        return env_tip

    stored = sleeper_tip_from_season_map(lineage.season_league_ids or {})
    if not stored:
        # Fall back to root — only covers the oldest season
        return str(lineage.root_platform_league_id)

    season_year = _current_fantasy_season()
    mgr_ids = [
        m.platform_user_id
        for m in db.query(LvManager)
        .filter_by(lineage_id=lineage.id, is_active=True)
        .limit(5)
        .all()
    ]
    try:
        with httpx.Client() as client:
            for year in (season_year, season_year + 1):
                nxt = discover_sleeper_successor_tip(
                    client,
                    tip_league_id=stored,
                    manager_platform_ids=mgr_ids,
                    season_year=year,
                )
                if nxt and nxt != stored:
                    logger.info(
                        "league_vault sleeper tip advanced slug=%s %s -> %s (season=%s)",
                        site.slug,
                        stored,
                        nxt,
                        year,
                    )
                    return nxt
    except Exception:
        logger.exception(
            "league_vault sleeper tip discovery failed slug=%s; using stored tip",
            site.slug,
        )
    return stored


def _reingest_site(
    db: Session, site: LvSite, lineage: LvLeagueLineage
) -> dict[str, Any]:
    platform = (lineage.platform or "").lower()
    if platform == "sleeper":
        tip = sleeper_tip_league_id(db, site, lineage)
        return ingest_sleeper_league(
            db,
            league_id=tip,
            slug=site.slug,
            display_name=site.display_name,
            tagline=site.tagline,
            last_place_label=site.last_place_label or "Sacko",
        )
    if platform == "espn":
        end = max(
            _current_fantasy_season(),
            site.latest_season or 0,
            site.first_season or 0,
        )
        start = site.first_season or min(end, 2018)
        # Keep a little history headroom for mid-season create
        if site.first_season is None and lineage.season_league_ids:
            try:
                start = min(int(k) for k in lineage.season_league_ids.keys())
            except ValueError:
                pass
        return ingest_espn_league(
            db,
            league_id=str(lineage.root_platform_league_id),
            slug=site.slug,
            display_name=site.display_name,
            start_season=int(start),
            end_season=int(end),
            tagline=site.tagline,
            last_place_label=site.last_place_label or "Sacko",
        )
    raise ValueError(f"unsupported vault platform: {platform!r}")


def refresh_site(
    db: Session,
    site: LvSite,
    *,
    reingest: bool = True,
    force_compute: bool = True,
) -> dict[str, Any]:
    """Re-ingest (optional) then force all-play + records for one site."""
    lineage = site.lineage
    if lineage is None:
        lineage = db.query(LvLeagueLineage).filter_by(id=site.lineage_id).one()

    out: dict[str, Any] = {
        "slug": site.slug,
        "platform": lineage.platform,
        "reingest": None,
        "compute": None,
    }
    if reingest:
        out["reingest"] = _reingest_site(db, site, lineage)
        db.refresh(site)
        db.refresh(lineage)

    out["compute"] = ensure_pilot_computed(db, site, force=force_compute)
    return out


def refresh_all_public_sites(
    db: Session,
    *,
    reingest: bool = True,
    force_compute: bool = True,
) -> dict[str, Any]:
    """Refresh every public LvSite. Continues past per-site failures."""
    sites = (
        db.query(LvSite)
        .options(joinedload(LvSite.lineage))
        .filter(LvSite.is_public.is_(True))
        .order_by(LvSite.slug.asc())
        .all()
    )
    results: list[dict[str, Any]] = []
    errors = 0
    for site in sites:
        try:
            results.append(
                refresh_site(
                    db,
                    site,
                    reingest=reingest,
                    force_compute=force_compute,
                )
            )
        except Exception as exc:
            errors += 1
            logger.exception("league_vault refresh failed slug=%s", site.slug)
            results.append(
                {
                    "slug": site.slug,
                    "error": str(exc),
                }
            )
            try:
                db.rollback()
            except Exception:
                pass
    return {
        "sites": len(sites),
        "ok": len(sites) - errors,
        "errors": errors,
        "results": results,
    }
