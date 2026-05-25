"""Shared league-agnostic ML training utilities (BKB-2.1 / YetAI-ft6.7).

Supersedes the original YetAI-2wf scope: WNBA and NBA ETL paths keep thin
wrappers under ``app.services.etl.<league>.ml_training`` for backward-compatible
imports and CI module paths.
"""

from app.services.ml.config import LeagueMLConfig

__all__ = ["LeagueMLConfig"]
