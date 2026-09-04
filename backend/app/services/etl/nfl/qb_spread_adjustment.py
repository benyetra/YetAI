"""Home-perspective spread adjustment when a team's starting QB is out."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

QB_OUT_SPREAD_POINTS = 3.5
_OUT_STATUSES = frozenset({"out", "ir", "doubtful", "injured reserve"})
_OLDEST_PREDICTION_DATE = datetime.min


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


def _row_field(row, key: str):
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _prediction_date_from_row(row):
    value = _row_field(row, "prediction_date")
    if value is not None:
        return value
    fi = _row_field(row, "feature_importance")
    if not isinstance(fi, dict):
        return None
    value = fi.get("prediction_date")
    if value is not None:
        return value
    features = fi.get("features")
    if isinstance(features, dict):
        return features.get("prediction_date")
    return None


def _sortable_prediction_date(value) -> datetime:
    """Missing/None sorts as oldest so dated rows win."""
    if value is None:
        return _OLDEST_PREDICTION_DATE
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    return _OLDEST_PREDICTION_DATE


def qb_out_map_from_rows(rows) -> dict[str, bool]:
    """Map team_name → QB-out using the newest prediction_date rows only.

    Among rows that share the latest ``prediction_date``, OR ``team_qb_is_out``.
    Missing/None dates sort as oldest so a later dated starter beats a leftover
    backup. Same-timestamp starter+backup still ORs to out.
    """
    by_team: dict[str, list] = defaultdict(list)
    for row in rows:
        team = _row_field(row, "team_name")
        if not team:
            continue
        by_team[team].append(row)

    out: dict[str, bool] = {}
    for team, team_rows in by_team.items():
        keys = [
            _sortable_prediction_date(_prediction_date_from_row(row))
            for row in team_rows
        ]
        latest = max(keys)
        latest_rows = [row for row, key in zip(team_rows, keys) if key == latest]
        out[team] = any(team_qb_is_out(qb_status_from_row(row)) for row in latest_rows)
    return out
