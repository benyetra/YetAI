"""Public League Vault API — unauthenticated read surface + pilot beacons."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.league_vault_events import LvVaultEvent
from app.models.league_vault_models import LvSite
from app.services.league_vault.branding import sanitize_site_display_name
from app.services.league_vault.compute.ensure import ensure_pilot_computed
from app.services.league_vault.publish.snapshot import build_site_snapshot
from app.services.league_vault import redeploy_token as _redeploy_token  # noqa: F401

router = APIRouter(prefix="/api/vault", tags=["league-vault"])

_CACHE = "public, s-maxage=300, stale-while-revalidate=600"


def _assert_no_pii(payload: dict) -> None:
    blob = str(payload)
    for forbidden in ("platform_user_id", "SWID", "espn_s2", "ESPN_S2"):
        if forbidden in blob:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Snapshot leaked forbidden field",
            )


def _public_site(db: Session, slug: str) -> LvSite:
    site = (
        db.query(LvSite).filter(LvSite.slug == slug, LvSite.is_public.is_(True)).first()
    )
    if not site:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vault not found"
        )
    return site


class VaultEventIn(BaseModel):
    path: str = Field(..., max_length=512)
    event_type: str = Field(default="page_view", max_length=64)
    referrer: Optional[str] = Field(default=None, max_length=1024)


@router.get("/{slug}")
def get_vault_site(slug: str, response: Response, db: Session = Depends(get_db)):
    site = _public_site(db, slug)
    # First hit after ingest fills lv_records / all-play without a shell on prod.
    ensure_pilot_computed(db, site)
    try:
        snapshot = build_site_snapshot(db, slug=site.slug)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to build snapshot: {exc}",
        ) from exc
    _assert_no_pii(snapshot)
    response.headers["Cache-Control"] = _CACHE
    return snapshot


@router.get("/{slug}/meta")
def get_vault_meta(slug: str, response: Response, db: Session = Depends(get_db)):
    site = _public_site(db, slug)
    ensure_pilot_computed(db, site)  # heals branding even when records exist
    response.headers["Cache-Control"] = _CACHE
    return {
        "slug": site.slug,
        "display_name": sanitize_site_display_name(site.display_name, slug=site.slug),
        "tagline": site.tagline,
        "first_season": site.first_season,
        "latest_season": site.latest_season,
        "last_place_label": site.last_place_label or "Last Place",
    }


@router.get("/{slug}/lottery")
def get_vault_lottery(
    slug: str,
    response: Response,
    upcoming_season: int | None = None,
    db: Session = Depends(get_db),
):
    """Preview lottery odds (or the locked order if already drawn)."""
    from app.services.league_vault.lottery.service import preview_lottery

    site = _public_site(db, slug)
    try:
        payload = preview_lottery(db, site, upcoming_season=upcoming_season)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    _assert_no_pii(payload)
    if payload.get("status") == "drawn":
        response.headers["Cache-Control"] = _CACHE
    else:
        response.headers["Cache-Control"] = "public, max-age=30"
    return payload


@router.post("/{slug}/lottery/run")
def post_vault_lottery_run(
    slug: str,
    upcoming_season: int | None = None,
    db: Session = Depends(get_db),
):
    """
    Run the weighted draft lottery once for the upcoming season.

    Idempotent: a second run returns the original draw (``already_drawn: true``).
    """
    from app.services.league_vault.lottery.service import run_lottery

    site = _public_site(db, slug)
    try:
        payload = run_lottery(db, site, upcoming_season=upcoming_season)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    _assert_no_pii(payload)
    return payload


@router.post("/{slug}/events", status_code=status.HTTP_204_NO_CONTENT)
def post_vault_event(slug: str, body: VaultEventIn, db: Session = Depends(get_db)):
    """Anonymous beacon for pilot engagement (attributed to league slug)."""
    site = _public_site(db, slug)
    path = body.path.strip() or "/"
    if len(path) > 512:
        path = path[:512]
    event_type = (body.event_type or "page_view").strip()[:64] or "page_view"
    referrer = body.referrer or None
    if referrer and len(referrer) > 1024:
        referrer = referrer[:1024]
    db.add(
        LvVaultEvent(
            site_id=site.id,
            slug=site.slug,
            path=path,
            event_type=event_type,
            referrer=referrer,
            created_at=datetime.utcnow(),
        )
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{slug}/stats")
def get_vault_stats(
    slug: str,
    days: int = 14,
    db: Session = Depends(get_db),
):
    """Aggregate view counts for go/no-go (no PII — path tallies only)."""
    site = _public_site(db, slug)
    window = max(1, min(days, 90))
    since = datetime.utcnow() - timedelta(days=window)
    rows = (
        db.query(LvVaultEvent)
        .filter(
            LvVaultEvent.site_id == site.id,
            LvVaultEvent.created_at >= since,
        )
        .all()
    )
    by_path = Counter(r.path for r in rows)
    by_type = Counter(r.event_type for r in rows)
    return {
        "slug": site.slug,
        "days": window,
        "total_events": len(rows),
        "by_path": dict(by_path.most_common(50)),
        "by_type": dict(by_type),
        "unique_paths": len(by_path),
    }
