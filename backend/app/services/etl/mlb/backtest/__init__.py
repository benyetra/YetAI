"""YetAI MLB Backtesting Engine.

A framework for running projection models against historical games
and measuring accuracy against actual outcomes.
"""
from app.services.etl.mlb.backtest.cli import parse_args, run_backtest, main

__all__ = ['parse_args', 'run_backtest', 'main']
