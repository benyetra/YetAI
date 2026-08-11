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
            val = float(row[key])
        except (TypeError, ValueError):
            continue
        if val != val:  # NaN
            continue
        return val
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
    """Team RZ trips / pass rate / early-down pass% from prior-week PBP."""
    rz = [
        p
        for p in filter_red_zone_plays(plays)
        if 0 < int(_num(p, "week", default=0)) < as_of_week
    ]
    # team -> week -> set(drive ids) and pass/rush counts
    drives: dict[str, dict[int, set[Any]]] = {}
    pass_n: dict[str, float] = {}
    rush_n: dict[str, float] = {}
    early_pass: dict[str, float] = {}
    early_plays: dict[str, float] = {}
    weeks: dict[str, set[int]] = {}
    play_counts: dict[str, dict[int, int]] = {}
    gl_rush: dict[str, float] = {}
    gl_plays: dict[str, float] = {}

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
        down = int(_num(play, "down", default=0))
        if down in {1, 2} and (_is_flag(play, "pass") or _is_flag(play, "rush")):
            early_plays[team] = early_plays.get(team, 0.0) + 1.0
            if _is_flag(play, "pass"):
                early_pass[team] = early_pass.get(team, 0.0) + 1.0
        yl = _num(play, "yardline_100", default=99)
        if yl <= GL_YARDLINE and (_is_flag(play, "pass") or _is_flag(play, "rush")):
            gl_plays[team] = gl_plays.get(team, 0.0) + 1.0
            if _is_flag(play, "rush"):
                gl_rush[team] = gl_rush.get(team, 0.0) + 1.0

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
        early_n = early_plays.get(team, 0.0)
        early_pct = (
            early_pass.get(team, 0.0) / early_n
            if early_n > 0
            else _EARLY_DOWN_PASS_PRIOR
        )
        gl_n = gl_plays.get(team, 0.0)
        gl_rush_rate = gl_rush.get(team, 0.0) / gl_n if gl_n > 0 else 0.55
        out[team] = {
            "team_rz_trips": _clamp(trips_pg, 1.5, 6.0),
            "team_rz_pass_rate": _clamp(pass_rate, 0.35, 0.75),
            "early_down_pass_pct": _clamp(early_pct, 0.30, 0.70),
            "team_gl_rush_rate": _clamp(gl_rush_rate, 0.25, 0.85),
            "team_tds_per_game": None,  # filled by weekly overlay when available
        }
    return out


def resolve_position_rz_share(
    *,
    position: str | None,
    rz_rush_share: float | None,
    rz_target_share: float | None,
    gl_carry_share: float | None,
    blended_share: float | None,
) -> float | None:
    """Pick RZ share for λ: RBs use rush+GL; WR/TE use targets; else blended."""
    pos = str(position or "").strip().upper()
    if pos == "RB":
        rush = rz_rush_share if rz_rush_share is not None else blended_share
        if rush is None and gl_carry_share is None:
            return None
        if rush is None:
            return _clamp(float(gl_carry_share), 0.02, 0.55)  # type: ignore[arg-type]
        if gl_carry_share is None:
            return _clamp(float(rush), 0.02, 0.55)
        return _clamp(0.70 * float(rush) + 0.30 * float(gl_carry_share), 0.02, 0.55)
    if pos in {"WR", "TE"}:
        share = rz_target_share if rz_target_share is not None else blended_share
        return _clamp(float(share), 0.02, 0.55) if share is not None else None
    if blended_share is not None:
        return _clamp(float(blended_share), 0.02, 0.55)
    return None


def aggregate_player_rz_from_pbp(
    plays: Iterable[dict[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, Any]]:
    """Player RZ targets/carries/share and GL carries from prior-week PBP.

    Emits rush/target/GL shares so callers can pick position-appropriate λ inputs.
    Rates are also normalized per prior game for GBM stability.
    """
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

    prior_games = max(as_of_week - 1, 1)
    team_week_touches: dict[tuple[str, int], float] = {}
    team_rz_rushes: dict[str, float] = {}
    team_rz_passes: dict[str, float] = {}
    team_gl_rushes: dict[str, float] = {}
    for play in rz:
        team = _str(play, "posteam").upper()
        week = int(_num(play, "week", default=0))
        if not team or week <= 0:
            continue
        if _is_flag(play, "pass") or _is_flag(play, "rush"):
            key = (team, week)
            team_week_touches[key] = team_week_touches.get(key, 0.0) + 1.0
        if _is_flag(play, "rush"):
            team_rz_rushes[team] = team_rz_rushes.get(team, 0.0) + 1.0
        if _is_flag(play, "pass"):
            team_rz_passes[team] = team_rz_passes.get(team, 0.0) + 1.0

    targets: dict[str, float] = {}
    carries: dict[str, float] = {}
    player_team: dict[str, str] = {}
    player_weeks: dict[str, set[int]] = {}
    gl_tds: dict[str, float] = {}

    for play in rz:
        week = int(_num(play, "week", default=0))
        team = _str(play, "posteam").upper()
        if _is_flag(play, "pass"):
            pid = _str(play, "receiver_player_id")
            if pid:
                targets[pid] = targets.get(pid, 0.0) + 1.0
                player_team[pid] = team
                player_weeks.setdefault(pid, set()).add(week)
        if _is_flag(play, "rush"):
            pid = _str(play, "rusher_player_id")
            if pid:
                carries[pid] = carries.get(pid, 0.0) + 1.0
                player_team[pid] = team
                player_weeks.setdefault(pid, set()).add(week)

    gl_carries: dict[str, float] = {}
    for play in gl:
        if not _is_flag(play, "rush"):
            continue
        pid = _str(play, "rusher_player_id")
        if not pid:
            continue
        team = _str(play, "posteam").upper()
        gl_carries[pid] = gl_carries.get(pid, 0.0) + 1.0
        player_team[pid] = team or player_team.get(pid, "")
        team_gl_rushes[team] = team_gl_rushes.get(team, 0.0) + 1.0
        if _is_flag(play, "touchdown"):
            gl_tds[pid] = gl_tds.get(pid, 0.0) + 1.0

    player_ids = set(targets) | set(carries) | set(gl_carries)
    out: dict[str, dict[str, Any]] = {}
    for pid in player_ids:
        t = targets.get(pid, 0.0)
        c = carries.get(pid, 0.0)
        touches = t + c
        team = player_team.get(pid, "")
        blended = None
        if team:
            team_total = sum(
                v for (tm, _w), v in team_week_touches.items() if tm == team
            )
            if team_total > 0:
                blended = touches / team_total
        rush_share = None
        if team and team_rz_rushes.get(team, 0.0) > 0 and c > 0:
            rush_share = c / team_rz_rushes[team]
        target_share = None
        if team and team_rz_passes.get(team, 0.0) > 0 and t > 0:
            target_share = t / team_rz_passes[team]
        gl_c = gl_carries.get(pid, 0.0)
        gl_share = None
        if team and team_gl_rushes.get(team, 0.0) > 0 and gl_c > 0:
            gl_share = gl_c / team_gl_rushes[team]
        gl_td_rate = None
        if gl_c > 0:
            gl_td_rate = gl_tds.get(pid, 0.0) / gl_c

        # Default blended share kept for backward compatibility.
        default_share = (
            _clamp(float(blended), 0.02, 0.55) if blended is not None else None
        )
        out[pid] = {
            "rz_targets": t,
            "rz_carries": c,
            "gl_carries": gl_c,
            "rz_touches": touches,
            "rz_targets_pg": t / prior_games,
            "rz_carries_pg": c / prior_games,
            "gl_carries_pg": gl_c / prior_games,
            "rz_rush_share": (
                _clamp(float(rush_share), 0.02, 0.70)
                if rush_share is not None
                else None
            ),
            "rz_target_share": (
                _clamp(float(target_share), 0.02, 0.55)
                if target_share is not None
                else None
            ),
            "gl_carry_share": (
                _clamp(float(gl_share), 0.02, 0.70) if gl_share is not None else None
            ),
            "gl_td_rate": (
                _clamp(float(gl_td_rate), 0.05, 0.85)
                if gl_td_rate is not None
                else None
            ),
            "player_rz_share": default_share,
            "prior_games": float(prior_games),
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
        "down",
        "touchdown",
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
