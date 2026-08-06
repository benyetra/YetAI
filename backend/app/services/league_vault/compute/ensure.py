"""Ensure pilot compute (all-play + records) has run for a lineage."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.league_vault_models import LvRecord, LvSeason, LvSite
from app.services.league_vault.branding import (
    heal_manager_display_names,
    heal_site_branding,
)
from app.services.league_vault.compute.records import compute_records_for_lineage
from app.services.league_vault.compute.standings import compute_all_play_for_lineage

logger = logging.getLogger(__name__)


def ensure_pilot_computed(
    db: Session,
    site: LvSite,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Run branding heal + all-play/records if the record book is empty (or ``force``).

    Safe to call on every public snapshot GET — compute no-ops once records exist.
    Branding heal always runs (cheap) so quoted ESPN names get fixed.
    """
    heal_site_branding(db, site)
    heal_manager_display_names(db, site.lineage_id)

    lineage_id = site.lineage_id
    existing = db.query(LvRecord).filter_by(lineage_id=lineage_id).count()
    if existing > 0 and not force:
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
            "league_vault compute slug=%s lineage=%s all_play=%s records=%s force=%s",
            site.slug,
            lineage_id,
            ap,
            len(recs),
            force,
        )
        return {
            "skipped": False,
            "all_play": ap,
            "records": len(recs),
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
