"""PBP red-zone / goal-line aggregators for NFL anytime-TD features.

Pure functions operate on plain play dicts so unit tests need no network.
Live loads use nflverse ``play_by_play_{season}.parquet`` (same source as fantasy
player analytics).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

RZ_YARDLINE = 20
GL_YARDLINE = 5
_TEAM_RZ_PASS_RATE_PRIOR = 0.52
_EARLY_DOWN_PASS_PRIOR = 0.48
_TEAM_RZ_TRIPS_PRIOR = 3.2


def _num(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key not in row or row[key] is None:
            continue
        try:
            return float(row[key])
        except (TypeError, ValueError):
            continue
    return default


def _str(row: dict[str, Any], *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if val is None:
            continue
        text = str(val).strip()
        if text and text.lower() not in {"nan", "none"}:
            return text
    return ""


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _is_flag(row: dict[str, Any], key: str) -> bool:
    val = row.get(key)
    if val is None:
        return False
    try:
        return int(val) == 1
    except (TypeError, ValueError):
        return bool(val)


def filter_red_zone_plays(
    plays: Iterable[dict[str, Any]], *, max_yardline: int = RZ_YARDLINE
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for play in plays:
        yl = _num(play, "yardline_100", default=-1)
        if yl < 0:
            continue
        if yl <= max_yardline:
            out.append(play)
    return out


def filter_goal_line_plays(
    plays: Iterable[dict[str, Any]], *, max_yardline: int = GL_YARDLINE
) -> list[dict[str, Any]]:
    return filter_red_zone_plays(plays, max_yardline=max_yardline)


def aggregate_team_rz_from_pbp(
    plays: Iterable[dict[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, Any]]:
    """Team RZ trips / pass rate from prior-week PBP (yardline_100 ≤ 20).

    Trips ≈ distinct ``drive`` ids per team-week (fallback: unique play count / 4).
    """
    rz = [
        p
        for p in filter_red_zone_plays(plays)
        if 0 < int(_num(p, "week", default=0)) < as_of_week
    ]
    # team -> week -> set(drive ids) and pass/rush counts
    drives: dict[str, dict[int, set[Any]]] = {}
    pass_n: dict[str, float] = {}
    rush_n: dict[str, float] = {}
    weeks: dict[str, set[int]] = {}
    play_counts: dict[str, dict[int, int]] = {}

    for play in rz:
        team = _str(play, "posteam").upper()
        week = int(_num(play, "week", default=0))
        if not team or week <= 0:
            continue
        weeks.setdefault(team, set()).add(week)
        play_counts.setdefault(team, {})
        play_counts[team][week] = play_counts[team].get(week, 0) + 1
        drive = play.get("drive")
        drives.setdefault(team, {}).setdefault(week, set())
        if drive is not None and str(drive).lower() not in {"nan", "none", ""}:
            drives[team][week].add(drive)
        if _is_flag(play, "pass"):
            pass_n[team] = pass_n.get(team, 0.0) + 1.0
        if _is_flag(play, "rush"):
            rush_n[team] = rush_n.get(team, 0.0) + 1.0

    out: dict[str, dict[str, Any]] = {}
    for team, week_set in weeks.items():
        n_games = max(len(week_set), 1)
        trip_total = 0.0
        for week in week_set:
            d = drives.get(team, {}).get(week) or set()
            if d:
                trip_total += float(len(d))
            else:
                # ~4 RZ plays ≈ 1 trip when drive id missing
                trip_total += float(play_counts.get(team, {}).get(week, 0)) / 4.0
        trips_pg = trip_total / n_games
        scored = pass_n.get(team, 0.0) + rush_n.get(team, 0.0)
        pass_rate = (
            pass_n.get(team, 0.0) / scored if scored > 0 else _TEAM_RZ_PASS_RATE_PRIOR
        )
        out[team] = {
            "team_rz_trips": _clamp(trips_pg, 1.5, 6.0),
            "team_rz_pass_rate": _clamp(pass_rate, 0.35, 0.75),
            "early_down_pass_pct": _EARLY_DOWN_PASS_PRIOR,
            "team_tds_per_game": None,  # filled by weekly overlay when available
        }
    return out


def aggregate_player_rz_from_pbp(
    plays: Iterable[dict[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, Any]]:
    """Player RZ targets/carries/share and GL carries from prior-week PBP."""
    rz = [
        p
        for p in filter_red_zone_plays(plays)
        if 0 < int(_num(p, "week", default=0)) < as_of_week
    ]
    gl = [
        p
        for p in filter_goal_line_plays(plays)
        if 0 < int(_num(p, "week", default=0)) < as_of_week
    ]

    team_week_touches: dict[tuple[str, int], float] = {}
    for play in rz:
        team = _str(play, "posteam").upper()
        week = int(_num(play, "week", default=0))
        if not team or week <= 0:
            continue
        if _is_flag(play, "pass") or _is_flag(play, "rush"):
            key = (team, week)
            team_week_touches[key] = team_week_touches.get(key, 0.0) + 1.0

    targets: dict[str, float] = {}
    carries: dict[str, float] = {}
    player_team_week: dict[str, tuple[str, int]] = {}

    for play in rz:
        week = int(_num(play, "week", default=0))
        team = _str(play, "posteam").upper()
        if _is_flag(play, "pass"):
            pid = _str(play, "receiver_player_id")
            if pid:
                targets[pid] = targets.get(pid, 0.0) + 1.0
                player_team_week[pid] = (team, week)
        if _is_flag(play, "rush"):
            pid = _str(play, "rusher_player_id")
            if pid:
                carries[pid] = carries.get(pid, 0.0) + 1.0
                player_team_week[pid] = (team, week)

    gl_carries: dict[str, float] = {}
    for play in gl:
        if not _is_flag(play, "rush"):
            continue
        pid = _str(play, "rusher_player_id")
        if pid:
            gl_carries[pid] = gl_carries.get(pid, 0.0) + 1.0

    player_ids = set(targets) | set(carries) | set(gl_carries)
    out: dict[str, dict[str, Any]] = {}
    for pid in player_ids:
        t = targets.get(pid, 0.0)
        c = carries.get(pid, 0.0)
        touches = t + c
        share = None
        team_week = player_team_week.get(pid)
        if team_week is not None:
            # Season share vs all prior team RZ touches for that team
            team = team_week[0]
            team_total = sum(
                v for (tm, _w), v in team_week_touches.items() if tm == team
            )
            if team_total > 0:
                share = touches / team_total
        out[pid] = {
            "rz_targets": t,
            "gl_carries": gl_carries.get(pid, 0.0),
            "rz_touches": touches,
            "player_rz_share": (
                _clamp(float(share), 0.02, 0.55) if share is not None else None
            ),
        }
    return out


def records_from_dataframe(frame: Any) -> list[dict[str, Any]]:
    if frame is None:
        return []
    if isinstance(frame, list):
        return [dict(r) for r in frame]
    if hasattr(frame, "to_dict"):
        return [dict(r) for r in frame.to_dict(orient="records")]
    return []


def load_pbp_records_nflverse(season: int) -> list[dict[str, Any]]:
    """Load nflverse PBP rows for one season (empty list on 404 / failure)."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas required for nflverse PBP load") from exc

    url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"pbp/play_by_play_{season}.parquet"
    )
    columns = [
        "week",
        "posteam",
        "yardline_100",
        "pass",
        "rush",
        "receiver_player_id",
        "rusher_player_id",
        "drive",
    ]
    try:
        frame = pd.read_parquet(url, columns=columns)
    except Exception as exc:
        logger.warning("nflverse PBP unavailable for %s: %s", season, exc)
        return []
    if frame is None or getattr(frame, "empty", False):
        return []
    return records_from_dataframe(frame)


def load_pbp_records_with_fallback(
    season: int, *, max_lookback: int = 3
) -> tuple[list[dict[str, Any]], int | None]:
    """Load PBP for ``season``, walking back on missing parquet."""
    for candidate in range(season, season - max_lookback - 1, -1):
        if candidate < 1999:
            break
        records = load_pbp_records_nflverse(candidate)
        if records:
            if candidate < season:
                logger.warning(
                    "nflverse PBP for %s unavailable; using %s for RZ priors",
                    season,
                    candidate,
                )
            return records, candidate
    return [], None
