"""WNBA game-level pick grading for predictions API enrichment.

Joins spread/totals projections with pred_wnba_*_actuals so the UI can show
final scores and Hit/Miss badges (aligned with MLB game projection cards).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.models.predictions_models import WNBASpreadActuals, WNBATotalsActuals
from app.services.mlb_game_picks import grade_moneyline, grade_total

PickSide = Literal["home", "away"]


@dataclass(frozen=True)
class WnbaGameActual:
    home_score: int
    away_score: int
    actual_margin: int
    home_won: bool
    actual_total: int


def game_match_key(
    game_date: date | Any,
    home_team_name: str,
    away_team_name: str,
) -> tuple[Any, str, str]:
    return (
        game_date,
        (home_team_name or "").strip().lower(),
        (away_team_name or "").strip().lower(),
    )


def actual_from_spread(row: WNBASpreadActuals) -> WnbaGameActual:
    return WnbaGameActual(
        home_score=row.home_score,
        away_score=row.away_score,
        actual_margin=row.actual_margin,
        home_won=row.home_won,
        actual_total=row.home_score + row.away_score,
    )


def actual_from_totals(row: WNBATotalsActuals) -> WnbaGameActual:
    margin = row.home_score - row.away_score
    return WnbaGameActual(
        home_score=row.home_score,
        away_score=row.away_score,
        actual_margin=margin,
        home_won=row.home_score > row.away_score,
        actual_total=row.actual_total,
    )


def ats_covered(
    recommendation: str | None,
    actual_margin: int,
    market_spread_home: float | None,
) -> bool | None:
    """Return True/False if spread pick covered; None for pushes or no-play."""
    rec = (recommendation or "").strip().upper()
    if rec == "NO_PLAY" or market_spread_home is None:
        return None
    threshold = -float(market_spread_home)
    if actual_margin == threshold:
        return None
    if rec == "HOME":
        return actual_margin > threshold
    if rec == "AWAY":
        return actual_margin < threshold
    return None


def _winner_side(home_won: bool) -> PickSide:
    return "home" if home_won else "away"


def enrich_spread_projection_row(
    row: dict[str, Any],
    actual: WnbaGameActual | None,
) -> dict[str, Any]:
    if actual is None:
        return row
    out = dict(row)
    out["actual_home_score"] = actual.home_score
    out["actual_away_score"] = actual.away_score
    out["actual_winner"] = _winner_side(actual.home_won)

    rec = (row.get("recommendation") or "").strip().upper()
    market = row.get("market_spread_home")
    if market is not None:
        out["spread_correct"] = ats_covered(
            rec, int(actual.actual_margin), float(market)
        )
    if rec in ("HOME", "AWAY"):
        out["ml_correct"] = grade_moneyline(rec, winner=_winner_side(actual.home_won))
    return out


def enrich_totals_projection_row(
    row: dict[str, Any],
    actual: WnbaGameActual | None,
) -> dict[str, Any]:
    if actual is None:
        return row
    out = dict(row)
    out["actual_home_score"] = actual.home_score
    out["actual_away_score"] = actual.away_score
    out["actual_total"] = actual.actual_total
    out["actual_total_runs"] = actual.actual_total
    out["total_correct"] = grade_total(
        row.get("recommendation"),
        total_runs=int(actual.actual_total),
        market_total=row.get("market_total"),
        projected_total=row.get("projected_total"),
    )
    return out


def _resolve_actuals_date(
    target_date: date | None,
    spreads: list[dict[str, Any]],
    totals: list[dict[str, Any]],
) -> date | None:
    if target_date is not None:
        return target_date
    for rows in (spreads, totals):
        if rows and rows[0].get("game_date") is not None:
            return rows[0]["game_date"]
    return None


def _actuals_lookup(
    db: Session, actuals_date: date
) -> dict[tuple[Any, str, str], WnbaGameActual]:
    lookup: dict[tuple[Any, str, str], WnbaGameActual] = {}
    for row in (
        db.query(WNBASpreadActuals)
        .filter(WNBASpreadActuals.game_date == actuals_date)
        .all()
    ):
        lookup[
            game_match_key(row.game_date, row.home_team_name, row.away_team_name)
        ] = actual_from_spread(row)
    for row in (
        db.query(WNBATotalsActuals)
        .filter(WNBATotalsActuals.game_date == actuals_date)
        .all()
    ):
        key = game_match_key(row.game_date, row.home_team_name, row.away_team_name)
        lookup.setdefault(key, actual_from_totals(row))
    return lookup


def enrich_wnba_game_predictions(
    db: Session,
    spreads: list[dict[str, Any]],
    totals: list[dict[str, Any]],
    *,
    target_date: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Attach final scores and grading flags when actuals exist for the date."""
    actuals_date = _resolve_actuals_date(target_date, spreads, totals)
    if actuals_date is None:
        return spreads, totals

    by_game = _actuals_lookup(db, actuals_date)

    enriched_spreads: list[dict[str, Any]] = []
    for row in spreads:
        key = game_match_key(
            row.get("game_date"),
            str(row.get("home_team_name", "")),
            str(row.get("away_team_name", "")),
        )
        enriched_spreads.append(enrich_spread_projection_row(row, by_game.get(key)))

    enriched_totals: list[dict[str, Any]] = []
    for row in totals:
        key = game_match_key(
            row.get("game_date"),
            str(row.get("home_team_name", "")),
            str(row.get("away_team_name", "")),
        )
        enriched_totals.append(enrich_totals_projection_row(row, by_game.get(key)))

    return enriched_spreads, enriched_totals
