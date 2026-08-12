"""QB starter resolution when nflverse depth charts are stale or mis-assigned.

nfl-data-py depth charts (2025+ format) ship many historical snapshots in one
frame. Without filtering to the latest ``dt``, rank-1 rows can come from an old
snapshot. Even the latest snapshot can mis-assign players to teams (e.g. 2026
ATL listing Tua Tagovailoa over Michael Penix Jr.).

This module:
1. Filters QB depth rows to the latest snapshot timestamp.
2. Applies a small curated override map (OurLads / Yahoo REG starters) for
   seasons where nflverse team assignments are known-bad.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.etl.nfl.qb_tiers import normalize_qb_name_key

# Team abbr → canonical starter name. Only teams with known-bad nflverse data.
# Source: 2026 REG depth charts (OurLads / Yahoo Aug 2026) — same calibration
# as ``qb_tiers.QB_YARDS_TIERS``.
QB_STARTER_OVERRIDES_BY_SEASON: dict[int, dict[str, str]] = {
    2026: {
        "ATL": "Michael Penix Jr.",
        "CLE": "Shedeur Sanders",
        "MIA": "Tua Tagovailoa",
    },
}


def filter_depth_charts_to_latest_snapshot(depth_charts: pd.DataFrame) -> pd.DataFrame:
    """Keep only rows from the newest ``dt`` snapshot when present."""
    if depth_charts.empty or "dt" not in depth_charts.columns:
        return depth_charts
    latest_dt = depth_charts["dt"].max()
    return depth_charts[depth_charts["dt"] == latest_dt].copy()


def get_starter_override(season: int, team_abbr: str) -> str | None:
    """Return curated starter name for ``team_abbr`` when configured."""
    team = team_abbr.strip().upper()
    return QB_STARTER_OVERRIDES_BY_SEASON.get(season, {}).get(team)


def _name_matches(row_name: str, target_name: str) -> bool:
    return normalize_qb_name_key(row_name) == normalize_qb_name_key(target_name)


def find_qb_row_by_name(
    qb_depth: pd.DataFrame,
    player_name: str,
    *,
    name_field: str,
    team: str | None = None,
) -> pd.Series | None:
    """Find a QB row by normalized name, optionally restricted to ``team``."""
    if qb_depth.empty:
        return None
    subset = qb_depth
    if team is not None:
        team_col = "team" if "team" in qb_depth.columns else "club_code"
        subset = qb_depth[qb_depth[team_col] == team]
    for _, row in subset.iterrows():
        if _name_matches(str(row[name_field]), player_name):
            return row
    if team is not None:
        for _, row in qb_depth.iterrows():
            if _name_matches(str(row[name_field]), player_name):
                return row
    return None


def resolve_qb_starter_for_team(
    *,
    team: str,
    team_qbs: pd.DataFrame,
    full_qb_depth: pd.DataFrame,
    override_name: str | None,
    use_2025_format: bool,
) -> pd.Series | None:
    """Pick the starter row for ``team``, honoring overrides when set."""
    if team_qbs.empty and override_name is None:
        return None

    name_field = "player_name" if use_2025_format else "full_name"
    rank_field = "pos_rank" if use_2025_format else "depth_team"
    starter_rank: Any = 1 if use_2025_format else "1"

    if override_name:
        row = find_qb_row_by_name(
            team_qbs if not team_qbs.empty else full_qb_depth,
            override_name,
            name_field=name_field,
            team=team if not team_qbs.empty else None,
        )
        if row is not None:
            return row
        row = find_qb_row_by_name(
            full_qb_depth, override_name, name_field=name_field, team=None
        )
        if row is not None:
            return row

    if team_qbs.empty:
        return None

    starters = team_qbs[team_qbs[rank_field] == starter_rank]
    if starters.empty:
        return None
    return starters.iloc[0]


def depth_chart_format(depth_charts: pd.DataFrame) -> str:
    """Return ``'2024'`` or ``'2025'`` based on nflverse column layout."""
    if "position" in depth_charts.columns:
        return "2024"
    return "2025"
