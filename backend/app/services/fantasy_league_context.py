"""NFL season / trade-deadline context for fantasy trade evaluation."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from app.services.etl.nfl.nfl_common import get_current_nfl_week, resolve_nfl_season

# Typical redraft trade deadline (most leagues lock trades ~ NFL week 10).
DEFAULT_TRADE_DEADLINE_WEEK = 10


def build_season_context(
    season: Optional[int] = None,
    *,
    is_dynasty: bool = False,
    trade_deadline_week: int = DEFAULT_TRADE_DEADLINE_WEEK,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Real NFL week and trade-deadline proximity for league-aware evaluation."""
    resolved_season = resolve_nfl_season(season)
    current_week = get_current_nfl_week(resolved_season, today=today)

    if is_dynasty:
        trade_deadline_weeks = None
        trade_deadline_passed = False
    else:
        trade_deadline_weeks = max(0, trade_deadline_week - current_week)
        trade_deadline_passed = current_week > trade_deadline_week

    return {
        "season": resolved_season,
        "current_week": current_week,
        "trade_deadline_week": trade_deadline_week,
        "trade_deadline_weeks": trade_deadline_weeks,
        "trade_deadline_passed": trade_deadline_passed,
        "regular_season_weeks_remaining": max(0, 18 - current_week),
    }
