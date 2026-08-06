"""Resolve platform player ids to display labels for vault snapshots."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

# ESPN pre-draft order rows use playerId=-1; treat as unset.
_PLACEHOLDER_PLAYER_IDS = frozenset({"", "-1", "0", "none", "null"})


def normalize_draft_player_id(raw: Any) -> Optional[str]:
    """Return a real platform player id, or None for blanks / ESPN placeholders."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in _PLACEHOLDER_PLAYER_IDS:
        return None
    try:
        if int(s) < 0:
            return None
    except ValueError:
        pass
    return s


def resolve_player_labels(
    db: Session, player_ids: set[str]
) -> dict[str, dict[str, Any]]:
    """Map Sleeper / ESPN player ids → {name, position, nfl_team}.

    Soft-fails if ``sleeper_players`` / ``fantasy_players`` are missing or empty.
    ESPN draft ids are matched via ``SleeperPlayer.espn_id`` when present.
    """
    ids = {str(pid) for pid in player_ids if pid}
    if not ids:
        return {}

    out: dict[str, dict[str, Any]] = {}

    try:
        from app.models.database_models import SleeperPlayer
        from sqlalchemy import or_

        rows = (
            db.query(SleeperPlayer)
            .filter(
                or_(
                    SleeperPlayer.sleeper_player_id.in_(list(ids)),
                    SleeperPlayer.espn_id.in_(list(ids)),
                )
            )
            .all()
        )
        for row in rows:
            label = _label_from_sleeper(row)
            if not label.get("name"):
                continue
            sid = str(row.sleeper_player_id or "")
            eid = str(row.espn_id or "") if row.espn_id else ""
            if sid and sid in ids:
                out[sid] = label
            if eid and eid in ids:
                out[eid] = label
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    missing = ids - set(out.keys())
    if not missing:
        return out

    try:
        from app.models.fantasy_models import FantasyPlayer

        rows = (
            db.query(FantasyPlayer)
            .filter(FantasyPlayer.platform_player_id.in_(list(missing)))
            .all()
        )
        for row in rows:
            pid = str(row.platform_player_id or "")
            if not pid or pid in out:
                continue
            name = (row.name or "").strip()
            if not name:
                continue
            pos = (
                getattr(row.position, "value", None) or str(row.position or "") or None
            )
            out[pid] = {
                "name": name,
                "position": pos,
                "nfl_team": row.team,
            }
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    return out


def _label_from_sleeper(row: Any) -> dict[str, Optional[str]]:
    name = (row.full_name or "").strip()
    if not name:
        name = f"{row.first_name or ''} {row.last_name or ''}".strip()
    return {
        "name": name or None,
        "position": row.position,
        "nfl_team": row.team,
    }


def apply_player_labels_to_picks(
    picks: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> None:
    """Attach player_name / position / nfl_team onto draft pick dicts in place."""
    for pick in picks:
        label = labels.get(str(pick.get("player_id") or "")) or {}
        pick["player_name"] = label.get("name")
        pick["player_position"] = label.get("position")
        pick["player_nfl_team"] = label.get("nfl_team")
