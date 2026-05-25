"""YetAI NHL backtest — replay stored predictions vs actuals."""

from app.services.etl.nhl.backtest.cli import main, parse_args, run_backtest
from app.services.etl.nhl.backtest.metrics import (
    DEFAULT_NHL_BACKTEST_TOLERANCES,
    BaselineCheckResult,
    assert_metrics_against_baseline,
    check_metrics_against_baseline,
    summarize_nhl_backtest_metrics,
)

__all__ = [
    "main",
    "parse_args",
    "run_backtest",
    "DEFAULT_NHL_BACKTEST_TOLERANCES",
    "BaselineCheckResult",
    "assert_metrics_against_baseline",
    "check_metrics_against_baseline",
    "summarize_nhl_backtest_metrics",
]
