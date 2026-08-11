"""Injury / availability filtering for NFL anytime-TD starters."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

UNAVAILABLE_STATUSES = frozenset({"Out", "Doubtful"})
_QUESTIONABLE_MULT = 0.75
_OUT_ALIASES = frozenset(
    {
        "out",
        "ir",
        "injured reserve",
        "pup",
        "physically unable to perform",
        "suspended",
        "exempt",
        "nf1",  # rare nflverse tag
    }
)


def normalize_injury_status(status: Any) -> str | None:
    """Map nflverse report/practice status → Out / Doubtful / Questionable / Healthy."""
    if status is None:
        return None
    try:
        if status != status:  # NaN
            return None
    except Exception:
        pass
    text = str(status).strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in {"full participation", "active", "healthy"}:
        return "Healthy"
    if "did not participate" in lowered:
        return "Out"
    if any(alias in lowered for alias in _OUT_ALIASES) or lowered == "out":
        return "Out"
    if "doubt" in lowered:
        return "Doubtful"
    if "question" in lowered:
        return "Questionable"
    if "participation" in lowered:
        return "Healthy"
    return text.title()[:20]


def is_unavailable_status(status: str | None) -> bool:
    if status is None:
        return False
    normalized = normalize_injury_status(status) or status
    return normalized in UNAVAILABLE_STATUSES or normalized == "Out"


def availability_multiplier(status: str | None) -> float:
    """1.0 healthy, 0.75 questionable, 0.0 out/doubtful."""
    if status is None:
        return 1.0
    normalized = normalize_injury_status(status) or status
    if is_unavailable_status(normalized):
        return 0.0
    if normalized == "Questionable":
        return _QUESTIONABLE_MULT
    return 1.0


def latest_injury_status_by_player(
    injury_records: Iterable[Mapping[str, Any]],
    *,
    week: int,
) -> dict[str, str]:
    """Latest report_status per GSIS id for weeks ≤ target (prefer exact week)."""
    best: dict[str, tuple[int, str]] = {}
    for raw in injury_records:
        player_id = str(raw.get("gsis_id") or raw.get("player_id") or "").strip()
        if not player_id:
            continue
        try:
            report_week = int(float(raw.get("week") or 0))
        except (TypeError, ValueError):
            continue
        if report_week <= 0 or report_week > week:
            continue
        status = normalize_injury_status(
            raw.get("report_status") or raw.get("practice_status")
        )
        if not status:
            continue
        prev = best.get(player_id)
        if prev is None or report_week >= prev[0]:
            best[player_id] = (report_week, status)
    return {pid: status for pid, (_w, status) in best.items()}


def _depth_candidate(raw: Mapping[str, Any], *, week: int) -> dict[str, Any] | None:
    from app.services.etl.nfl.anytime_td_features import (
        SKILL_POSITIONS,
        _num,
        _str,
    )

    pos = _str(raw, "position", "pos_abb").upper()
    if pos not in SKILL_POSITIONS:
        return None
    team = _str(raw, "club_code", "team").upper()
    player_id = _str(raw, "gsis_id", "player_id")
    if not team or not player_id:
        return None
    depth_week = int(_num(raw, "week", default=week))
    if depth_week > week:
        return None
    depth_team = int(_num(raw, "depth_team", "pos_rank", default=99))
    depth_pos = _str(raw, "depth_position", default=pos).upper()
    return {
        "player_id": player_id,
        "player_name": _str(raw, "full_name", "football_name", "player_name"),
        "position": pos,
        "team_abbr": team,
        "depth_team": depth_team,
        "depth_week": depth_week,
        "depth_position": depth_pos,
    }


def _promote_backup(
    *,
    team: str,
    position: str,
    depth_position: str,
    depth_records: Iterable[Mapping[str, Any]],
    injury_by_player: Mapping[str, str],
    week: int,
    exclude_ids: set[str],
) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for raw in depth_records:
        cand = _depth_candidate(raw, week=week)
        if cand is None:
            continue
        if cand["team_abbr"] != team or cand["position"] != position:
            continue
        if cand["depth_position"] != depth_position and depth_position:
            # Allow RB/FB flex when starter slot was RB
            if not (
                position == "RB"
                and cand["depth_position"] in {"RB", "FB"}
                and depth_position in {"RB", "FB"}
            ):
                continue
        if cand["player_id"] in exclude_ids:
            continue
        if cand["depth_team"] < 2:
            continue
        status = injury_by_player.get(cand["player_id"])
        if is_unavailable_status(status):
            continue
        candidates.append(cand)
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["depth_team"], -c["depth_week"]))
    pick = dict(candidates[0])
    pick["availability_mult"] = availability_multiplier(
        injury_by_player.get(pick["player_id"])
    )
    pick["injury_status"] = injury_by_player.get(pick["player_id"])
    pick["promoted_from_backup"] = True
    return pick


def apply_availability_to_universe(
    universe: list[dict[str, Any]],
    *,
    injury_by_player: Mapping[str, str],
    depth_records: Iterable[Mapping[str, Any]],
    week: int,
) -> list[dict[str, Any]]:
    """Drop Out/Doubtful starters (promote depth-2 when possible); tag Questionable."""
    depth_list = [dict(r) for r in depth_records]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for player in universe:
        player_id = str(player.get("player_id") or "")
        status = injury_by_player.get(player_id)
        mult = availability_multiplier(status)
        if mult <= 0.0:
            promoted = _promote_backup(
                team=str(player.get("team_abbr") or "").upper(),
                position=str(player.get("position") or "").upper(),
                depth_position=str(
                    player.get("depth_position") or player.get("position") or ""
                ).upper(),
                depth_records=depth_list,
                injury_by_player=injury_by_player,
                week=week,
                exclude_ids={player_id},
            )
            if promoted and promoted["player_id"] not in seen:
                out.append(promoted)
                seen.add(promoted["player_id"])
            continue
        row = dict(player)
        row["injury_status"] = status
        row["availability_mult"] = mult
        if player_id and player_id not in seen:
            out.append(row)
            seen.add(player_id)
    return out


def load_injury_records(season: int) -> list[dict[str, Any]]:
    """Load nflverse injury reports for ``season`` (empty on missing parquet)."""
    from app.services.etl.nfl.anytime_td_features import (
        _is_missing_nflverse_data_error,
        _import_nfl,
        records_from_dataframe,
    )

    url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"injuries/injuries_{season}.parquet"
    )
    try:
        import pandas as pd

        frame = pd.read_parquet(url)
        return records_from_dataframe(frame)
    except Exception as exc:
        if not _is_missing_nflverse_data_error(exc):
            logger.info(
                "injuries parquet failed for %s (%s); trying nfl_data_py", season, exc
            )
        else:
            logger.info("injuries parquet missing for %s; trying nfl_data_py", season)

    try:
        nfl = _import_nfl()
        return records_from_dataframe(nfl.import_injuries([int(season)]))
    except Exception as exc:
        logger.warning("nflverse injuries unavailable for %s: %s", season, exc)
        return []
