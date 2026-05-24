from unittest.mock import MagicMock

from app.services.yetai_bets_demo import is_demo_yetai_bet


def test_demo_title_detected():
    bet = MagicMock(
        title="Dodgers vs Padres",
        description=None,
        reasoning=None,
        selection=None,
    )
    assert is_demo_yetai_bet(bet) is True


def test_real_prop_not_demo():
    bet = MagicMock(
        title="Mets vs Phillies",
        description="Model edge on Ks.",
        reasoning=None,
        selection="Scott UNDER 4.5 strikeouts",
    )
    assert is_demo_yetai_bet(bet) is False
