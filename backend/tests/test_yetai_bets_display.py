from unittest.mock import MagicMock

from app.services.yetai_bets_demo import is_demo_yetai_bet
from app.services.yetai_bets_display import (
    subscriber_game_label,
    title_looks_like_prop_line,
)


def test_subscriber_game_label_from_teams():
    bet = MagicMock(
        away_team="Mets",
        home_team="Phillies",
        title="Christian Scott UNDER 4.5 strikeouts (MLB)",
    )
    assert subscriber_game_label(bet) == "Mets @ Phillies"


def test_subscriber_game_label_prop_title_without_teams():
    bet = MagicMock(
        away_team=None,
        home_team=None,
        title="Christian Scott UNDER 4.5 strikeouts (MLB)",
    )
    assert subscriber_game_label(bet) == "Matchup pending"


def test_demo_detected_by_reasoning():
    bet = MagicMock(
        title="Some edited title",
        description="Padres bullpen fatigued from extra innings yesterday.",
        reasoning=None,
        selection="Dodgers ML",
    )
    assert is_demo_yetai_bet(bet) is True


def test_title_looks_like_prop_line():
    assert title_looks_like_prop_line("Scott UNDER 4.5 strikeouts") is True
    assert title_looks_like_prop_line("Mets vs Phillies") is False
