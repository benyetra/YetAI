"""NFL offline backtest — QB passing yards and kicker FG vs stored actuals."""

from app.services.etl.nfl.backtest.metrics import (
    assert_metrics_against_baseline,
    check_metrics_against_baseline,
    summarize_nfl_backtest_metrics,
)
from app.services.etl.nfl.backtest.runner import (
    run_backtest_replay,
    score_synthetic_rows,
)
from app.services.etl.nfl.backtest.scorer import NFLBacktestScorer

__all__ = [
    "NFLBacktestScorer",
    "assert_metrics_against_baseline",
    "check_metrics_against_baseline",
    "run_backtest_replay",
    "score_synthetic_rows",
    "summarize_nfl_backtest_metrics",
]
