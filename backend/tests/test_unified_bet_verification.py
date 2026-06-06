"""Unified bet verification — team matching, DB fallback, spread push."""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.modules.setdefault("aiohttp", MagicMock())

from app.models.simple_unified_bet_model import BetStatus, BetType, TeamSide
from app.services.unified_bet_verification_service import UnifiedBetVerificationService


def _spread_bet(
    *,
    spread_value=-3.0,
    spread_selection=TeamSide.AWAY,
    home_team="Golden State Valkyries",
    away_team="Minnesota Lynx",
):
    return SimpleNamespace(
        id="bet-lynx",
        spread_value=spread_value,
        spread_selection=spread_selection,
        selected_team_name=away_team,
        selection=f"{away_team} -3",
        home_team=home_team,
        away_team=away_team,
        amount=1250.0,
        potential_win=1136.36,
        bet_type=BetType.SPREAD,
    )


def test_teams_match_partial_names():
    service = UnifiedBetVerificationService()
    assert service._teams_match("Minnesota Lynx", "Minnesota Lynx")
    assert service._teams_match("Golden State Valkyries", "Golden State Valkyries")
    assert service._teams_match("LA Sparks", "Los Angeles Sparks")
    assert service._teams_match("Minnesota Lynx", "Chicago Sky") is False


def test_evaluate_spread_push_when_away_wins_by_exact_line():
    service = UnifiedBetVerificationService()
    bet = _spread_bet()
    # Lynx (away) win by 3 with -3 spread → push
    status, amount, reasoning = service._evaluate_spread(
        bet, home_score=80, away_score=83
    )
    assert status == BetStatus.PUSHED
    assert amount == 1250.0
    assert "push" in reasoning.lower()


def test_evaluate_spread_resolves_side_from_selection_when_enum_missing():
    service = UnifiedBetVerificationService()
    bet = _spread_bet(spread_selection=TeamSide.NONE)
    status, amount, _ = service._evaluate_spread(bet, home_score=80, away_score=83)
    assert status == BetStatus.PUSHED
    assert amount == 1250.0


def test_find_completed_game_by_team_names_when_event_id_missing():
    service = UnifiedBetVerificationService()
    bet = SimpleNamespace(
        odds_api_event_id="wrong-id",
        home_team="Golden State Valkyries",
        away_team="Minnesota Lynx",
    )
    games = [
        {
            "id": "real-event",
            "completed": True,
            "home_team": "Golden State Valkyries",
            "away_team": "Minnesota Lynx",
            "scores": [
                {"name": "Golden State Valkyries", "score": "80"},
                {"name": "Minnesota Lynx", "score": "83"},
            ],
        }
    ]
    matched = service._find_completed_game(bet, games)
    assert matched is not None
    assert matched["id"] == "real-event"


def test_get_scores_from_db_uses_final_game_row():
    service = UnifiedBetVerificationService()
    from app.models.database_models import GameStatus

    game = SimpleNamespace(
        id="evt-1",
        home_score=80,
        away_score=83,
        status=GameStatus.FINAL,
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = game

    bet = SimpleNamespace(
        game_id="evt-1",
        odds_api_event_id="evt-1",
        home_team="Golden State Valkyries",
        away_team="Minnesota Lynx",
    )
    result = service._get_scores_from_db(bet, db)
    assert result == (80, 83, "local games table (evt-1)")
