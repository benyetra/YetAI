"""Site-specific championship title annotations (asterisks / footnotes)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_ANNOTATIONS_PATH = Path(__file__).with_name("title_annotations.json")


@lru_cache(maxsize=1)
def _load_all() -> dict[str, list[dict[str, Any]]]:
    if not _ANNOTATIONS_PATH.is_file():
        return {}
    raw = json.loads(_ANNOTATIONS_PATH.read_text())
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for slug, rows in raw.items():
        if isinstance(rows, list):
            out[str(slug)] = [r for r in rows if isinstance(r, dict)]
    return out


def annotations_for_slug(slug: str) -> list[dict[str, Any]]:
    return list(_load_all().get(slug) or [])


def annotation_for_season(slug: str, season: int) -> dict[str, Any] | None:
    for row in annotations_for_slug(slug):
        try:
            if int(row.get("season")) == int(season):
                return {
                    "marker": str(row.get("marker") or "*"),
                    "note": str(row.get("note") or "").strip(),
                }
        except (TypeError, ValueError):
            continue
    return None


def apply_title_annotations(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Attach champion_asterisk / champion_note onto seasons + dynasty timeline."""
    slug = str(snapshot.get("slug") or "")
    if not slug:
        return snapshot

    notes_by_season: dict[int, dict[str, Any]] = {}
    for row in annotations_for_slug(slug):
        try:
            year = int(row.get("season"))
        except (TypeError, ValueError):
            continue
        note = str(row.get("note") or "").strip()
        if not note:
            continue
        notes_by_season[year] = {
            "marker": str(row.get("marker") or "*"),
            "note": note,
        }

    if not notes_by_season:
        snapshot.setdefault("title_footnotes", [])
        return snapshot

    footnotes: list[dict[str, Any]] = []
    for season_row in snapshot.get("seasons") or []:
        year = season_row.get("season")
        ann = notes_by_season.get(int(year)) if year is not None else None
        if not ann:
            season_row["champion_asterisk"] = False
            season_row["champion_note"] = None
            continue
        season_row["champion_asterisk"] = True
        season_row["champion_note"] = ann["note"]
        season_row["champion_marker"] = ann["marker"]
        footnotes.append(
            {
                "season": int(year),
                "marker": ann["marker"],
                "note": ann["note"],
            }
        )

    for cell in snapshot.get("dynasty_timeline") or []:
        year = cell.get("season")
        ann = notes_by_season.get(int(year)) if year is not None else None
        if not ann:
            cell["champion_asterisk"] = False
            cell["champion_note"] = None
            continue
        cell["champion_asterisk"] = True
        cell["champion_note"] = ann["note"]
        cell["champion_marker"] = ann["marker"]

    snapshot["title_footnotes"] = footnotes
    return snapshot
