"""Load curated NFL defensive scheme tags from YAML and upsert to DB.

Feature builders (``anytime_td_features``) read string tags directly from YAML.
This module encodes tags to int/float for ``pred_nfl_defense_scheme`` persistence.
Season-level YAML sync uses ``SEASON_LEVEL_WEEK`` (0); the ``week`` column stays
nullable for future week-specific overrides.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.database import SessionLocal
from app.models.predictions_models import NFLDefenseScheme
from app.services.etl.nfl.nfl_common import resolve_nfl_season
from app.services.etl.nfl.team_names import _CANONICAL_BY_ABBR
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

SOURCE_YAML = "yaml"
SEASON_LEVEL_WEEK = 0

_COVER_BASE_TO_INT: dict[str, int] = {
    "cover_1": 1,
    "cover_2": 2,
    "cover_3": 3,
    "cover_4": 4,
    "cover_6": 6,
}
_MAN_ZONE_TO_FLOAT: dict[str, float] = {"man": 1.0, "zone": 0.0}
_PRESSURE_TO_FLOAT: dict[str, float] = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
}
_INT_TO_COVER_BASE: dict[int, str] = {v: k for k, v in _COVER_BASE_TO_INT.items()}
_FLOAT_TO_MAN_ZONE: dict[float, str] = {v: k for k, v in _MAN_ZONE_TO_FLOAT.items()}
_FLOAT_TO_PRESSURE: dict[float, str] = {v: k for k, v in _PRESSURE_TO_FLOAT.items()}

SCHEME_UPSERT_UPDATE_KEYS = [
    "cover_base",
    "man_zone_lean",
    "pressure_lean",
    "source",
    "updated_at",
]

_DEFAULT_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "nfl" / "defensive_schemes.yaml"
)

_PRIMARY_ABBRS = frozenset(
    {
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
        "JAX",
        "KC",
        "LAC",
        "LAR",
        "LV",
        "MIA",
        "MIN",
        "NE",
        "NO",
        "NYG",
        "NYJ",
        "PHI",
        "PIT",
        "SEA",
        "SF",
        "TB",
        "TEN",
        "WAS",
    }
)


def load_schemes_from_yaml(path: Path | None = None) -> dict[str, dict[str, Any]]:
    yaml_path = path or _DEFAULT_PATH
    with yaml_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected mapping at root of {yaml_path}")

    schemes: dict[str, dict[str, Any]] = {}
    for abbr, entry in raw.items():
        if not isinstance(entry, dict) or not isinstance(abbr, str):
            continue
        key = abbr.upper()
        if key not in _PRIMARY_ABBRS:
            continue
        record = dict(entry)
        schemes[key] = record
        full_name = _CANONICAL_BY_ABBR.get(key)
        if full_name:
            schemes[full_name] = record

    return schemes


def _encode_cover_base(value: Any) -> int | None:
    if value is None:
        return None
    key = str(value).lower().replace("-", "_")
    if key.isdigit():
        return int(key)
    return _COVER_BASE_TO_INT.get(key)


def _encode_man_zone_lean(value: Any) -> float | None:
    if value is None:
        return None
    return _MAN_ZONE_TO_FLOAT.get(str(value).lower())


def _encode_pressure_lean(value: Any) -> float | None:
    if value is None:
        return None
    return _PRESSURE_TO_FLOAT.get(str(value).lower())


def decode_cover_base(value: int | None) -> str | None:
    """Decode persisted ``cover_base`` int to YAML tag (e.g. 3 → ``cover_3``)."""
    if value is None:
        return None
    return _INT_TO_COVER_BASE.get(int(value))


def decode_man_zone_lean(value: float | None) -> str | None:
    """Decode persisted ``man_zone_lean`` float to YAML tag."""
    if value is None:
        return None
    return _FLOAT_TO_MAN_ZONE.get(float(value))


def decode_pressure_lean(value: float | None) -> str | None:
    """Decode persisted ``pressure_lean`` float to YAML tag."""
    if value is None:
        return None
    return _FLOAT_TO_PRESSURE.get(float(value))


def db_row_to_scheme_tags(row: dict[str, Any]) -> dict[str, str | None]:
    """Map one ``pred_nfl_defense_scheme`` row to YAML-style string tags."""
    return {
        "cover_base": decode_cover_base(row.get("cover_base")),
        "man_zone_lean": decode_man_zone_lean(row.get("man_zone_lean")),
        "pressure_lean": decode_pressure_lean(row.get("pressure_lean")),
    }


def yaml_entry_to_db_row(
    abbr: str,
    entry: dict[str, Any],
    *,
    season: int,
    week: int = SEASON_LEVEL_WEEK,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Map one YAML team entry to ``pred_nfl_defense_scheme`` upsert row."""
    team_name = _CANONICAL_BY_ABBR.get(abbr.upper(), abbr)
    timestamp = now or datetime.utcnow()
    return {
        "team_name": team_name,
        "season": season,
        "week": week,
        "cover_base": _encode_cover_base(entry.get("cover_base")),
        "man_zone_lean": _encode_man_zone_lean(entry.get("man_zone_lean")),
        "pressure_lean": _encode_pressure_lean(entry.get("pressure_lean")),
        "source": SOURCE_YAML,
        "updated_at": timestamp,
    }


def build_scheme_upsert_rows(
    schemes: dict[str, dict[str, Any]],
    *,
    season: int,
    week: int = SEASON_LEVEL_WEEK,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """One row per primary abbr (32 teams), keyed by canonical full name."""
    rows: list[dict[str, Any]] = []
    for abbr in sorted(_PRIMARY_ABBRS):
        entry = schemes.get(abbr)
        if not entry:
            continue
        rows.append(
            yaml_entry_to_db_row(abbr, entry, season=season, week=week, now=now)
        )
    return rows


def upsert_schemes_from_yaml(
    *,
    season: int | None = None,
    week: int = SEASON_LEVEL_WEEK,
    path: Path | None = None,
) -> dict[str, Any]:
    """Load YAML and upsert season-level scheme tags for all 32 teams."""
    resolved_season = resolve_nfl_season(season)
    schemes = load_schemes_from_yaml(path)
    now = datetime.utcnow()
    rows = build_scheme_upsert_rows(schemes, season=resolved_season, week=week, now=now)

    if not rows:
        return {
            "status": "ok",
            "season": resolved_season,
            "week": week,
            "upserted": 0,
        }

    db = SessionLocal()
    try:
        upsert_many(
            db,
            NFLDefenseScheme,
            rows,
            conflict_keys=["team_name", "season", "week"],
            update_keys=SCHEME_UPSERT_UPDATE_KEYS,
        )
        db.commit()
        return {
            "status": "ok",
            "season": resolved_season,
            "week": week,
            "upserted": len(rows),
        }
    finally:
        db.close()
