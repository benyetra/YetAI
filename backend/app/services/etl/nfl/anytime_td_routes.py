"""True route participation from nflverse pbp_participation (pass-play on-field).

Public NGS weekly receiving does not include per-player ``routes_run``. The closest
open source is ``pbp_participation``: GSIS IDs on offense for dropbacks. We count
WR/TE/RB appearances on ``pass==1`` plays as routes, with team dropbacks as the
denominator. Snap-based proxies in ``anytime_td_snaps`` remain the fallback.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)

_ROUTE_POSITIONS = frozenset({"WR", "TE", "RB"})
_PARTICIPATION_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "pbp_participation/pbp_participation_{season}.parquet"
)
_PBP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "pbp/play_by_play_{season}.parquet"
)


def _split_offense_players(raw: Any) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text or text.lower() in {"nan", "none"}:
        return []
    return [p.strip() for p in text.split(";") if p.strip()]


def weekly_route_records_from_pass_plays(
    pass_plays: Iterable[Mapping[str, Any]],
    *,
    position_by_player: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Build player-week route rows from pass plays with ``offense_players``.

    Each play needs: ``week``, ``team`` (possession), ``offense_players`` (``;``-
    separated GSIS ids) or ``offense_player_ids`` (list). Only WR/TE/RB in
    ``position_by_player`` are counted.
    """
    # (player_id, week, team) -> routes
    routes: dict[tuple[str, int, str], int] = {}
    # (team, week) -> dropbacks
    dropbacks: dict[tuple[str, int], int] = {}
    last_pos: dict[str, str] = {}

    for play in pass_plays:
        try:
            week = int(float(play.get("week") or 0))
        except (TypeError, ValueError):
            continue
        if week <= 0:
            continue
        team = (
            str(
                play.get("team")
                or play.get("possession_team")
                or play.get("posteam")
                or ""
            )
            .strip()
            .upper()
        )
        if not team:
            continue

        ids = play.get("offense_player_ids")
        if ids is None:
            ids = _split_offense_players(play.get("offense_players"))
        else:
            ids = [str(p).strip() for p in ids if str(p).strip()]

        dropbacks[(team, week)] = dropbacks.get((team, week), 0) + 1
        seen: set[str] = set()
        for player_id in ids:
            if player_id in seen:
                continue
            seen.add(player_id)
            pos = str(position_by_player.get(player_id) or "").strip().upper()
            if pos not in _ROUTE_POSITIONS:
                continue
            key = (player_id, week, team)
            routes[key] = routes.get(key, 0) + 1
            last_pos[player_id] = pos

    out: list[dict[str, Any]] = []
    for (player_id, week, team), n_routes in routes.items():
        team_db = int(dropbacks.get((team, week), 0))
        out.append(
            {
                "player_id": player_id,
                "week": week,
                "team": team,
                "position": last_pos.get(player_id, ""),
                "routes": float(n_routes),
                "team_dropbacks": float(team_db),
            }
        )
    return out


def aggregate_player_routes(
    route_records: Iterable[Mapping[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, Any]]:
    """Aggregate prior-week routes / route participation (weeks < as_of_week)."""
    by_player: dict[str, list[dict[str, Any]]] = {}
    for raw in route_records:
        try:
            week = int(float(raw.get("week") or 0))
        except (TypeError, ValueError):
            continue
        if week <= 0 or week >= as_of_week:
            continue
        player_id = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        if not player_id:
            continue
        try:
            n_routes = float(raw.get("routes") or 0.0)
        except (TypeError, ValueError):
            continue
        try:
            team_db = float(raw.get("team_dropbacks") or 0.0)
        except (TypeError, ValueError):
            team_db = 0.0
        by_player.setdefault(player_id, []).append(
            {
                "week": week,
                "routes": n_routes,
                "team_dropbacks": team_db,
                "position": str(raw.get("position") or "").upper(),
                "team": str(raw.get("team") or raw.get("recent_team") or "").upper(),
            }
        )

    out: dict[str, dict[str, Any]] = {}
    for player_id, rows in by_player.items():
        rows.sort(key=lambda r: r["week"])
        last3 = rows[-3:]
        routes_l3 = sum(r["routes"] for r in last3) / len(last3)
        parts = [
            (r["routes"] / r["team_dropbacks"])
            for r in last3
            if r["team_dropbacks"] and r["team_dropbacks"] > 0
        ]
        route_part = sum(parts) / len(parts) if parts else 0.0
        route_part = min(1.0, max(0.0, route_part))
        out[player_id] = {
            "routes_l3": routes_l3,
            "route_participation": route_part,
            "routes_source": "pbp_participation",
            "position": last3[-1]["position"],
            "team_abbr": last3[-1]["team"],
        }
    return out


def merge_routes_into_usage(
    usage_by_player: dict[str, dict[str, Any]],
    routes_by_player: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Overwrite snap-proxy routes with true pbp_participation routes when present."""
    merged = {pid: dict(u) for pid, u in usage_by_player.items()}
    for player_id, route in routes_by_player.items():
        row = merged.setdefault(player_id, {"player_id": player_id})
        if route.get("routes_l3") is not None:
            row["routes_l3"] = float(route["routes_l3"])
        if route.get("route_participation") is not None:
            row["route_participation"] = float(route["route_participation"])
        if route.get("routes_source"):
            row["routes_source"] = str(route["routes_source"])
        elif route.get("routes_l3") is not None:
            row["routes_source"] = "pbp_participation"
        if route.get("position") and not row.get("position"):
            row["position"] = route["position"]
        if route.get("team_abbr") and not row.get("team_abbr"):
            row["team_abbr"] = route["team_abbr"]
    return merged


def _position_map_from_weekly(season: int) -> dict[str, str]:
    """GSIS → position from weekly stats (best-effort)."""
    from app.services.etl.nfl.anytime_td_features import (
        load_weekly_records_with_fallback,
    )

    weekly, _ = load_weekly_records_with_fallback(season)
    out: dict[str, str] = {}
    for row in weekly or []:
        pid = str(row.get("player_id") or row.get("gsis_id") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        if pid and pos:
            out[pid] = pos
    return out


def load_route_records(season: int) -> list[dict[str, Any]]:
    """Load player-week route counts from pbp_participation × PBP pass flag.

    Returns empty list when parquet/network unavailable (caller keeps snap proxy).
    """
    try:
        import pandas as pd
    except ImportError:
        logger.warning("pandas unavailable for route participation load")
        return []

    try:
        part = pd.read_parquet(
            _PARTICIPATION_URL.format(season=int(season)),
            columns=[
                "nflverse_game_id",
                "play_id",
                "offense_players",
                "possession_team",
            ],
        )
    except Exception as exc:
        logger.warning(
            "pbp_participation unavailable for %s (%s); keeping snap route proxy",
            season,
            exc,
        )
        return []

    try:
        pbp = pd.read_parquet(
            _PBP_URL.format(season=int(season)),
            columns=["game_id", "play_id", "pass", "week", "posteam"],
        )
    except Exception as exc:
        logger.warning(
            "PBP unavailable for route join season=%s (%s); keeping snap proxy",
            season,
            exc,
        )
        return []

    merged = part.merge(
        pbp,
        left_on=["nflverse_game_id", "play_id"],
        right_on=["game_id", "play_id"],
        how="inner",
    )
    pass_m = merged[merged["pass"].fillna(0).astype(float) == 1.0]
    if pass_m.empty:
        logger.warning("no pass plays after pbp_participation join for %s", season)
        return []

    try:
        position_by_player = _position_map_from_weekly(int(season))
    except Exception as exc:
        logger.warning("weekly position map failed for routes (%s)", exc)
        position_by_player = {}

    plays: list[dict[str, Any]] = []
    for row in pass_m.itertuples(index=False):
        week = getattr(row, "week", None)
        team = getattr(row, "possession_team", None) or getattr(row, "posteam", None)
        offense = getattr(row, "offense_players", None)
        plays.append(
            {
                "week": week,
                "team": team,
                "offense_players": offense,
            }
        )

    records = weekly_route_records_from_pass_plays(
        plays, position_by_player=position_by_player
    )
    logger.info(
        "loaded %s player-week route rows from pbp_participation season=%s",
        len(records),
        season,
    )
    return records
