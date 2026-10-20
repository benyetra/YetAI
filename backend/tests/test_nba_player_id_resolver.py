"""NBA name → NBA.com player_id resolution."""

from __future__ import annotations

import pytest

from app.services.etl.nba import _api_sports
from app.services.etl.nba._api_sports import (
    MANUAL_PLAYER_IDS,
    SYNTHETIC_ID_BASE,
    normalize_player_name,
    resolve_nba_player_id,
)

STATIC = [
    {"id": 1, "full_name": "Luka Dončić", "is_active": True},
    {"id": 2, "full_name": "Gary Payton", "is_active": False},
    {"id": 3, "full_name": "Gary Payton II", "is_active": True},
    {"id": 4, "full_name": "Marcus Williams", "is_active": False},
    {"id": 5, "full_name": "Marcus Williams", "is_active": True},
    {"id": 6, "full_name": "Al Horford", "is_active": True},
    {"id": 7, "full_name": "Jaime Jaquez Jr.", "is_active": True},
    {"id": 8, "full_name": "Kristaps Porziņģis", "is_active": True},
]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Luka Dončić", "luka doncic"),
        ("Jaime Jaquez Jr.", "jaime jaquez"),
        ("Ja'Kobi Gillespie", "jakobi gillespie"),
        ("  Shai  Gilgeous-Alexander ", "shai gilgeous alexander"),
        ("Gary Payton II", "gary payton"),
        ("", ""),
    ],
)
def test_normalize_player_name(raw, expected):
    assert normalize_player_name(raw) == expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Luka Doncic", 1),  # accents
        ("Kristaps Porzingis", 8),
        ("Jaime Jaquez Jr", 7),  # suffix punctuation
        ("Jaime Jaquez", 7),
        ("Gary Payton II", 3),  # suffix kept → never the father
        ("Gary Payton", 3),  # father inactive → the active namesake
        ("Marcus Williams", 5),  # namesakes → the active one
        ("Neal Horford", None),  # no character-level substring match
    ],
)
def test_resolve_against_static(name, expected):
    assert resolve_nba_player_id(name, static_players=STATIC) == expected


def test_unknown_player_gets_synthetic_id_only_with_api_id():
    assert resolve_nba_player_id("AJ Dybantsa", static_players=STATIC) is None
    assert (
        resolve_nba_player_id("AJ Dybantsa", static_players=STATIC, api_sports_id=42)
        == SYNTHETIC_ID_BASE + 42
    )


def test_manual_ids_match_nba_api():
    """A wrong pin silently files one player's games under another's id."""
    static = _api_sports._get_static_players()
    by_name: dict[str, list[int]] = {}
    for p in static:
        by_name.setdefault(normalize_player_name(p["full_name"]), []).append(p["id"])
    for name, pid in MANUAL_PLAYER_IDS.items():
        assert name == normalize_player_name(name), f"{name!r} key not normalized"
        if name in by_name:
            assert (
                pid in by_name[name]
            ), f"{name}: pinned {pid}, nba_api {by_name[name]}"
        assert pid < SYNTHETIC_ID_BASE


def test_real_roster_names_resolve():
    for name, pid in {
        "Luka Doncic": 1629029,
        "Nikola Jokic": 203999,
        "Scoot Henderson": 1630703,
        "Brandon Miller": 1641706,
        "Jaime Jaquez Jr.": 1631170,
        "Anthony Davis": 203076,
    }.items():
        assert resolve_nba_player_id(name) == pid, name


@pytest.mark.parametrize(
    "api_sports_name, pid",
    [
        # API-Sports files the suffix under the first name.
        ("Jaime Jr. Jaquez", 1631170),
        ("Dereck II Lively", 1641726),
        ("Jaren Jr. Jackson", 1628991),
        # API-Sports spellings pinned in MANUAL_PLAYER_IDS.
        ("R. Rupert", 1641712),
        ("Jamie Jr. Jaquez", 1631170),
    ],
)
def test_api_sports_name_formats_resolve(api_sports_name, pid):
    assert resolve_nba_player_id(api_sports_name, api_sports_id=1) == pid


def test_mid_name_suffix_normalization():
    assert normalize_player_name("Jaime Jr. Jaquez") == "jaime jaquez"
    assert normalize_player_name("Trey III Murphy") == "trey murphy"
    assert normalize_player_name("Jaime Jr. Jaquez", strip_suffix=False) == (
        "jaime jr jaquez"
    )
