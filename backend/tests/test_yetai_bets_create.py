"""Admin YetAI bet creation (games FK and bet type normalization)."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.yetai_bets_service_db import (
    _ensure_game_row_for_yetai_bet,
)


def test_ensure_game_row_creates_missing_game():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    captured: dict = {}

    def capture_add(obj):
        captured["game"] = obj

    db.add.side_effect = capture_add

    game_id = _ensure_game_row_for_yetai_bet(
        db,
        game_id="evt-wnba-99",
        sport="WNBA",
        home_team="Minnesota Lynx",
        away_team="Golden State Valkyries",
        commence_time=datetime(2026, 6, 4, 23, 0, tzinfo=timezone.utc),
    )

    assert game_id == "evt-wnba-99"
    db.flush.assert_called_once()
    game = captured["game"]
    assert game.id == "evt-wnba-99"
    assert game.sport_key == "basketball_wnba"
    assert game.home_team == "Minnesota Lynx"


def test_ensure_game_row_skips_when_exists():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
        id="evt-1"
    )

    game_id = _ensure_game_row_for_yetai_bet(
        db,
        game_id="evt-1",
        sport="WNBA",
        home_team="A",
        away_team="B",
        commence_time=None,
    )

    assert game_id == "evt-1"
    db.add.assert_not_called()
