"""Offensive snap % and route-participation proxies for anytime TD."""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


def normalize_offense_pct(value: Any) -> float | None:
    """Return offense snap share as 0–1 fraction (accepts 0–100 percents)."""
    if value is None:
        return None
    try:
        pct = float(value)
    except (TypeError, ValueError):
        return None
    if pct != pct:  # NaN
        return None
    if pct > 1.0:
        pct = pct / 100.0
    return min(1.0, max(0.0, pct))


def route_participation_from_snaps(
    position: str,
    snap_pct: float,
    *,
    team_pass_rate: float = 0.55,
) -> float:
    """Approximate route participation from offense snap share.

    True NGS routes are not in public nflverse weekly; for WR/TE snap share is a
    strong standing proxy. RBs on routes are discounted by team pass rate.
    """
    pos = (position or "").upper()
    snap = min(1.0, max(0.0, float(snap_pct)))
    pass_rate = min(1.0, max(0.0, float(team_pass_rate)))
    if pos in {"WR", "TE"}:
        return snap
    if pos == "RB":
        return snap * pass_rate * 0.55
    if pos == "QB":
        return snap * pass_rate
    return snap * pass_rate


def aggregate_player_snaps(
    snap_records: Iterable[Mapping[str, Any]],
    *,
    as_of_week: int,
    team_pass_rate_by_team: Mapping[str, float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Aggregate prior-week offense snap % / snaps (weeks < as_of_week)."""
    by_player: dict[str, list[dict[str, Any]]] = {}
    for raw in snap_records:
        try:
            week = int(float(raw.get("week") or 0))
        except (TypeError, ValueError):
            continue
        if week <= 0 or week >= as_of_week:
            continue
        player_id = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        if not player_id:
            continue
        pct = normalize_offense_pct(raw.get("offense_pct"))
        if pct is None:
            continue
        try:
            snaps = float(raw.get("offense_snaps") or 0.0)
        except (TypeError, ValueError):
            snaps = 0.0
        by_player.setdefault(player_id, []).append(
            {
                "week": week,
                "offense_pct": pct,
                "offense_snaps": snaps,
                "position": str(raw.get("position") or "").upper(),
                "team": str(raw.get("team") or raw.get("recent_team") or "").upper(),
            }
        )

    pass_rates = team_pass_rate_by_team or {}
    out: dict[str, dict[str, Any]] = {}
    for player_id, rows in by_player.items():
        rows.sort(key=lambda r: r["week"])
        last3 = rows[-3:]
        snap_pct = sum(r["offense_pct"] for r in last3) / len(last3)
        snaps_l3 = sum(r["offense_snaps"] for r in last3) / len(last3)
        pos = last3[-1]["position"]
        team = last3[-1]["team"]
        team_pass = float(pass_rates.get(team, 0.55))
        route_part = route_participation_from_snaps(
            pos, snap_pct, team_pass_rate=team_pass
        )
        routes_l3 = snaps_l3 * (
            1.0 if pos in {"WR", "TE"} else team_pass * (0.55 if pos == "RB" else 1.0)
        )
        out[player_id] = {
            "snap_pct": snap_pct,
            "offense_snaps_l3": snaps_l3,
            "route_participation": route_part,
            "routes_l3": routes_l3,
            "position": pos,
            "team_abbr": team,
        }
    return out


def merge_snaps_into_usage(
    usage_by_player: dict[str, dict[str, Any]],
    snaps_by_player: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Overwrite target_share snap proxy with real offense_pct when available."""
    merged = {pid: dict(u) for pid, u in usage_by_player.items()}
    for player_id, snap in snaps_by_player.items():
        row = merged.setdefault(player_id, {"player_id": player_id})
        if snap.get("snap_pct") is not None:
            row["snap_pct"] = float(snap["snap_pct"])
            row["snap_pct_source"] = "offense_pct"
        if snap.get("offense_snaps_l3") is not None:
            row["offense_snaps_l3"] = float(snap["offense_snaps_l3"])
        if snap.get("route_participation") is not None:
            row["route_participation"] = float(snap["route_participation"])
        if snap.get("routes_l3") is not None:
            row["routes_l3"] = float(snap["routes_l3"])
        if snap.get("position") and not row.get("position"):
            row["position"] = snap["position"]
        if snap.get("team_abbr") and not row.get("team_abbr"):
            row["team_abbr"] = snap["team_abbr"]
    return merged


def _load_pfr_to_gsis_map() -> dict[str, str]:
    try:
        from app.services.etl.nfl.anytime_td_features import _import_nfl

        nfl = _import_nfl()
        ids = nfl.import_ids()
    except Exception as exc:
        logger.warning("nflverse ids unavailable for snap map: %s", exc)
        return {}
    out: dict[str, str] = {}
    if ids is None:
        return out
    records = ids.to_dict(orient="records") if hasattr(ids, "to_dict") else list(ids)
    for row in records:
        pfr = row.get("pfr_id")
        gsis = row.get("gsis_id")
        if pfr and gsis:
            out[str(pfr).strip()] = str(gsis).strip()
    return out


def load_snap_records(season: int) -> list[dict[str, Any]]:
    """Load snap counts mapped to GSIS player_id (empty if unavailable)."""
    from app.services.etl.nfl.anytime_td_features import (
        _import_nfl,
        _is_missing_nflverse_data_error,
        records_from_dataframe,
    )

    url = (
        "https://github.com/nflverse/nflverse-data/releases/download/"
        f"snap_counts/snap_counts_{season}.parquet"
    )
    frame = None
    try:
        import pandas as pd

        frame = pd.read_parquet(url)
    except Exception as exc:
        logger.info(
            "snap_counts parquet for %s failed (%s); trying import_snap_counts",
            season,
            exc,
        )
        try:
            nfl = _import_nfl()
            frame = nfl.import_snap_counts([int(season)])
        except Exception as exc2:
            if _is_missing_nflverse_data_error(exc2):
                logger.warning("snap counts missing for %s", season)
            else:
                logger.warning("snap counts unavailable for %s: %s", season, exc2)
            return []

    raw = records_from_dataframe(frame)
    if not raw:
        return []
    pfr_to_gsis = _load_pfr_to_gsis_map()
    out: list[dict[str, Any]] = []
    for row in raw:
        pfr = str(row.get("pfr_player_id") or "").strip()
        gsis = pfr_to_gsis.get(pfr) if pfr else None
        if not gsis:
            # Some builds may already carry gsis
            gsis = str(row.get("gsis_id") or row.get("player_id") or "").strip() or None
        if not gsis:
            continue
        mapped = dict(row)
        mapped["player_id"] = gsis
        mapped["gsis_id"] = gsis
        out.append(mapped)
    return out
