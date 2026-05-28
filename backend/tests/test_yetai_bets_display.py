from unittest.mock import MagicMock

from app.services.yetai_bets_demo import is_demo_yetai_bet
from app.services.yetai_bets_display import (
    game_label_for_matchup,
    subscriber_game_label,
    title_looks_like_prop_line,
)


def test_subscriber_game_label_from_teams():
    bet = MagicMock(
        away_team="Mets",
        home_team="Phillies",
        title="Christian Scott UNDER 4.5 strikeouts (MLB)",
        bet_type="prop",
        sport="MLB",
        prediction_factors={},
    )
    assert subscriber_game_label(bet) == "Mets @ Phillies"


def test_subscriber_game_label_prop_with_opponent_metadata():
    bet = MagicMock(
        away_team=None,
        home_team=None,
        title="Luke Kornet OVER 1.5 points",
        bet_type="prop",
        sport="NBA",
        prediction_factors={
            "projection_metadata": {"opponent": "Oklahoma City Thunder"}
        },
    )
    assert subscriber_game_label(bet) == "vs Oklahoma City Thunder"


def test_subscriber_game_label_prop_without_teams():
    bet = MagicMock(
        away_team=None,
        home_team=None,
        title="Luke Kornet OVER 1.5 points",
        bet_type="prop",
        sport="NBA",
        prediction_factors={},
    )
    assert subscriber_game_label(bet) == "NBA player prop"


def test_game_label_for_matchup_prop_title_without_teams():
    assert (
        game_label_for_matchup(
            title="Victor Wembanyama UNDER 27.5 points",
            sport="NBA",
            bet_type="prop",
        )
        == "NBA player prop"
    )


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
