"""Resolve platform player ids to display labels for vault snapshots."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ESPN pre-draft order rows use playerId=-1; treat as unset.
_PLACEHOLDER_PLAYER_IDS = frozenset({"", "-1", "0", "none", "null"})

_SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
_ESPN_ATHLETE_URL = (
    "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/athletes/{pid}"
)
_CACHE_DIR = Path(os.environ.get("LV_PLAYER_CACHE_DIR", "/tmp"))
_SLEEPER_CACHE = _CACHE_DIR / "lv_sleeper_nfl_players.json"
_ESPN_CACHE = _CACHE_DIR / "lv_espn_athlete_cache.json"
_SLEEPER_TTL_SEC = 24 * 60 * 60
_ESPN_LOOKUP_WORKERS = 8
_ESPN_LOOKUP_TIMEOUT = 6.0


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
    db: Session, player_ids: set[str], *, allow_http: bool | None = None
) -> dict[str, dict[str, Any]]:
    """Map Sleeper / ESPN player ids → {name, position, nfl_team}.

    Order: DB tables → cached Sleeper NFL catalog (indexed by sleeper + espn id)
    → ESPN core athlete API for leftovers. All steps soft-fail.

    ``allow_http`` defaults on unless ``LV_PLAYER_HTTP=0`` (tests / offline).
    """
    ids = {str(pid) for pid in player_ids if pid}
    if not ids:
        return {}

    if allow_http is None:
        allow_http = os.environ.get("LV_PLAYER_HTTP", "1") != "0"

    out: dict[str, dict[str, Any]] = {}
    _fill_from_db(db, ids, out)

    if not allow_http:
        return out

    missing = ids - set(out.keys())
    if missing:
        catalog = _sleeper_catalog_index()
        for pid in list(missing):
            label = catalog.get(pid)
            if label and label.get("name"):
                out[pid] = label
        missing = ids - set(out.keys())

    if missing:
        for pid, label in _espn_athlete_labels(missing).items():
            if label.get("name"):
                out[pid] = label

    return out


def _fill_from_db(db: Session, ids: set[str], out: dict[str, dict[str, Any]]) -> None:
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
        return

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


def _sleeper_catalog_index() -> dict[str, dict[str, Any]]:
    """Build sleeper_id + espn_id → label map from Sleeper's public NFL catalog."""
    try:
        players = _load_sleeper_players_raw()
    except Exception as exc:
        logger.warning("Sleeper player catalog unavailable: %s", exc)
        return {}

    index: dict[str, dict[str, Any]] = {}
    for sid, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        name = (pdata.get("full_name") or "").strip()
        if not name:
            name = f"{pdata.get('first_name') or ''} {pdata.get('last_name') or ''}".strip()
        if not name:
            continue
        label = {
            "name": name,
            "position": pdata.get("position"),
            "nfl_team": pdata.get("team"),
        }
        index[str(sid)] = label
        eid = pdata.get("espn_id")
        if eid is not None and str(eid).strip():
            index[str(eid)] = label
    return index


def _load_sleeper_players_raw() -> dict[str, Any]:
    if _SLEEPER_CACHE.exists():
        age = time.time() - _SLEEPER_CACHE.stat().st_mtime
        if age < _SLEEPER_TTL_SEC:
            return json.loads(_SLEEPER_CACHE.read_text())

    req = urllib.request.Request(
        _SLEEPER_PLAYERS_URL,
        headers={"User-Agent": "YetAI-LeagueVault/1.0"},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
    data = json.loads(raw)
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _SLEEPER_CACHE.write_bytes(raw)
    except Exception:
        pass
    return data if isinstance(data, dict) else {}


def _espn_athlete_labels(player_ids: set[str]) -> dict[str, dict[str, Any]]:
    cache = _load_espn_cache()
    out: dict[str, dict[str, Any]] = {}
    need: list[str] = []
    for pid in player_ids:
        if pid in cache and cache[pid].get("name"):
            out[pid] = cache[pid]
        else:
            need.append(pid)

    if need:
        with ThreadPoolExecutor(max_workers=_ESPN_LOOKUP_WORKERS) as pool:
            futs = {pool.submit(_fetch_espn_athlete, pid): pid for pid in need}
            for fut in as_completed(futs, timeout=30):
                pid = futs[fut]
                try:
                    label = fut.result()
                except Exception:
                    label = None
                if label and label.get("name"):
                    out[pid] = label
                    cache[pid] = label
        _save_espn_cache(cache)
    return out


def _fetch_espn_athlete(pid: str) -> Optional[dict[str, Any]]:
    url = _ESPN_ATHLETE_URL.format(pid=pid)
    req = urllib.request.Request(url, headers={"User-Agent": "YetAI-LeagueVault/1.0"})
    with urllib.request.urlopen(req, timeout=_ESPN_LOOKUP_TIMEOUT) as resp:
        data = json.loads(resp.read())
    if not isinstance(data, dict):
        return None
    name = (data.get("displayName") or data.get("fullName") or "").strip()
    if not name:
        return None
    pos = data.get("position")
    if isinstance(pos, dict):
        pos = pos.get("abbreviation") or pos.get("name")
    team = data.get("team")
    team_abbr = None
    if isinstance(team, dict):
        team_abbr = team.get("abbreviation")
    return {"name": name, "position": pos, "nfl_team": team_abbr}


def _load_espn_cache() -> dict[str, dict[str, Any]]:
    try:
        if _ESPN_CACHE.exists():
            data = json.loads(_ESPN_CACHE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_espn_cache(cache: dict[str, dict[str, Any]]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _ESPN_CACHE.write_text(json.dumps(cache))
    except Exception:
        pass


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
