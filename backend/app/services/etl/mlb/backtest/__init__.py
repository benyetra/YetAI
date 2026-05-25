"""YetAI MLB Backtesting Engine.

A framework for running projection models against historical games
and measuring accuracy against actual outcomes.
"""

from app.services.etl.mlb.backtest.cli import parse_args, run_backtest, main
from app.services.etl.mlb.backtest.metrics import (
    DEFAULT_BACKTEST_TOLERANCES,
    BaselineCheckResult,
    assert_metrics_against_baseline,
    check_metrics_against_baseline,
    summarize_backtest_metrics,
)

__all__ = [
    "parse_args",
    "run_backtest",
    "main",
    "DEFAULT_BACKTEST_TOLERANCES",
    "BaselineCheckResult",
    "assert_metrics_against_baseline",
    "check_metrics_against_baseline",
    "summarize_backtest_metrics",
]
