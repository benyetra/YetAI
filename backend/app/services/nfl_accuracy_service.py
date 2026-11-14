"""Per-day NFL projection accuracy → unified bucket shape.

NFL projection dates are stored on `game_date` (DateTime). We filter by
calendar day in the server's timezone for simplicity — there's only one
NFL slate per calendar day so timezone edge-cases don't matter much.

Buckets:
- QB Passing Yards O/U (uses `ou_line` + `betting_recommendation`)
- QB Passing Yards MAE
- Receiving Yards O/U (+MAE in the secondary)
- Kicker FG Made MAE
- Spread ATS (HOME/AWAY edge plays vs market line)
- Game Totals O/U (market_total + recommendation)
- Anytime TD Brier (P(TD) vs binary scored outcome)
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.predictions_models import (
    KickerActuals,
    KickerPredictions,
    NFLAnytimeTDActuals,
    NFLAnytimeTDPredictions,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTotalsActuals,
    NFLTotalsProjections,
    QBActuals,
    QBPredictions,
    RecvYdsActuals,
    RecvYdsPredictions,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    brier_bucket,
    edge_play_bucket,
    edge_play_graded_breakdown,
    edge_play_graded_counts,
    edge_row_result,
    mae_bucket,
    ou_call_bucket,
    ou_call_graded_breakdown,
    ou_call_graded_counts,
    ou_row_result,
    overview_item_from_markets,
)

ANYTIME_TD_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def _game_date_only(value: Any) -> date_type:
    if value is None:
        raise ValueError("missing game_date")
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date_type):
        return value
    raise TypeError(f"unsupported date type {type(value)}")


def _merge_actuals_recv(projections: list[Any], actuals: list[Any]) -> list[dict]:
    by_key = {(a.player_id, _game_date_only(a.game_date)): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        a = by_key.get((p.player_id, _game_date_only(p.game_date)))
        out.append(
            {
                "id": getattr(p, "id", None),
                "predicted_receiving_yards": p.predicted_receiving_yards,
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_receiving_yards": a.actual_receiving_yards if a else None,
                # grading ran for this window: a missing actual is a DNP
                "actual_expected": bool(actuals),
            }
        )
    return out


def _merge_actuals_qb_range(
    projections: list[Any], actuals: list[Any]
) -> list[dict[str, Any]]:
    by_key = {(a.qb_player_id, _game_date_only(a.game_date)): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        key = (p.qb_player_id, _game_date_only(p.game_date))
        a = by_key.get(key)
        out.append(
            {
                "id": getattr(p, "id", None),
                "qb_player_id": p.qb_player_id,
                "predicted_passing_yards": p.predicted_passing_yards,
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_passing_yards": a.actual_passing_yards if a else None,
                "actual_expected": bool(actuals),
                "model_version": getattr(p, "model_version", None) or "unknown",
            }
        )
    return out


def _merge_actuals_qb(projections, actuals) -> list[dict[str, Any]]:
    by_pid = {a.qb_player_id: a for a in actuals}
    out = []
    for p in projections:
        a = by_pid.get(p.qb_player_id)
        out.append(
            {
                "id": getattr(p, "id", None),
                "qb_player_id": p.qb_player_id,
                "predicted_passing_yards": p.predicted_passing_yards,
                "ou_line": p.ou_line,
                "betting_recommendation": p.betting_recommendation,
                "actual_passing_yards": a.actual_passing_yards if a else None,
                "actual_expected": bool(actuals),
                "model_version": getattr(p, "model_version", None) or "unknown",
            }
        )
    return out


def _merge_actuals_kicker(projections, actuals) -> list[dict[str, Any]]:
    by_kid = {a.kicker_id: a for a in actuals}
    out = []
    for p in projections:
        a = by_kid.get(p.kicker_player_id)
        out.append(
            {
                "kicker_player_id": p.kicker_player_id,
                "predicted_fg_made": getattr(p, "predicted_fg_made", None)
                or getattr(p, "projected_field_goals", None),
                "actual_field_goals_made": (a.actual_field_goals_made if a else None),
                "model_version": getattr(p, "model_version", None) or "unknown",
            }
        )
    return out


def mae_by_model_version(
    rows: list[dict[str, Any]],
    *,
    projected_field: str,
    actual_field: str,
    version_field: str = "model_version",
) -> dict[str, dict[str, Any]]:
    """Per-model_version MAE breakdown for graded rows."""
    buckets: dict[str, list[float]] = {}
    for row in rows:
        actual = row.get(actual_field)
        projected = row.get(projected_field)
        if actual is None or projected is None:
            continue
        try:
            err = abs(float(projected) - float(actual))
        except (TypeError, ValueError):
            continue
        ver = str(row.get(version_field) or "unknown")
        buckets.setdefault(ver, []).append(err)
    out: dict[str, dict[str, Any]] = {}
    for ver, errors in buckets.items():
        out[ver] = {
            "n": len(errors),
            "mae": round(sum(errors) / len(errors), 3) if errors else None,
        }
    return out


def _game_key(row) -> tuple:
    return (row.game_date, row.home_team_name, row.away_team_name)


def _ats_covered(
    recommendation: Optional[str],
    actual_margin: int | None,
    market_spread_home: float | None,
) -> bool | None:
    """Return True/False if pick covered; None for pushes or no-play."""
    if not recommendation or recommendation == "NO_PLAY" or market_spread_home is None:
        return None
    if actual_margin is None:
        return None
    threshold = -market_spread_home
    if actual_margin == threshold:
        return None
    if recommendation == "HOME":
        return actual_margin > threshold
    if recommendation == "AWAY":
        return actual_margin < threshold
    return None


def _is_ats_push(recommendation, actual_margin, market_spread_home) -> bool:
    return (
        recommendation in ("HOME", "AWAY")
        and actual_margin is not None
        and market_spread_home is not None
        and actual_margin == -market_spread_home
    )


def _merge_actuals_spread(projections, actuals) -> list[dict[str, Any]]:
    by_key = {_game_key(a): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        a = by_key.get(_game_key(p))
        actual_margin = a.actual_margin if a else None
        out.append(
            {
                "id": getattr(p, "id", None),
                "projected_margin": p.projected_margin,
                "market_spread_home": p.market_spread_home,
                "recommendation": p.recommendation,
                "actual_margin": actual_margin,
                "spread_correct": _ats_covered(
                    p.recommendation, actual_margin, p.market_spread_home
                ),
                "spread_push": _is_ats_push(
                    p.recommendation, actual_margin, p.market_spread_home
                ),
                "actual_home_score": getattr(a, "home_score", None),
                "actual_away_score": getattr(a, "away_score", None),
                "actual_winner": (
                    None
                    if getattr(a, "home_won", None) is None
                    else ("home" if a.home_won else "away")
                ),
            }
        )
    return out


def _merge_actuals_totals(projections, actuals) -> list[dict[str, Any]]:
    by_key = {_game_key(a): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        a = by_key.get(_game_key(p))
        out.append(
            {
                "id": getattr(p, "id", None),
                "projected_total": p.projected_total,
                "market_total": p.market_total,
                "recommendation": p.recommendation,
                "actual_total": a.actual_total if a else None,
                "actual_home_score": getattr(a, "home_actual_score", None),
                "actual_away_score": getattr(a, "away_actual_score", None),
            }
        )
    return out


def _merge_actuals_anytime_td(projections, actuals) -> list[dict[str, Any]]:
    by_key = {(a.season, a.week, a.player_id): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in projections:
        key = (p.season, p.week, p.player_id)
        a = by_key.get(key)
        out.append(
            {
                "td_probability": p.td_probability,
                "scored_anytime_td": a.scored_anytime_td if a else None,
            }
        )
    return out


def _recv_rows_for(db: Session, proj_filter, actual_filter) -> list[dict[str, Any]]:
    proj = db.query(RecvYdsPredictions).filter(proj_filter).all()
    actuals = db.query(RecvYdsActuals).filter(actual_filter).all()
    return _merge_actuals_recv(proj, actuals)


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NFL accuracy summary for `target_date`."""

    qb_proj = (
        db.query(QBPredictions)
        .filter(func.date(QBPredictions.game_date) == target_date)
        .all()
    )
    qb_actuals = (
        db.query(QBActuals).filter(func.date(QBActuals.game_date) == target_date).all()
    )
    qb_rows = _merge_actuals_qb(qb_proj, qb_actuals)

    recv_rows = _recv_rows_for(
        db,
        RecvYdsPredictions.game_date == target_date,
        RecvYdsActuals.game_date == target_date,
    )

    k_proj = (
        db.query(KickerPredictions)
        .filter(func.date(KickerPredictions.game_date) == target_date)
        .all()
    )
    k_actuals = db.query(KickerActuals).filter(KickerActuals.date == target_date).all()
    k_rows = _merge_actuals_kicker(k_proj, k_actuals)

    spread_proj = (
        db.query(NFLSpreadProjections)
        .filter(NFLSpreadProjections.game_date == target_date)
        .all()
    )
    spread_actuals = (
        db.query(NFLSpreadActuals)
        .filter(NFLSpreadActuals.game_date == target_date)
        .all()
    )
    spread_rows = _merge_actuals_spread(spread_proj, spread_actuals)

    totals_proj = (
        db.query(NFLTotalsProjections)
        .filter(NFLTotalsProjections.game_date == target_date)
        .all()
    )
    totals_actuals = (
        db.query(NFLTotalsActuals)
        .filter(NFLTotalsActuals.game_date == target_date)
        .all()
    )
    totals_rows = _merge_actuals_totals(totals_proj, totals_actuals)

    anytime_proj = (
        db.query(NFLAnytimeTDPredictions)
        .filter(
            NFLAnytimeTDPredictions.game_date == target_date,
            NFLAnytimeTDPredictions.position.in_(ANYTIME_TD_POSITIONS),
        )
        .all()
    )
    anytime_actuals = (
        db.query(NFLAnytimeTDActuals)
        .filter(
            NFLAnytimeTDActuals.game_date == target_date,
            NFLAnytimeTDActuals.position.in_(ANYTIME_TD_POSITIONS),
        )
        .all()
    )
    anytime_rows = _merge_actuals_anytime_td(anytime_proj, anytime_actuals)

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            qb_rows,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_passing_yards",
            projected_field="predicted_passing_yards",
            label="QB Pass Yds O/U",
            key="qb_passing_ou",
        ),
        mae_bucket(
            qb_rows,
            projected_field="predicted_passing_yards",
            actual_field="actual_passing_yards",
            label="QB Passing Yds",
            key="qb_passing_mae",
            unit_label="yds",
        ),
        ou_call_bucket(
            recv_rows,
            line_field="ou_line",
            pick_field="betting_recommendation",
            actual_field="actual_receiving_yards",
            projected_field="predicted_receiving_yards",
            label="Receiving Yds O/U",
            key="recv_yds_ou",
        ),
        mae_bucket(
            k_rows,
            projected_field="predicted_fg_made",
            actual_field="actual_field_goals_made",
            label="Kicker FG Made",
            key="kicker_fg_mae",
            unit_label="FG",
        ),
        edge_play_bucket(
            spread_rows,
            pick_field="recommendation",
            correct_field="spread_correct",
            label="Spread ATS",
            key="spread_ats",
            secondary="Spread edge plays vs market line",
        ),
        ou_call_bucket(
            totals_rows,
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
            projected_field="projected_total",
            label="Game Totals O/U",
            key="totals_ou",
        ),
        brier_bucket(
            anytime_rows,
            prob_field="td_probability",
            actual_field="scored_anytime_td",
            label="Anytime TD",
            key="anytime_td_brier",
        ),
    ]

    # NFL-7: a lined QB who never played has no actual row (books void it); say so.
    voided = ou_call_graded_breakdown(
        qb_rows,
        line_field="ou_line",
        pick_field="betting_recommendation",
        actual_field="actual_passing_yards",
    )["missing_actual"]
    if voided:
        buckets[0].secondary += f" · {voided} no actual"

    assembled = assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(
            qb_rows or recv_rows or k_rows or spread_rows or totals_rows or anytime_rows
        ),
    )
    assembled["by_model_version"] = {
        "qb_passing_mae": mae_by_model_version(
            qb_rows,
            projected_field="predicted_passing_yards",
            actual_field="actual_passing_yards",
        ),
        "kicker_fg_mae": mae_by_model_version(
            k_rows,
            projected_field="predicted_fg_made",
            actual_field="actual_field_goals_made",
        ),
    }
    return assembled


def _window_rows(db: Session, *, start: date_type, end: date_type) -> dict[str, list]:
    """Row sets behind the NFL overview: QB, receiving, game totals, spreads."""
    qb_proj = (
        db.query(QBPredictions)
        .filter(
            func.date(QBPredictions.game_date) >= start,
            func.date(QBPredictions.game_date) <= end,
        )
        .all()
    )
    qb_actuals = (
        db.query(QBActuals)
        .filter(
            func.date(QBActuals.game_date) >= start,
            func.date(QBActuals.game_date) <= end,
        )
        .all()
    )
    recv = _recv_rows_for(
        db,
        (RecvYdsPredictions.game_date >= start) & (RecvYdsPredictions.game_date <= end),
        (RecvYdsActuals.game_date >= start) & (RecvYdsActuals.game_date <= end),
    )
    spread_proj = (
        db.query(NFLSpreadProjections)
        .filter(
            NFLSpreadProjections.game_date >= start,
            NFLSpreadProjections.game_date <= end,
        )
        .all()
    )
    spread_actuals = (
        db.query(NFLSpreadActuals)
        .filter(NFLSpreadActuals.game_date >= start, NFLSpreadActuals.game_date <= end)
        .all()
    )
    totals_proj = (
        db.query(NFLTotalsProjections)
        .filter(
            NFLTotalsProjections.game_date >= start,
            NFLTotalsProjections.game_date <= end,
        )
        .all()
    )
    totals_actuals = (
        db.query(NFLTotalsActuals)
        .filter(NFLTotalsActuals.game_date >= start, NFLTotalsActuals.game_date <= end)
        .all()
    )
    return {
        "qb": _merge_actuals_qb_range(qb_proj, qb_actuals),
        "recv": recv,
        "totals": _merge_actuals_totals(totals_proj, totals_actuals),
        "spread": _merge_actuals_spread(spread_proj, spread_actuals),
    }


_OU_SPECS = (
    # key, label, row set, line, pick, actual
    (
        "qb_passing_ou",
        "QB Pass Yds O/U",
        "qb",
        "ou_line",
        "betting_recommendation",
        "actual_passing_yards",
    ),
    (
        "recv_yds_ou",
        "Receiving Yds O/U",
        "recv",
        "ou_line",
        "betting_recommendation",
        "actual_receiving_yards",
    ),
    (
        "totals_ou",
        "Game Totals O/U",
        "totals",
        "market_total",
        "recommendation",
        "actual_total",
    ),
)


def _overview_markets(r: dict[str, list]) -> dict[str, tuple[int, int]]:
    markets = {
        label: ou_call_graded_counts(
            r[rk], line_field=lf, pick_field=pf, actual_field=af
        )
        for _key, label, rk, lf, pf, af in _OU_SPECS
    }
    markets["Spread ATS"] = edge_play_graded_counts(
        r["spread"], pick_field="recommendation", correct_field="spread_correct"
    )
    return markets


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window NFL accuracy: QB pass yds + receiving yds O/U, game totals O/U, spreads ATS."""
    r = _window_rows(db, start=start, end=end)
    return overview_item_from_markets(
        sport="nfl", label="NFL", markets=_overview_markets(r)
    )


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same row sets as ``season_overview``."""
    r = _window_rows(db, start=start, end=end)
    parts = []
    for key, label, rk, lf, pf, af in _OU_SPECS:
        bd = ou_call_graded_breakdown(
            r[rk], line_field=lf, pick_field=pf, actual_field=af
        )
        parts.append(
            {
                "key": key,
                "label": label,
                "kind": "ou",
                "breakdown": bd,
                "graded_correct": bd["graded_correct"],
                "graded_total": bd["graded_total"],
            }
        )
    sbd = edge_play_graded_breakdown(
        r["spread"], pick_field="recommendation", correct_field="spread_correct"
    )
    parts.append(
        {
            "key": "spread_ats",
            "label": "Spread ATS",
            "kind": "edge",
            "breakdown": sbd,
            "graded_correct": sbd["graded_correct"],
            "graded_total": sbd["graded_total"],
        }
    )
    return {
        "sport": "nfl",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview_item_from_markets(
            sport="nfl", label="NFL", markets=_overview_markets(r)
        ),
        "parts": parts,
    }


# ---------------------------------------------------------------------------
# Past-view per-row results (H-4): same rows + shared row graders as the tiles
# ---------------------------------------------------------------------------


def _ou_results(rows, *, line, pick, actual) -> dict[int, dict[str, Any]]:
    return {
        r["id"]: {
            "actual": r[actual],
            "result": ou_row_result(
                line=r[line],
                pick=r[pick],
                actual=r[actual],
                actual_expected=r.get("actual_expected", False),
            ),
        }
        for r in rows
        if r["id"] is not None
    }


def past_row_results(
    db: Session, *, target_date: date_type
) -> dict[str, dict[int, dict[str, Any]]]:
    """{response_key: {projection_row_id: {"actual", "result", ...}}} for one past date.

    Keys match GET /api/v1/predictions/nfl: qb_predictions,
    receiving_yards_predictions, spreads, totals.
    """
    qb_proj = (
        db.query(QBPredictions)
        .filter(func.date(QBPredictions.game_date) == target_date)
        .all()
    )
    qb_actuals = (
        db.query(QBActuals).filter(func.date(QBActuals.game_date) == target_date).all()
    )
    qb_rows = _merge_actuals_qb(qb_proj, qb_actuals)
    recv_rows = _recv_rows_for(
        db,
        RecvYdsPredictions.game_date == target_date,
        RecvYdsActuals.game_date == target_date,
    )

    spread_rows = _merge_actuals_spread(
        db.query(NFLSpreadProjections)
        .filter(NFLSpreadProjections.game_date == target_date)
        .all(),
        db.query(NFLSpreadActuals)
        .filter(NFLSpreadActuals.game_date == target_date)
        .all(),
    )
    totals_rows = _merge_actuals_totals(
        db.query(NFLTotalsProjections)
        .filter(NFLTotalsProjections.game_date == target_date)
        .all(),
        db.query(NFLTotalsActuals)
        .filter(NFLTotalsActuals.game_date == target_date)
        .all(),
    )

    totals = _ou_results(
        totals_rows, line="market_total", pick="recommendation", actual="actual_total"
    )
    for r in totals_rows:
        if r["id"] in totals:
            totals[r["id"]].update(
                actual_home_score=r["actual_home_score"],
                actual_away_score=r["actual_away_score"],
                actual_total=r["actual_total"],
                actual_total_runs=r["actual_total"],
            )
    spreads = {
        r["id"]: {
            "actual": r["actual_margin"],
            "result": edge_row_result(
                pick=r["recommendation"],
                correct_flag=r["spread_correct"],
                push=r["spread_push"],
            ),
            "actual_home_score": r["actual_home_score"],
            "actual_away_score": r["actual_away_score"],
            "actual_winner": r["actual_winner"],
        }
        for r in spread_rows
        if r["id"] is not None
    }
    return {
        "qb_predictions": _ou_results(
            qb_rows,
            line="ou_line",
            pick="betting_recommendation",
            actual="actual_passing_yards",
        ),
        "receiving_yards_predictions": _ou_results(
            recv_rows,
            line="ou_line",
            pick="betting_recommendation",
            actual="actual_receiving_yards",
        ),
        "spreads": spreads,
        "totals": totals,
    }
