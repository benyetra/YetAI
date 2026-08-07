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


def _normalize_annotation(row: dict[str, Any]) -> dict[str, Any] | None:
    note = str(row.get("note") or "").strip()
    if not note:
        return None
    link = str(row.get("link") or "").strip() or None
    link_label = str(row.get("link_label") or "").strip() or None
    if link and not link_label:
        link_label = "Watch"
    return {
        "marker": str(row.get("marker") or "*"),
        "note": note,
        "link": link,
        "link_label": link_label,
    }


def annotations_for_slug(slug: str) -> list[dict[str, Any]]:
    return list(_load_all().get(slug) or [])


def annotation_for_season(slug: str, season: int) -> dict[str, Any] | None:
    for row in annotations_for_slug(slug):
        try:
            if int(row.get("season")) == int(season):
                return _normalize_annotation(row)
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
        ann = _normalize_annotation(row)
        if not ann:
            continue
        notes_by_season[year] = ann

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
            season_row["champion_link"] = None
            season_row["champion_link_label"] = None
            continue
        season_row["champion_asterisk"] = True
        season_row["champion_note"] = ann["note"]
        season_row["champion_marker"] = ann["marker"]
        season_row["champion_link"] = ann.get("link")
        season_row["champion_link_label"] = ann.get("link_label")
        footnotes.append(
            {
                "season": int(year),
                "marker": ann["marker"],
                "note": ann["note"],
                "link": ann.get("link"),
                "link_label": ann.get("link_label"),
            }
        )

    for cell in snapshot.get("dynasty_timeline") or []:
        year = cell.get("season")
        ann = notes_by_season.get(int(year)) if year is not None else None
        if not ann:
            cell["champion_asterisk"] = False
            cell["champion_note"] = None
            cell["champion_link"] = None
            cell["champion_link_label"] = None
            continue
        cell["champion_asterisk"] = True
        cell["champion_note"] = ann["note"]
        cell["champion_marker"] = ann["marker"]
        cell["champion_link"] = ann.get("link")
        cell["champion_link_label"] = ann.get("link_label")

    snapshot["title_footnotes"] = footnotes
    return snapshot
