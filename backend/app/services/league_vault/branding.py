"""Pilot site branding + display hygiene (heal without re-ingest)."""

from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models.league_vault_models import LvManager, LvSite

# Fallbacks when DB still has an ingest placeholder (real names come from ESPN/Sleeper).
PILOT_SITE_NAME_FALLBACKS: dict[str, str] = {
    "mikes-hard": "Mike's Hard Fantasy Football",
    "league-838295": "The Famiglia League",
}

_PLACEHOLDER_SITE_NAME = re.compile(
    r"^(ESPN League|League)\s+\d+$",
    re.IGNORECASE,
)


def _strip_wrapping_quotes(value: str) -> str:
    s = (value or "").strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ("'", '"'):
        return s[1:-1].strip()
    return s


def is_placeholder_site_name(raw: Optional[str]) -> bool:
    cleaned = _strip_wrapping_quotes(raw or "")
    if not cleaned:
        return True
    return bool(_PLACEHOLDER_SITE_NAME.match(cleaned))


def sanitize_site_display_name(raw: Optional[str], *, slug: str) -> str:
    cleaned = _strip_wrapping_quotes(raw or "")
    fallback = PILOT_SITE_NAME_FALLBACKS.get(slug)
    raw_s = raw or ""
    quoted = '"' in raw_s or (
        raw_s.strip().startswith("'") and raw_s.strip().endswith("'")
    )
    if is_placeholder_site_name(cleaned) or quoted:
        return fallback or cleaned or slug
    return cleaned or fallback or slug


def public_manager_display_name(
    raw: Optional[str], *, canonical: Optional[str] = None
) -> str:
    """Prefer human-looking names; collapse bare emails to the local-part."""
    name = (raw or canonical or "").strip()
    name = _strip_wrapping_quotes(name)
    if "@" in name and re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", name):
        return name.split("@", 1)[0]
    return name or "Manager"


def heal_site_branding(db: Session, site: LvSite) -> bool:
    """Persist a cleaned display_name when ingest left quotes / placeholders."""
    desired = sanitize_site_display_name(site.display_name, slug=site.slug)
    if desired and desired != site.display_name:
        site.display_name = desired
        db.add(site)
        db.commit()
        db.refresh(site)
        return True
    return False


def heal_manager_display_names(db: Session, lineage_id: int) -> int:
    """Email-looking display_names → local-part (previous value kept in aliases)."""
    updated = 0
    for mgr in db.query(LvManager).filter_by(lineage_id=lineage_id).all():
        new_name = public_manager_display_name(
            mgr.display_name, canonical=mgr.canonical_name
        )
        if new_name and new_name != mgr.display_name:
            aliases = list(mgr.aliases or [])
            if mgr.display_name and mgr.display_name not in aliases:
                aliases.append(mgr.display_name)
            mgr.aliases = aliases
            mgr.display_name = new_name
            db.add(mgr)
            updated += 1
    if updated:
        db.commit()
    return updated
