"""Derive shooting efficiency from traditional box score columns.

WNBA ETL stores FGM / FG3M / FGA / FTA / PTS but not advanced rates from
stats.wnba.com. eFG% and TS% are computed here so feature engineering and
backfill stay consistent without a second API call per game.
"""

from __future__ import annotations

from typing import Any


def effective_fg_pct(
    *,
    field_goals_made: float | None,
    three_pt_made: float | None,
    fg_attempts: float | None,
    stored: float | None = None,
) -> float | None:
    """eFG% = (FGM + 0.5 * FG3M) / FGA. Prefer stored value when present."""
    if stored is not None:
        return float(stored)
    if field_goals_made is None or fg_attempts is None or fg_attempts <= 0:
        return None
    fg3 = float(three_pt_made or 0.0)
    return (float(field_goals_made) + 0.5 * fg3) / float(fg_attempts)


def true_shooting_pct(
    *,
    points: float | None,
    fg_attempts: float | None,
    ft_attempts: float | None,
    stored: float | None = None,
) -> float | None:
    """TS% = PTS / (2 * (FGA + 0.44 * FTA)). Prefer stored when present."""
    if stored is not None:
        return float(stored)
    if points is None or fg_attempts is None:
        return None
    fta = float(ft_attempts or 0.0)
    denom = 2.0 * (float(fg_attempts) + 0.44 * fta)
    if denom <= 0:
        return None
    return float(points) / denom


def shooting_from_row(row: Any) -> dict[str, float | None]:
    """Return derived eFG/TS for an ORM row or box-score dict-like object."""

    def _get(name: str) -> float | None:
        if isinstance(row, dict):
            val = row.get(name)
        else:
            val = getattr(row, name, None)
        return float(val) if val is not None else None

    efg = effective_fg_pct(
        field_goals_made=_get("field_goals_made"),
        three_pt_made=_get("three_pt_made"),
        fg_attempts=_get("fg_attempts"),
        stored=_get("effective_field_goal_percentage"),
    )
    ts = true_shooting_pct(
        points=_get("points"),
        fg_attempts=_get("fg_attempts"),
        ft_attempts=_get("ft_attempts"),
        stored=_get("true_shooting_percentage"),
    )
    return {
        "effective_field_goal_percentage": efg,
        "true_shooting_percentage": ts,
    }


def enrich_boxscore_row(row: dict[str, Any]) -> dict[str, Any]:
    """Add derived shooting columns to a pending upsert dict (in-place safe copy)."""
    out = dict(row)
    # Always set both keys (including None) so bulk INSERT batches stay column-aligned.
    out.update(shooting_from_row(out))
    return out
