"""WNBA backtest package — stored projection replay (ATS / O-U / props)."""

from app.services.etl.wnba.backtest.cli import main, parse_args
from app.services.etl.wnba.backtest.runner import run_backtest_replay
from app.services.etl.wnba.backtest.scorer import (
    american_to_profit,
    score_ats,
    score_props,
    score_totals,
)

__all__ = [
    "american_to_profit",
    "main",
    "parse_args",
    "run_backtest_replay",
    "score_ats",
    "score_props",
    "score_totals",
]
