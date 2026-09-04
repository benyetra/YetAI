"""Home-perspective spread adjustment when a team's starting QB is out."""

from __future__ import annotations

QB_OUT_SPREAD_POINTS = 3.5
_OUT_STATUSES = frozenset({"out", "ir", "doubtful", "injured reserve"})


def qb_out_margin_adjustment(
    *,
    home_qb_out: bool,
    away_qb_out: bool,
    points: float = QB_OUT_SPREAD_POINTS,
) -> float:
    if home_qb_out and away_qb_out:
        return 0.0
    if home_qb_out:
        return -float(points)
    if away_qb_out:
        return float(points)
    return 0.0


def team_qb_is_out(row: dict) -> bool:
    status = str(row.get("injury_status") or "").strip().lower()
    if status in _OUT_STATUSES:
        return True
    return bool(row.get("is_backup"))
