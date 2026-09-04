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


def qb_status_from_row(row) -> dict:
    """Pull injury_status / is_backup from a prediction row, dict, or namespace."""
    if isinstance(row, dict):
        fi = row.get("feature_importance")
        injury_attr = row.get("injury_status")
        backup_attr = row.get("is_backup")
    else:
        fi = getattr(row, "feature_importance", None)
        injury_attr = getattr(row, "injury_status", None)
        backup_attr = getattr(row, "is_backup", None)
    fi = fi if isinstance(fi, dict) else {}
    features = fi.get("features") if isinstance(fi.get("features"), dict) else {}
    return {
        "injury_status": injury_attr
        or features.get("injury_status")
        or fi.get("injury_status")
        or "Healthy",
        "is_backup": bool(
            backup_attr or features.get("is_backup") or fi.get("is_backup")
        ),
    }


def qb_out_map_from_rows(rows) -> dict[str, bool]:
    """Map team_name → QB-out, OR-ing flags when starter and backup rows coexist."""
    out: dict[str, bool] = {}
    for row in rows:
        team = (
            row.get("team_name")
            if isinstance(row, dict)
            else getattr(row, "team_name", None)
        )
        if not team:
            continue
        out[team] = out.get(team, False) or team_qb_is_out(qb_status_from_row(row))
    return out
