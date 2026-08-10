"""Load curated NFL defensive scheme tags from YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.services.etl.nfl.team_names import _CANONICAL_BY_ABBR

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
