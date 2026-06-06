"""Pushed bets should contribute $0 to net P&L."""

from unittest.mock import MagicMock

from app.services.betting_analytics_service import BettingAnalyticsService


def test_bet_net_profit_push_is_zero():
    bet = MagicMock()
    bet.status = "pushed"
    bet.amount = 1250.0
    bet.result_amount = 1250.0
    assert BettingAnalyticsService._bet_net_profit(bet) == 0.0


def test_bet_net_profit_won_uses_payout_minus_stake():
    bet = MagicMock()
    bet.status = "won"
    bet.amount = 100.0
    bet.result_amount = 190.91
    bet.potential_win = 90.91
    assert round(BettingAnalyticsService._bet_net_profit(bet), 2) == 90.91


def test_bet_net_profit_lost_is_negative_stake():
    bet = MagicMock()
    bet.status = "lost"
    bet.amount = 50.0
    bet.result_amount = 0.0
    assert BettingAnalyticsService._bet_net_profit(bet) == -50.0
