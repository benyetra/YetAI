"""Title asterisk annotations for League Vault snapshots."""

from __future__ import annotations

from app.services.league_vault import title_annotations as ta
from app.services.league_vault.title_annotations import (
    annotation_for_season,
    apply_title_annotations,
)


def setup_function():
    ta._load_all.cache_clear()


def test_mikes_hard_2022_eddie_title_has_asterisk():
    ann = annotation_for_season("mikes-hard", 2022)
    assert ann is not None
    assert ann["marker"] == "*"
    assert "Hamlin" in ann["note"]
    assert "totally fine" in ann["note"]
    assert ann["link"] == "https://www.youtube.com/watch?v=2TGJQT-JgPI"
    assert ann["link_label"] == "Watch the hit"


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
    assert "Hamlin" in by_year[2022]["champion_note"]
    assert (
        by_year[2022]["champion_link"] == "https://www.youtube.com/watch?v=2TGJQT-JgPI"
    )
    assert by_year[2021].get("champion_asterisk") is False
    assert by_year[2023].get("champion_asterisk") is False

    dyn = {c["season"]: c for c in out["dynasty_timeline"]}
    assert dyn[2022]["champion_asterisk"] is True
    assert len(out["title_footnotes"]) == 1
    assert out["title_footnotes"][0]["season"] == 2022
    assert out["title_footnotes"][0]["link_label"] == "Watch the hit"


def test_other_slugs_unaffected():
    snap = {
        "slug": "league-838295",
        "seasons": [{"season": 2022, "champion": {"display_name": "X"}}],
        "dynasty_timeline": [{"season": 2022, "champion": {"display_name": "X"}}],
    }
    out = apply_title_annotations(snap)
    assert not out["seasons"][0].get("champion_asterisk")
    assert out.get("title_footnotes") == []
