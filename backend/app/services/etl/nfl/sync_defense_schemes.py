"""Sync curated defensive scheme tags from YAML into the database."""

from __future__ import annotations

from app.services.etl.nfl.scheme_loader import (
    SEASON_LEVEL_WEEK,
    upsert_schemes_from_yaml,
)


def run(*, season: int | None = None, week: int = SEASON_LEVEL_WEEK) -> dict:
    """Load ``defensive_schemes.yaml`` and upsert ``pred_nfl_defense_scheme``."""
    return upsert_schemes_from_yaml(season=season, week=week)
