"""One-shot draft lottery service for League Vault."""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.league_vault_models import LvDraftLottery, LvSeason, LvSite
from app.services.league_vault.lottery.odds import (
    LOTTERY_PICKS,
    draw_weighted_order,
)
from app.services.league_vault.lottery.seed import build_seed_snapshot


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "manager"


def resolve_source_and_upcoming(
    db: Session, site: LvSite, upcoming_season: int | None = None
) -> tuple[LvSeason, int]:
    """Source = last finished season; upcoming = source + 1 (or explicit)."""
    seasons = (
        db.query(LvSeason)
        .filter_by(lineage_id=site.lineage_id)
        .order_by(LvSeason.season.desc())
        .all()
    )
    if not seasons:
        raise ValueError("No seasons ingested for this vault")

    finished = [s for s in seasons if s.champion_manager_id is not None]
    source = finished[0] if finished else seasons[0]
    target = upcoming_season if upcoming_season is not None else source.season + 1
    if target <= source.season:
        raise ValueError(
            f"Upcoming season {target} must be after source season {source.season}"
        )
    return source, target


def serialize_lottery(row: LvDraftLottery) -> dict[str, Any]:
    return {
        "upcoming_season": row.upcoming_season,
        "source_season": row.source_season,
        "drawn_at": row.drawn_at.isoformat() + "Z" if row.drawn_at else None,
        "rng_seed": row.rng_seed,
        "lottery_picks": row.lottery_picks,
        "seed_snapshot": row.seed_snapshot,
        "drawn_order": row.drawn_order,
        "status": "drawn",
    }


def preview_lottery(
    db: Session, site: LvSite, *, upcoming_season: int | None = None
) -> dict[str, Any]:
    """Odds board before a draw (or stored result if already drawn)."""
    source, target = resolve_source_and_upcoming(db, site, upcoming_season)
    existing = (
        db.query(LvDraftLottery)
        .filter_by(site_id=site.id, upcoming_season=target)
        .one_or_none()
    )
    if existing:
        return serialize_lottery(existing)

    seed = build_seed_snapshot(db, source)
    return {
        "upcoming_season": target,
        "source_season": source.season,
        "drawn_at": None,
        "rng_seed": None,
        "lottery_picks": LOTTERY_PICKS,
        "seed_snapshot": seed,
        "drawn_order": None,
        "status": "ready",
    }


def run_lottery(
    db: Session, site: LvSite, *, upcoming_season: int | None = None
) -> dict[str, Any]:
    """Run once; later calls return the same immutable result."""
    import secrets

    source, target = resolve_source_and_upcoming(db, site, upcoming_season)
    existing = (
        db.query(LvDraftLottery)
        .filter_by(site_id=site.id, upcoming_season=target)
        .one_or_none()
    )
    if existing:
        out = serialize_lottery(existing)
        out["already_drawn"] = True
        return out

    seed = build_seed_snapshot(db, source)
    field = seed["lottery_field"]
    if not field and not seed["playoff_block"]:
        raise ValueError("No teams available to lottery")

    rng_seed = secrets.token_hex(16)
    seeded = random.Random(rng_seed)

    lottery_order = (
        draw_weighted_order(
            field,
            [int(e["combinations"]) for e in field],
            lottery_picks=LOTTERY_PICKS,
            rng=seeded,
        )
        if field
        else []
    )

    drawn_order: list[dict[str, Any]] = []
    pick = 1
    for entry in lottery_order:
        drawn_order.append(
            {
                "pick": pick,
                "via": "lottery" if pick <= LOTTERY_PICKS else "lottery_fallback",
                **{k: entry[k] for k in entry if k != "group"},
                "group": "lottery",
            }
        )
        pick += 1
    for entry in seed["playoff_block"]:
        drawn_order.append(
            {
                "pick": pick,
                "via": "playoff_reverse",
                **{k: entry[k] for k in entry if k != "group"},
                "group": "playoff",
            }
        )
        pick += 1

    for row in drawn_order:
        if not row.get("manager_slug") and row.get("display_name"):
            row["manager_slug"] = _slugify(str(row["display_name"]))

    record = LvDraftLottery(
        site_id=site.id,
        upcoming_season=target,
        source_season=source.season,
        drawn_at=datetime.utcnow(),
        rng_seed=rng_seed,
        seed_snapshot=seed,
        drawn_order=drawn_order,
        lottery_picks=LOTTERY_PICKS,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    out = serialize_lottery(record)
    out["already_drawn"] = False
    return out
