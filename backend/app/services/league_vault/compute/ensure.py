"""Ensure pilot compute (all-play + records) has run for a lineage."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.league_vault_models import LvLeagueLineage, LvRecord, LvSeason, LvSite
from app.services.league_vault.branding import (
    heal_manager_display_names,
    heal_site_branding,
)
from app.services.league_vault.compute.records import compute_records_for_lineage
from app.services.league_vault.compute.standings import compute_all_play_for_lineage

logger = logging.getLogger(__name__)


def records_stale_after_sync(db: Session, lineage_id: int) -> bool:
    """True when lineage was synced more recently than the record book was built."""
    lineage = db.query(LvLeagueLineage).filter_by(id=lineage_id).one_or_none()
    if lineage is None or lineage.last_synced is None:
        return False
    latest_computed = (
        db.query(func.max(LvRecord.computed_at))
        .filter(LvRecord.lineage_id == lineage_id)
        .scalar()
    )
    if latest_computed is None:
        return True
    # Normalize naive datetimes from SQLite/Postgres
    synced = lineage.last_synced
    computed = latest_computed
    if getattr(synced, "tzinfo", None) is not None:
        synced = synced.replace(tzinfo=None)
    if getattr(computed, "tzinfo", None) is not None:
        computed = computed.replace(tzinfo=None)
    return synced > computed


def ensure_pilot_computed(
    db: Session,
    site: LvSite,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Run branding heal + all-play/records when empty, forced, or stale after sync.

    Safe to call on every public snapshot GET — compute no-ops once records exist
    and are newer than ``lineage.last_synced``. Branding heal always runs (cheap).
    """
    heal_site_branding(db, site)
    heal_manager_display_names(db, site.lineage_id)

    lineage_id = site.lineage_id
    existing = db.query(LvRecord).filter_by(lineage_id=lineage_id).count()
    stale = False
    if existing > 0 and not force:
        stale = records_stale_after_sync(db, lineage_id)
        if not stale:
            return {"skipped": True, "records": existing}

    season_ids = [
        s.id for s in db.query(LvSeason).filter_by(lineage_id=lineage_id).all()
    ]
    if not season_ids:
        return {"skipped": True, "records": 0, "reason": "no_seasons"}

    try:
        ap = compute_all_play_for_lineage(db, lineage_id)
        recs = compute_records_for_lineage(db, lineage_id)
        logger.info(
            "league_vault compute slug=%s lineage=%s all_play=%s records=%s force=%s stale=%s",
            site.slug,
            lineage_id,
            ap,
            len(recs),
            force,
            stale,
        )
        return {
            "skipped": False,
            "all_play": ap,
            "records": len(recs),
            "stale": stale,
            "forced": force,
            "computed_at": datetime.utcnow().isoformat() + "Z",
        }
    except Exception:
        logger.exception(
            "league_vault compute failed slug=%s lineage=%s", site.slug, lineage_id
        )
        try:
            db.rollback()
        except Exception:
            pass
        return {"skipped": False, "error": True, "records": existing}
