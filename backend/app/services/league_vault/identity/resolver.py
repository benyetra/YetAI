"""Manager identity resolution + manual override seed application."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.league_vault_models import LvManager


def apply_identity_overrides(
    db: Session,
    *,
    lineage_id: int,
    overrides: list[dict[str, Any]],
) -> dict[str, int]:
    """Apply hand overrides from a seed file.

    Override shape::
        {
          "platform_user_id": "...",
          "canonical_name": "...",          # optional
          "display_name": "...",            # optional
          "aliases": ["..."],               # optional, merged
          "merge_into_platform_user_id": null | "..."  # optional future
        }
    """
    updated = 0
    skipped = 0
    for row in overrides or []:
        pid = str(row.get("platform_user_id") or "")
        if not pid:
            skipped += 1
            continue
        mgr = (
            db.query(LvManager)
            .filter_by(lineage_id=lineage_id, platform_user_id=pid)
            .first()
        )
        if not mgr:
            skipped += 1
            continue
        if row.get("canonical_name"):
            mgr.canonical_name = row["canonical_name"]
        if row.get("display_name"):
            if mgr.display_name and mgr.display_name != row["display_name"]:
                aliases = list(mgr.aliases or [])
                if mgr.display_name not in aliases:
                    aliases.append(mgr.display_name)
                mgr.aliases = aliases
            mgr.display_name = row["display_name"]
        if row.get("aliases"):
            aliases = list(mgr.aliases or [])
            for a in row["aliases"]:
                if a and a not in aliases:
                    aliases.append(a)
            mgr.aliases = aliases
        # merge_into reserved for P2+ when two platform ids are the same person
        _ = row.get("merge_into_platform_user_id")
        updated += 1
    db.commit()
    return {"updated": updated, "skipped": skipped}


def load_overrides_file(path: str) -> list[dict[str, Any]]:
    """Load overrides from JSON seed file. Expected: {\"overrides\": [...]} or a list."""
    import json
    from pathlib import Path

    raw = json.loads(Path(path).read_text())
    if isinstance(raw, list):
        return raw
    return list(raw.get("overrides") or [])


def summarize_managers(db: Session, lineage_id: int) -> list[dict[str, Any]]:
    """Return managers for hand-inspection (pilot deliverable)."""
    rows = (
        db.query(LvManager)
        .filter_by(lineage_id=lineage_id)
        .order_by(LvManager.display_name)
        .all()
    )
    return [
        {
            "id": m.id,
            "platform_user_id": m.platform_user_id,
            "canonical_name": m.canonical_name,
            "display_name": m.display_name,
            "aliases": m.aliases or [],
            "first_season": m.first_season,
            "last_season": m.last_season,
            "is_active": m.is_active,
        }
        for m in rows
    ]
