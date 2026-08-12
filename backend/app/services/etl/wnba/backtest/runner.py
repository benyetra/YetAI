"""Replay stored WNBA projections vs actuals (NFL-style walk-forward grade)."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.services.etl.wnba.backtest.scorer import score_ats, score_props, score_totals

logger = logging.getLogger(__name__)

DEFAULT_QUICK_DAYS = 45


def _window_bounds(
    *,
    start: date | None,
    end: date | None,
    quick: bool,
) -> tuple[date, date]:
    end_d = end or date.today()
    if start is not None:
        start_d = start
    elif quick:
        start_d = end_d - timedelta(days=DEFAULT_QUICK_DAYS)
    else:
        # Default: current calendar season from May 1
        year = end_d.year if end_d.month >= 5 else end_d.year - 1
        start_d = date(year, 5, 1)
    return start_d, end_d


def _load_spread_rows(session: Session, start: date, end: date) -> list[dict[str, Any]]:
    from app.models.predictions_models import WNBASpreadActuals, WNBASpreadProjections

    pairs = (
        session.query(WNBASpreadProjections, WNBASpreadActuals)
        .join(
            WNBASpreadActuals,
            (WNBASpreadProjections.game_date == WNBASpreadActuals.game_date)
            & (WNBASpreadProjections.home_team_name == WNBASpreadActuals.home_team_name)
            & (
                WNBASpreadProjections.away_team_name == WNBASpreadActuals.away_team_name
            ),
        )
        .filter(WNBASpreadProjections.game_date >= start)
        .filter(WNBASpreadProjections.game_date <= end)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for proj, actual in pairs:
        rows.append(
            {
                "game_date": proj.game_date,
                "recommendation": proj.recommendation,
                "actual_margin": actual.actual_margin,
                "market_spread_home": proj.market_spread_home,
                "projected_margin": proj.projected_margin,
            }
        )
    return rows


def _load_totals_rows(session: Session, start: date, end: date) -> list[dict[str, Any]]:
    from app.models.predictions_models import WNBATotalsActuals, WNBATotalsProjections

    pairs = (
        session.query(WNBATotalsProjections, WNBATotalsActuals)
        .join(
            WNBATotalsActuals,
            (WNBATotalsProjections.game_date == WNBATotalsActuals.game_date)
            & (WNBATotalsProjections.home_team_name == WNBATotalsActuals.home_team_name)
            & (
                WNBATotalsProjections.away_team_name == WNBATotalsActuals.away_team_name
            ),
        )
        .filter(WNBATotalsProjections.game_date >= start)
        .filter(WNBATotalsProjections.game_date <= end)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for proj, actual in pairs:
        rows.append(
            {
                "game_date": proj.game_date,
                "recommendation": proj.recommendation,
                "projected_total": proj.projected_total,
                "market_total": proj.market_total,
                "actual_total": actual.actual_total,
            }
        )
    return rows


def _load_prop_rows(
    session: Session, start: date, end: date, *, stat: str
) -> list[dict[str, Any]]:
    from app.models.predictions_models import (
        WNBAAssistsActuals,
        WNBAAssistsProjections,
        WNBAPointsActuals,
        WNBAPointsProjections,
        WNBAPRAActuals,
        WNBAPRAProjections,
        WNBAReboundsActuals,
        WNBAReboundsProjections,
        WNBAThreePtMadeActuals,
        WNBAThreePtMadeProjections,
    )

    mapping = {
        "points": (
            WNBAPointsProjections,
            WNBAPointsActuals,
            "projected_points",
            "actual_points",
        ),
        "assists": (
            WNBAAssistsProjections,
            WNBAAssistsActuals,
            "projected_assists",
            "actual_assists",
        ),
        "rebounds": (
            WNBAReboundsProjections,
            WNBAReboundsActuals,
            "projected_rebounds",
            "actual_rebounds",
        ),
        "three_pt_made": (
            WNBAThreePtMadeProjections,
            WNBAThreePtMadeActuals,
            "projected_three_pt_made",
            "actual_three_pt_made",
        ),
        "pra": (
            WNBAPRAProjections,
            WNBAPRAActuals,
            "projected_pra",
            "actual_pra",
        ),
    }
    proj_model, act_model, proj_col, act_col = mapping[stat]
    pairs = (
        session.query(proj_model, act_model)
        .join(
            act_model,
            (proj_model.date == act_model.date)
            & (proj_model.player_id == act_model.player_id),
        )
        .filter(proj_model.date >= start)
        .filter(proj_model.date <= end)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for proj, actual in pairs:
        rows.append(
            {
                "date": proj.date,
                "player_id": proj.player_id,
                "projected": getattr(proj, proj_col),
                "market_line": proj.market_line,
                "recommendation": proj.recommendation,
                "actual": getattr(actual, act_col),
            }
        )
    return rows


def run_backtest_replay(
    session: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    quick: bool = False,
    odds: int = -110,
) -> dict[str, Any]:
    """Join stored WNBA projections to actuals and score ATS / O-U / props."""
    start_d, end_d = _window_bounds(start=start, end=end, quick=quick)
    spread_rows = _load_spread_rows(session, start_d, end_d)
    totals_rows = _load_totals_rows(session, start_d, end_d)
    prop_stats: dict[str, Any] = {}
    for stat in ("points", "assists", "rebounds", "three_pt_made", "pra"):
        prop_rows = _load_prop_rows(session, start_d, end_d, stat=stat)
        prop_stats[stat] = {
            **score_props(prop_rows, odds=odds),
            "n_rows": len(prop_rows),
        }

    result = {
        "status": "ok",
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "odds": odds,
        "spreads": {**score_ats(spread_rows, odds=odds), "n_rows": len(spread_rows)},
        "totals": {**score_totals(totals_rows, odds=odds), "n_rows": len(totals_rows)},
        "props": prop_stats,
    }
    logger.info(
        "WNBA backtest %s..%s: spreads n=%s ats_roi=%s totals n=%s ou_roi=%s",
        start_d,
        end_d,
        result["spreads"]["n_rows"],
        result["spreads"]["roi"],
        result["totals"]["n_rows"],
        result["totals"]["roi"],
    )
    return result
