"""Public League Vault API — unauthenticated read surface."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.league_vault_models import LvSite
from app.services.league_vault.publish.snapshot import build_site_snapshot

router = APIRouter(prefix="/api/vault", tags=["league-vault"])

# Soft cache headers for CDN / browser (pilot traffic is tiny).
_CACHE = "public, s-maxage=300, stale-while-revalidate=600"


def _assert_no_pii(payload: dict) -> None:
    """Defense-in-depth: never emit platform identity fields on the public API."""
    blob = str(payload)
    for forbidden in ("platform_user_id", "SWID", "espn_s2", "ESPN_S2"):
        if forbidden in blob:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Snapshot leaked forbidden field",
            )


@router.get("/{slug}")
def get_vault_site(slug: str, response: Response, db: Session = Depends(get_db)):
    site = (
        db.query(LvSite).filter(LvSite.slug == slug, LvSite.is_public.is_(True)).first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vault not found"
        )
    try:
        snapshot = build_site_snapshot(db, slug=slug)
    except Exception as exc:  # pragma: no cover - surfaced as 500
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build snapshot: {exc}",
        ) from exc
    _assert_no_pii(snapshot)
    response.headers["Cache-Control"] = _CACHE
    return snapshot


@router.get("/{slug}/meta")
def get_vault_meta(slug: str, response: Response, db: Session = Depends(get_db)):
    """Lightweight metadata for OG / middleware existence checks."""
    site = (
        db.query(LvSite).filter(LvSite.slug == slug, LvSite.is_public.is_(True)).first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vault not found"
        )
    response.headers["Cache-Control"] = _CACHE
    return {
        "slug": site.slug,
        "display_name": site.display_name,
        "tagline": site.tagline,
        "first_season": site.first_season,
        "latest_season": site.latest_season,
        "last_place_label": site.last_place_label or "Last Place",
    }
