"""Shared MLB game-level pick derivation and grading (ML, spread, total).

Used by the game projection ETL, predictions API enrichment, and accuracy
summary so UI, storage, and grading stay aligned.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

Side = Literal["HOME", "AWAY"]
PickSide = Literal["home", "away"]

MLB_SPREAD_EDGE_THRESHOLD = 0.5
ML_EDGE_THRESHOLD = 0.03
TOTAL_EDGE_THRESHOLD = 0.5


def spread_recommendation(
    run_line: float | None,
    market_spread_home: float | None,
    *,
    threshold: float = MLB_SPREAD_EDGE_THRESHOLD,
) -> Optional[Side]:
    """Return HOME/AWAY spread play when projected margin beats market."""
    if run_line is None or market_spread_home is None:
        return None
    implied_market_margin = -float(market_spread_home)
    edge = float(run_line) - implied_market_margin
    if edge >= threshold:
        return "HOME"
    if edge <= -threshold:
        return "AWAY"
    return None


def derive_spread_recommendation_row(row: dict[str, Any]) -> Optional[str]:
    side = spread_recommendation(
        _float_or_none(row.get("run_line")),
        _float_or_none(row.get("market_spread")),
    )
    return side


def grade_moneyline(
    ml_recommendation: str | None,
    *,
    winner: PickSide,
) -> bool | None:
    pick = _normalize_side_pick(ml_recommendation)
    if pick is None:
        return None
    return pick == winner


def grade_spread(
    spread_recommendation: str | None,
    *,
    home_score: int,
    away_score: int,
    market_spread_home: float,
) -> bool | None:
    pick = _normalize_side_pick(spread_recommendation)
    if pick is None:
        return None
    actual_margin = home_score - away_score
    spread_f = float(market_spread_home)
    if actual_margin == spread_f:
        return None
    home_covers = actual_margin > spread_f
    if pick == "home":
        return home_covers
    return not home_covers


def grade_total(
    total_recommendation: str | None,
    *,
    total_runs: int,
    market_total: float | None,
    projected_total: float | None,
) -> bool | None:
    pick = (total_recommendation or "").strip().upper()
    if pick not in ("OVER", "UNDER"):
        return None
    line = market_total if market_total is not None else projected_total
    if line is None:
        return None
    line_f = float(line)
    if total_runs == line_f:
        return None
    if pick == "OVER":
        return total_runs > line_f
    return total_runs < line_f


def enrich_game_projection_row(row: dict[str, Any]) -> dict[str, Any]:
    """Attach spread_recommendation and optional actuals grading fields."""
    out = dict(row)
    if not out.get("spread_recommendation"):
        spread = derive_spread_recommendation_row(out)
        if spread:
            out["spread_recommendation"] = spread

    home_score = out.get("actual_home_score")
    away_score = out.get("actual_away_score")
    winner = out.get("actual_winner")
    if home_score is None or away_score is None or not winner:
        return out

    winner_side: PickSide = "home" if str(winner).lower() == "home" else "away"
    market_spread = _float_or_none(out.get("market_spread"))

    if out.get("ml_correct") is None:
        out["ml_correct"] = grade_moneyline(
            out.get("ml_recommendation"), winner=winner_side
        )
    if out.get("total_correct") is None:
        out["total_correct"] = grade_total(
            out.get("total_recommendation"),
            total_runs=int(home_score) + int(away_score),
            market_total=_float_or_none(out.get("market_total")),
            projected_total=_float_or_none(out.get("projected_total")),
        )
    if out.get("spread_correct") is None and market_spread is not None:
        out["spread_correct"] = grade_spread(
            out.get("spread_recommendation"),
            home_score=int(home_score),
            away_score=int(away_score),
            market_spread_home=market_spread,
        )
    return out


def _normalize_side_pick(value: str | None) -> PickSide | None:
    raw = (value or "").strip().upper()
    if raw == "HOME":
        return "home"
    if raw == "AWAY":
        return "away"
    return None


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
