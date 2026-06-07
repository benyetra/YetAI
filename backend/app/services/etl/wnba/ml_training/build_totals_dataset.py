"""Build (features, residual) dataset for WNBA totals ML training."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAGameLines,
    WNBASpreadActuals,
    WNBATotalsActuals,
    WNBATotalsProjections,
)
from app.services.etl.wnba import totals_projector as tp
from app.services.etl.wnba.ml_training import team_stats_as_of as tsa
from app.services.etl.wnba.totals_ml import features_from_projection

logger = logging.getLogger(__name__)

GameKey = tuple[date, str, str]


def _proj_dict_from_row(
    proj: WNBATotalsProjections, heuristic: float
) -> dict[str, Any]:
    return {
        "projected_total": heuristic,
        "heuristic_total": heuristic,
        "base_projection": proj.base_projection,
        "expected_pace": proj.expected_pace,
        "home_offensive_rating": proj.home_offensive_rating,
        "away_offensive_rating": proj.away_offensive_rating,
        "home_defensive_rating": proj.home_defensive_rating,
        "away_defensive_rating": proj.away_defensive_rating,
        "injury_adjustment": proj.injury_adjustment,
        "rest_adjustment": proj.rest_adjustment,
        "venue_adjustment": proj.venue_adjustment,
        "form_adjustment": proj.form_adjustment,
        "total_adjustment": proj.total_adjustment,
        "market_total": proj.market_total,
    }


def _preload_game_lines(
    db, season_start: date, season_end: date
) -> dict[GameKey, float]:
    lines = (
        db.query(WNBAGameLines)
        .filter(WNBAGameLines.game_date >= season_start)
        .filter(WNBAGameLines.game_date <= season_end)
        .all()
    )
    out: dict[GameKey, float] = {}
    for line in lines:
        if line.total is None:
            continue
        key = (line.game_date, line.home_team_name, line.away_team_name)
        out[key] = float(line.total)
    return out


def _fast_heuristic_projection(
    *,
    home_team_name: str,
    away_team_name: str,
    market_total: float | None,
    stats_cache: tsa.TeamStatsCache,
    as_of: date,
) -> dict[str, Any]:
    """Replay pace/efficiency baseline with point-in-time team stats."""
    home_stats = tsa.pace_and_efficiency_as_of(stats_cache, home_team_name, as_of)
    away_stats = tsa.pace_and_efficiency_as_of(stats_cache, away_team_name, as_of)

    expected_pace = tp.estimate_game_pace(home_stats["pace"], away_stats["pace"])
    home_adj = tp.matchup_efficiency(
        home_stats["offensive_rating"], away_stats["defensive_rating"]
    )
    away_adj = tp.matchup_efficiency(
        away_stats["offensive_rating"], home_stats["defensive_rating"]
    )
    home_projected = tp.project_team_score(home_adj, expected_pace)
    away_projected = tp.project_team_score(away_adj, expected_pace)
    base_projection = home_projected + away_projected
    heuristic = round(base_projection, 1)

    return {
        "projected_total": heuristic,
        "heuristic_total": heuristic,
        "base_projection": round(base_projection, 1),
        "expected_pace": round(expected_pace, 1),
        "home_offensive_rating": round(home_stats["offensive_rating"], 1),
        "away_offensive_rating": round(away_stats["offensive_rating"], 1),
        "home_defensive_rating": round(home_stats["defensive_rating"], 1),
        "away_defensive_rating": round(away_stats["defensive_rating"], 1),
        "injury_adjustment": 0.0,
        "rest_adjustment": 0.0,
        "venue_adjustment": 0.0,
        "form_adjustment": 0.0,
        "total_adjustment": 0.0,
        "market_total": market_total,
    }


def _heuristic_from_stored(proj: WNBATotalsProjections) -> float | None:
    shadow = (proj.factors or {}).get("ml_shadow") if proj.factors else {}
    heuristic = None
    if isinstance(shadow, dict):
        heuristic = shadow.get("heuristic_total")
    if heuristic is None:
        heuristic = proj.projected_total
    if heuristic is None:
        return None
    return float(heuristic)


def _load_actuals(db, season_start: date, season_end: date) -> list[Any]:
    totals = (
        db.query(WNBATotalsActuals)
        .filter(WNBATotalsActuals.game_date >= season_start)
        .filter(WNBATotalsActuals.game_date <= season_end)
        .order_by(WNBATotalsActuals.game_date.asc())
        .all()
    )
    if totals:
        return totals

    spreads = (
        db.query(WNBASpreadActuals)
        .filter(WNBASpreadActuals.game_date >= season_start)
        .filter(WNBASpreadActuals.game_date <= season_end)
        .order_by(WNBASpreadActuals.game_date.asc())
        .all()
    )
    if not spreads:
        return []

    logger.info(
        "build_totals_dataset: no totals actuals; using %d spread actuals",
        len(spreads),
    )
    return spreads


def _actual_total(actual: Any) -> float:
    if hasattr(actual, "actual_total") and actual.actual_total is not None:
        return float(actual.actual_total)
    return float(actual.home_score + actual.away_score)


def build(
    season_start: date, season_end: date
) -> tuple[pd.DataFrame, pd.Series, pd.Series, dict[str, int]]:
    """
    Target = actual_total - heuristic_total (residual on rule-based baseline).

    Uses stored projections when present; otherwise replays a fast pace/efficiency
    heuristic with point-in-time team stats and market total from ``pred_wnba_game_lines``.
    Falls back to spread actuals when totals actuals are empty.

    Returns ``(features, residual_target, game_dates, stats)`` aligned row-wise.
    """
    db = SessionLocal()
    rows_features: list[dict] = []
    rows_target: list[float] = []
    rows_dates: list[date] = []
    replayed = 0
    stored = 0
    try:
        actuals = _load_actuals(db, season_start, season_end)
        if not actuals:
            logger.info("build_totals_dataset: 0 rows (of 0 actuals)")
            empty_y = pd.Series(rows_target, name="residual")
            empty_d = pd.Series(rows_dates, name="game_date")
            stats = {
                "actuals": 0,
                "rows": 0,
                "stored_projections": 0,
                "fast_replay": 0,
            }
            return pd.DataFrame(rows_features), empty_y, empty_d, stats

        stats_cache = tsa.build_cache(db, season_start, season_end)
        market_lines = _preload_game_lines(db, season_start, season_end)

        stored_rows = {
            (
                p.game_date,
                p.home_team_name,
                p.away_team_name,
            ): p
            for p in db.query(WNBATotalsProjections)
            .filter(WNBATotalsProjections.game_date >= season_start)
            .filter(WNBATotalsProjections.game_date <= season_end)
            .all()
        }

        for actual in actuals:
            key = (actual.game_date, actual.home_team_name, actual.away_team_name)
            proj = stored_rows.get(key)

            proj_dict: dict[str, Any] | None = None
            if proj is not None:
                heuristic = _heuristic_from_stored(proj)
                if heuristic is not None:
                    proj_dict = _proj_dict_from_row(proj, heuristic)
                    stored += 1

            if proj_dict is None:
                market_total = market_lines.get(key)
                proj_dict = _fast_heuristic_projection(
                    home_team_name=actual.home_team_name,
                    away_team_name=actual.away_team_name,
                    market_total=market_total,
                    stats_cache=stats_cache,
                    as_of=actual.game_date,
                )
                replayed += 1

            heuristic = float(proj_dict["heuristic_total"])
            actual_total = _actual_total(actual)
            rows_features.append(features_from_projection(proj_dict))
            rows_target.append(actual_total - heuristic)
            rows_dates.append(actual.game_date)

        logger.info(
            "build_totals_dataset: %d rows (of %d actuals; stored=%d fast_replay=%d)",
            len(rows_features),
            len(actuals),
            stored,
            replayed,
        )
        stats = {
            "actuals": len(actuals),
            "rows": len(rows_features),
            "stored_projections": stored,
            "fast_replay": replayed,
        }
        return (
            pd.DataFrame(rows_features),
            pd.Series(rows_target, name="residual"),
            pd.Series(rows_dates, name="game_date"),
            stats,
        )
    finally:
        db.close()
