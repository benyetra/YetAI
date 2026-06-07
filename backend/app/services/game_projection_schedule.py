"""Attach scheduled start times from pred_*_game_lines onto projection API rows."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session


def game_match_key(
    game_date: Any,
    home_team_name: str,
    away_team_name: str,
) -> tuple[Any, str, str]:
    return (
        game_date,
        (home_team_name or "").strip().lower(),
        (away_team_name or "").strip().lower(),
    )


def build_game_time_lookup(
    db: Session,
    lines_model: Any,
    game_dates: set[date],
) -> dict[tuple[Any, str, str], datetime | None]:
    if not game_dates:
        return {}
    lookup: dict[tuple[Any, str, str], datetime | None] = {}
    for row in (
        db.query(lines_model).filter(lines_model.game_date.in_(game_dates)).all()
    ):
        key = game_match_key(row.game_date, row.home_team_name, row.away_team_name)
        lookup[key] = row.game_time
    return lookup


def attach_game_times(
    rows: list[dict[str, Any]],
    lookup: dict[tuple[Any, str, str], datetime | None],
    *,
    date_field: str = "game_date",
    home_field: str = "home_team_name",
    away_field: str = "away_team_name",
) -> list[dict[str, Any]]:
    if not lookup:
        return rows
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if row.get("game_time") is not None:
            enriched.append(row)
            continue
        key = game_match_key(
            row.get(date_field),
            str(row.get(home_field, "")),
            str(row.get(away_field, "")),
        )
        game_time = lookup.get(key)
        if game_time is not None:
            enriched.append({**row, "game_time": game_time})
        else:
            enriched.append(row)
    return enriched


def attach_game_times_from_lines(
    db: Session,
    rows: list[dict[str, Any]],
    lines_model: Any,
    *,
    date_field: str = "game_date",
    home_field: str = "home_team_name",
    away_field: str = "away_team_name",
) -> list[dict[str, Any]]:
    dates: set[date] = set()
    for row in rows:
        gd = row.get(date_field)
        if isinstance(gd, date):
            dates.add(gd)
    lookup = build_game_time_lookup(db, lines_model, dates)
    return attach_game_times(
        rows,
        lookup,
        date_field=date_field,
        home_field=home_field,
        away_field=away_field,
    )
