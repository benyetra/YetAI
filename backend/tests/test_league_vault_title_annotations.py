"""Title asterisk annotations for League Vault snapshots."""

from __future__ import annotations

from app.services.league_vault.title_annotations import (
    annotation_for_season,
    apply_title_annotations,
)


def test_mikes_hard_2022_eddie_title_has_asterisk():
    ann = annotation_for_season("mikes-hard", 2022)
    assert ann is not None
    assert ann["marker"] == "*"
    assert "asterisk" in ann["note"].lower() or "cut" in ann["note"].lower()


def test_apply_title_annotations_onto_snapshot():
    snap = {
        "slug": "mikes-hard",
        "seasons": [
            {"season": 2021, "champion": {"display_name": "Remdick"}},
            {"season": 2022, "champion": {"display_name": "eddieprado89"}},
            {"season": 2023, "champion": {"display_name": "Jckeaney"}},
        ],
        "dynasty_timeline": [
            {"season": 2021, "champion": {"display_name": "Remdick"}},
            {"season": 2022, "champion": {"display_name": "eddieprado89"}},
            {"season": 2023, "champion": {"display_name": "Jckeaney"}},
        ],
    }
    out = apply_title_annotations(snap)
    by_year = {s["season"]: s for s in out["seasons"]}
    assert by_year[2022]["champion_asterisk"] is True
    assert by_year[2022]["champion_marker"] == "*"
    assert (
        "eddie" in by_year[2022]["champion_note"].lower()
        or "title" in by_year[2022]["champion_note"].lower()
    )
    assert by_year[2021].get("champion_asterisk") is False
    assert by_year[2023].get("champion_asterisk") is False

    dyn = {c["season"]: c for c in out["dynasty_timeline"]}
    assert dyn[2022]["champion_asterisk"] is True
    assert len(out["title_footnotes"]) == 1
    assert out["title_footnotes"][0]["season"] == 2022


def test_other_slugs_unaffected():
    snap = {
        "slug": "league-838295",
        "seasons": [{"season": 2022, "champion": {"display_name": "X"}}],
        "dynasty_timeline": [{"season": 2022, "champion": {"display_name": "X"}}],
    }
    out = apply_title_annotations(snap)
    assert not out["seasons"][0].get("champion_asterisk")
    assert out.get("title_footnotes") == []
