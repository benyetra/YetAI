"""WNBA backtest scoring: ATS, totals O/U, prop ROI at American odds."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.services.etl.wnba.spreads_accuracy_tracker import _ats_covered

DEFAULT_ODDS = -110


def american_to_profit(odds: int | float, *, won: bool) -> float:
    """Unit-stake profit for a graded bet (win or lose; pushes excluded)."""
    if not won:
        return -1.0
    o = float(odds)
    if o < 0:
        return round(100.0 / abs(o), 6)
    return round(o / 100.0, 6)


def _mean(xs: Sequence[float]) -> float | None:
    if not xs:
        return None
    return round(sum(xs) / len(xs), 6)


def score_ats(
    rows: Sequence[Mapping[str, Any]],
    *,
    odds: int | float = DEFAULT_ODDS,
) -> dict[str, Any]:
    """Grade spread recommendations vs actual margins."""
    pnls: list[float] = []
    hits = 0
    for row in rows:
        covered = _ats_covered(
            str(row.get("recommendation") or "NO_PLAY"),
            int(row["actual_margin"]),
            row.get("market_spread_home"),
        )
        if covered is None:
            continue
        if covered:
            hits += 1
        pnls.append(american_to_profit(odds, won=covered))
    n = len(pnls)
    return {
        "n_bets": n,
        "hit_rate": round(hits / n, 6) if n else None,
        "roi": _mean(pnls),
        "units": round(sum(pnls), 4) if pnls else 0.0,
    }


def _totals_hit(row: Mapping[str, Any]) -> bool | None:
    rec = str(row.get("recommendation") or "NO_PLAY").upper()
    if rec == "NO_PLAY":
        # Infer from projected vs market when recommendation missing
        projected = row.get("projected_total")
        market = row.get("market_total")
        actual = row.get("actual_total")
        if projected is None or market is None or actual is None:
            return None
        if float(projected) == float(market) or float(actual) == float(market):
            return None
        pred_over = float(projected) > float(market)
        actual_over = float(actual) > float(market)
        return pred_over == actual_over
    if rec not in {"OVER", "UNDER"}:
        return None
    market = row.get("market_total")
    actual = row.get("actual_total")
    if market is None or actual is None:
        return None
    if float(actual) == float(market):
        return None
    actual_over = float(actual) > float(market)
    return actual_over if rec == "OVER" else (not actual_over)


def score_totals(
    rows: Sequence[Mapping[str, Any]],
    *,
    odds: int | float = DEFAULT_ODDS,
) -> dict[str, Any]:
    """Grade totals OVER/UNDER (or projected vs market when NO_PLAY)."""
    pnls: list[float] = []
    hits = 0
    abs_errs: list[float] = []
    for row in rows:
        if (
            row.get("projected_total") is not None
            and row.get("actual_total") is not None
        ):
            abs_errs.append(
                abs(float(row["projected_total"]) - float(row["actual_total"]))
            )
        hit = _totals_hit(row)
        if hit is None:
            continue
        if hit:
            hits += 1
        pnls.append(american_to_profit(odds, won=hit))
    n = len(pnls)
    return {
        "n_bets": n,
        "hit_rate": round(hits / n, 6) if n else None,
        "roi": _mean(pnls),
        "units": round(sum(pnls), 4) if pnls else 0.0,
        "mae": _mean(abs_errs),
    }


def _prop_hit(row: Mapping[str, Any]) -> bool | None:
    rec = str(row.get("recommendation") or "NO_PLAY").upper()
    line = row.get("market_line")
    actual = row.get("actual")
    if line is None or actual is None:
        return None
    if float(actual) == float(line):
        return None
    actual_over = float(actual) > float(line)
    if rec == "OVER":
        return actual_over
    if rec == "UNDER":
        return not actual_over
    # Explicit NO_PLAY / unknown: do not force a bet from projected vs line
    return None


def score_props(
    rows: Sequence[Mapping[str, Any]],
    *,
    odds: int | float = DEFAULT_ODDS,
) -> dict[str, Any]:
    """Grade player-prop OVER/UNDER with MAE on all projected rows."""
    pnls: list[float] = []
    hits = 0
    abs_errs: list[float] = []
    for row in rows:
        if row.get("projected") is not None and row.get("actual") is not None:
            abs_errs.append(abs(float(row["projected"]) - float(row["actual"])))
        hit = _prop_hit(row)
        if hit is None:
            continue
        if hit:
            hits += 1
        pnls.append(american_to_profit(odds, won=hit))
    n = len(pnls)
    return {
        "n_bets": n,
        "hit_rate": round(hits / n, 6) if n else None,
        "roi": _mean(pnls),
        "units": round(sum(pnls), 4) if pnls else 0.0,
        "mae": _mean(abs_errs),
    }
