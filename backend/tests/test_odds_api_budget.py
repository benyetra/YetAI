"""Tests for shared Odds API daily budget."""

from unittest.mock import patch

from app.services.odds_api_budget import (
    DAILY_CREDIT_BUDGET,
    guard_sync,
    record_sync,
)


def test_guard_sync_blocks_at_budget():
    with patch(
        "app.services.odds_api_budget.get_daily_usage_sync",
        return_value=DAILY_CREDIT_BUDGET,
    ):
        assert guard_sync("test.caller") is False


def test_guard_sync_allows_under_budget():
    with patch(
        "app.services.odds_api_budget.get_daily_usage_sync",
        return_value=DAILY_CREDIT_BUDGET - 1,
    ):
        assert guard_sync("test.caller") is True


def test_record_sync_without_redis_returns_cost():
    with patch("app.services.odds_api_budget._sync_redis", return_value=None):
        assert record_sync(3, caller="test") == 3
