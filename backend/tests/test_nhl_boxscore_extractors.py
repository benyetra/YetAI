"""Tests for the pure boxscore extractors in app/services/etl/nhl/_boxscore.py.

These functions are pure transforms over the NHL API JSON shape, so we
exercise them with hand-built fixture dicts. No network, no DB.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.services.etl.nhl import _boxscore as bx


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _team_summary(name: str, *, team_id: int, sog: int = 30, score: int = 2) -> dict:
    return {
        "id": team_id,
        "name": {"default": name},
        "sog": sog,
        "score": score,
    }


def _skater(*, player_id: int, name: str, sog: int) -> dict:
    return {"playerId": player_id, "name": {"default": name}, "sog": sog}


def _boxscore(
    *,
    away_name="Bruins",
    home_name="Rangers",
    away_id=1,
    home_id=2,
    away_sog=28,
    home_sog=33,
    away_score=2,
    home_score=4,
    skaters_away=None,
    skaters_home=None,
):
    return {
        "awayTeam": _team_summary(
            away_name, team_id=away_id, sog=away_sog, score=away_score
        ),
        "homeTeam": _team_summary(
            home_name, team_id=home_id, sog=home_sog, score=home_score
        ),
        "playerByGameStats": {
            "awayTeam": {
                "forwards": skaters_away or [],
                "defense": [],
                "goalies": [],
            },
            "homeTeam": {
                "forwards": skaters_home or [],
                "defense": [],
                "goalies": [],
            },
        },
    }


GAME_DATE = date(2026, 5, 23)


# ---------------------------------------------------------------------------
# extract_team_shots
# ---------------------------------------------------------------------------


def test_extract_team_shots_returns_two_rows_per_game():
    rows = bx.extract_team_shots(_boxscore(), game_id=42, game_date=GAME_DATE)
    assert len(rows) == 2
    away, home = rows
    assert away["team_name"] == "Bruins"
    assert away["opponent_team_name"] == "Rangers"
    assert away["actual_shots"] == 28
    assert home["team_name"] == "Rangers"
    assert home["actual_shots"] == 33


def test_extract_team_shots_skips_missing_sog():
    """If only one team has sog, only that row appears (defensive)."""
    box = _boxscore()
    box["homeTeam"].pop("sog")
    rows = bx.extract_team_shots(box, game_id=42, game_date=GAME_DATE)
    assert len(rows) == 1
    assert rows[0]["team_name"] == "Bruins"


def test_extract_team_shots_empty_boxscore_returns_empty():
    assert bx.extract_team_shots({}, game_id=42, game_date=GAME_DATE) == []


# ---------------------------------------------------------------------------
# extract_player_shots
# ---------------------------------------------------------------------------


def test_extract_player_shots_includes_skaters_excludes_goalies():
    box = _boxscore(
        skaters_away=[_skater(player_id=100, name="A. Skater", sog=4)],
        skaters_home=[_skater(player_id=200, name="B. Defender", sog=2)],
    )
    # Add a goalie to confirm exclusion
    box["playerByGameStats"]["homeTeam"]["goalies"] = [
        {"playerId": 999, "name": {"default": "Goalie"}, "sog": 0}
    ]
    rows = bx.extract_player_shots(box, game_id=42, game_date=GAME_DATE)
    ids = sorted(r["player_id"] for r in rows)
    assert ids == [100, 200]


def test_extract_player_shots_attaches_team_and_opponent():
    box = _boxscore(
        skaters_away=[_skater(player_id=100, name="A", sog=4)],
        skaters_home=[_skater(player_id=200, name="B", sog=2)],
    )
    rows = bx.extract_player_shots(box, game_id=42, game_date=GAME_DATE)
    a = next(r for r in rows if r["player_id"] == 100)
    assert a["team_name"] == "Bruins"
    assert a["opponent_team_name"] == "Rangers"
    h = next(r for r in rows if r["player_id"] == 200)
    assert h["team_name"] == "Rangers"
    assert h["opponent_team_name"] == "Bruins"


def test_extract_player_shots_skips_rows_without_sog_or_id():
    box = _boxscore(
        skaters_away=[
            {"playerId": None, "name": {"default": "X"}, "sog": 3},
            {"playerId": 5, "name": {"default": "Y"}, "sog": None},
            _skater(player_id=6, name="Z", sog=1),
        ],
    )
    rows = bx.extract_player_shots(box, game_id=42, game_date=GAME_DATE)
    ids = [r["player_id"] for r in rows]
    assert ids == [6]


# ---------------------------------------------------------------------------
# extract_team_totals
# ---------------------------------------------------------------------------


def test_extract_team_totals_returns_one_row():
    row = bx.extract_team_totals(
        _boxscore(away_score=2, home_score=4), game_id=42, game_date=GAME_DATE
    )
    assert row is not None
    assert row["actual_home_goals"] == 4
    assert row["actual_away_goals"] == 2
    assert row["actual_total_goals"] == 6
    assert row["home_team_name"] == "Rangers"
    assert row["away_team_name"] == "Bruins"


def test_extract_team_totals_returns_none_when_score_missing():
    box = _boxscore()
    box["homeTeam"].pop("score")
    assert bx.extract_team_totals(box, game_id=42, game_date=GAME_DATE) is None


# ---------------------------------------------------------------------------
# parse_ou_pick + grade_ou_pick
# ---------------------------------------------------------------------------


def test_parse_ou_pick_handles_uppercase_with_line():
    assert bx.parse_ou_pick("OVER 28.5") == "over"
    assert bx.parse_ou_pick("UNDER 28.5") == "under"
    assert bx.parse_ou_pick("PASS") is None
    assert bx.parse_ou_pick(None) is None
    assert bx.parse_ou_pick("") is None


def test_grade_ou_pick_over_wins_when_actual_above_line():
    assert bx.grade_ou_pick(actual=30, line=28.5, recommendation="OVER 28.5") is True


def test_grade_ou_pick_under_wins_when_actual_below_line():
    assert bx.grade_ou_pick(actual=4, line=5.5, recommendation="UNDER 5.5") is True


def test_grade_ou_pick_push_returns_none():
    assert bx.grade_ou_pick(actual=5, line=5, recommendation="OVER") is None


def test_grade_ou_pick_pass_returns_none():
    assert bx.grade_ou_pick(actual=5, line=4.5, recommendation="PASS") is None


def test_grade_ou_pick_missing_actual_returns_none():
    assert bx.grade_ou_pick(actual=None, line=4.5, recommendation="OVER 4.5") is None
