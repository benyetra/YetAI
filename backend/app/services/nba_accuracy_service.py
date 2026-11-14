"""Per-day NBA projection accuracy → unified bucket shape.

Buckets (daily tile, season overview and the past view's per-row results all
come from the same row builders, so they cannot disagree):
- Props O/U vs the FanDuel line: points, 3P made, steals, assists, rebounds, PRA
  (blocks has no line column, so nothing to grade against)
- Game totals O/U (market_total + recommendation)
- Spreads ATS (market_spread_home + HOME/AWAY recommendation; push excluded)
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    ActualThreePointMade,
    AssistsActuals,
    AssistsProjections,
    NBASpreadActuals,
    NBASpreadProjections,
    NBATotalsActuals,
    NBATotalsProjections,
    PointsActuals,
    PointsProjections,
    PRAActuals,
    PRAProjections,
    ReboundsActuals,
    ReboundsProjections,
    StealsActuals,
    StealsProjections,
    ThreePointProjections,
)
from app.services.nfl_accuracy_service import mae_by_model_version
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    edge_play_bucket,
    edge_play_graded_breakdown,
    edge_play_graded_counts,
    edge_row_result,
    ou_call_bucket,
    ou_call_graded_breakdown,
    ou_call_graded_counts,
    ou_row_result,
    overview_item_from_markets,
)

# (response key in GET /predictions/nba, bucket key, label, overview/diag key,
#  projections, actuals, projected field, actual field)
_PROPS = (
    (
        "points",
        "points_ou",
        "Points O/U",
        PointsProjections,
        PointsActuals,
        "projected_points",
        "actual_points",
    ),
    (
        "three_point",
        "three_pt_ou",
        "3P Made O/U",
        ThreePointProjections,
        ActualThreePointMade,
        "projected_three_pt_made",
        "actual_three_pt_made",
    ),
    (
        "steals",
        "steals_ou",
        "Steals O/U",
        StealsProjections,
        StealsActuals,
        "projected_steals",
        "actual_steals",
    ),
    (
        "assists",
        "assists_ou",
        "Assists O/U",
        AssistsProjections,
        AssistsActuals,
        "projected_assists",
        "actual_assists",
    ),
    (
        "rebounds",
        "rebounds_ou",
        "Rebounds O/U",
        ReboundsProjections,
        ReboundsActuals,
        "projected_rebounds",
        "actual_rebounds",
    ),
    (
        "pra",
        "pra_ou",
        "PRA O/U",
        PRAProjections,
        PRAActuals,
        "projected_pra",
        "actual_pra",
    ),
)


def _merge_actuals_range(
    projections,
    actuals,
    *,
    pid_attr: str,
    actual_attr: str,
    actual_key: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pair projections with actuals on (player_id, calendar date).

    Returns merged row dicts plus projection dedupe stats (latest ``id`` wins).
    """
    raw_n = len(projections)
    latest_by_key: dict[tuple[Any, Any], Any] = {}
    for p in projections:
        key = (getattr(p, pid_attr), p.date)
        prev = latest_by_key.get(key)
        if prev is None or getattr(p, "id", 0) > getattr(prev, "id", 0):
            latest_by_key[key] = p

    by_key = {(getattr(a, pid_attr), a.date): a for a in actuals}
    out: list[dict[str, Any]] = []
    for p in latest_by_key.values():
        key = (getattr(p, pid_attr), p.date)
        a = by_key.get(key)
        row: dict[str, Any] = {c.name: getattr(p, c.name) for c in p.__table__.columns}
        row[actual_key] = getattr(a, actual_attr) if a else None
        out.append(row)
    stats = {
        "projection_rows_raw": raw_n,
        "projection_rows_deduped": len(latest_by_key),
        "merged_rows": len(out),
    }
    return out, stats


def _prop_rows(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, tuple[list[dict[str, Any]], dict[str, int]]]:
    """Merged, deduped rows per prop (latest projection id per player+date)."""
    out = {}
    for rk, _bk, _label, proj_cls, act_cls, _pf, actual_f in _PROPS:
        proj = (
            db.query(proj_cls)
            .filter(proj_cls.date >= start, proj_cls.date <= end)
            .all()
        )
        act = db.query(act_cls).filter(act_cls.date >= start, act_cls.date <= end).all()
        rows, stats = _merge_actuals_range(
            proj, act, pid_attr="player_id", actual_attr=actual_f, actual_key=actual_f
        )
        graded_dates = {a.date for a in act}
        for r in rows:
            # Grading ran for that date → a missing player actual is a DNP.
            r["actual_expected"] = r["date"] in graded_dates
        out[rk] = (rows, stats)
    return out


def _nba_season_window_rows(
    db: Session, *, start: date_type, end: date_type
) -> list[tuple[str, str, list[dict[str, Any]], dict[str, int]]]:
    """(bucket key, label, merged rows, merge stats) per prop over a window."""
    props = _prop_rows(db, start=start, end=end)
    return [(bk, label, *props[rk]) for rk, bk, label, *_ in _PROPS]


def _upper(value: Any) -> str:
    return str(value or "").strip().upper()


def _game_rows(
    db: Session, *, start: date_type, end: date_type
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(totals rows, spread rows) with their actuals and the ATS grade."""

    def _in_range(model):
        return (
            db.query(model)
            .filter(model.game_date >= start, model.game_date <= end)
            .all()
        )

    def _key(r):
        return (r.game_date, r.home_team_name, r.away_team_name)

    total_actuals = _in_range(NBATotalsActuals)
    by_total = {_key(a): a for a in total_actuals}
    total_dates = {a.game_date for a in total_actuals}
    totals: list[dict[str, Any]] = []
    for p in _in_range(NBATotalsProjections):
        a = by_total.get(_key(p))
        totals.append(
            {
                "id": p.id,
                "game_date": p.game_date,
                "projected_total": p.projected_total,
                "market_total": p.market_total,
                "pick": _upper(p.recommendation),
                "actual_total": a.actual_total if a else None,
                "actual_home_score": a.home_actual_score if a else None,
                "actual_away_score": a.away_actual_score if a else None,
                "actual_expected": p.game_date in total_dates,
            }
        )

    spread_actuals = _in_range(NBASpreadActuals)
    by_spread = {_key(a): a for a in spread_actuals}
    spread_dates = {a.game_date for a in spread_actuals}
    spreads: list[dict[str, Any]] = []
    for p in _in_range(NBASpreadProjections):
        a = by_spread.get(_key(p))
        pick = _upper(p.recommendation)
        line = p.market_spread_home
        if pick not in ("HOME", "AWAY") or line is None:
            pick = "NO_PLAY"
        margin = a.actual_margin if a else None
        correct = push = None
        if margin is not None and pick != "NO_PLAY":
            # home covers when margin > -market_spread_home
            threshold = -line
            push = margin == threshold
            if not push:
                correct = (margin > threshold) == (pick == "HOME")
        spreads.append(
            {
                "id": p.id,
                "game_date": p.game_date,
                "projected_margin": p.projected_margin,
                "market_spread_home": line,
                "ats_pick": pick,
                "ats_correct": correct,
                "ats_push": bool(push),
                "actual_margin": margin,
                "actual_home_score": a.home_score if a else None,
                "actual_away_score": a.away_score if a else None,
                "actual_winner": (
                    None if a is None else "home" if a.home_won else "away"
                ),
                "actual_expected": p.game_date in spread_dates,
            }
        )
    return totals, spreads


def past_row_results(
    db: Session, *, target_date: date_type
) -> dict[str, dict[int, dict[str, Any]]]:
    """{response_key: {projection id: {"actual", "result", ...}}} for one past date.

    Covers every row for the date (the past view's top-N cap is applied elsewhere).
    Rows superseded by a later projection for the same player are absent.
    """
    out: dict[str, dict[int, dict[str, Any]]] = {}
    props = _prop_rows(db, start=target_date, end=target_date)
    for rk, _bk, _label, _pc, _ac, _pf, actual_f in _PROPS:
        out[rk] = {
            r["id"]: {
                "actual": r[actual_f],
                "result": ou_row_result(
                    line=r.get("fanduel_line"),
                    pick=r.get("fanduel_over_under"),
                    actual=r[actual_f],
                    actual_expected=r["actual_expected"],
                ),
            }
            for r in props[rk][0]
        }
    totals, spreads = _game_rows(db, start=target_date, end=target_date)
    out["totals"] = {}
    for r in totals:
        res = ou_row_result(
            line=r["market_total"],
            pick=r["pick"],
            actual=r["actual_total"],
            actual_expected=r["actual_expected"],
        )
        out["totals"][r["id"]] = {
            "actual": r["actual_total"],
            "result": res,
            "actual_total": r["actual_total"],
            "actual_home_score": r["actual_home_score"],
            "actual_away_score": r["actual_away_score"],
            "total_correct": res == "hit" if res in ("hit", "miss") else None,
        }
    out["spreads"] = {}
    for r in spreads:
        res = edge_row_result(
            pick=r["ats_pick"],
            correct_flag=r["ats_correct"],
            push=r["ats_push"],
            actual_expected=r["actual_expected"],
        )
        out["spreads"][r["id"]] = {
            "actual": r["actual_margin"],
            "result": res,
            "actual_home_score": r["actual_home_score"],
            "actual_away_score": r["actual_away_score"],
            "actual_winner": r["actual_winner"],
            "spread_correct": res == "hit" if res in ("hit", "miss") else None,
        }
    return out


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NBA accuracy summary for `target_date`."""
    props = _prop_rows(db, start=target_date, end=target_date)
    totals, spreads = _game_rows(db, start=target_date, end=target_date)

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            props[rk][0],
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field=actual_f,
            projected_field=proj_f,
            label=label,
            key=bk,
            price_field="fanduel_price",
        )
        for rk, bk, label, _pc, _ac, proj_f, actual_f in _PROPS
    ]
    buckets.append(
        ou_call_bucket(
            totals,
            line_field="market_total",
            pick_field="pick",
            actual_field="actual_total",
            projected_field="projected_total",
            label="Game Totals O/U",
            key="totals_ou",
        )
    )
    buckets.append(
        edge_play_bucket(
            spreads,
            pick_field="ats_pick",
            correct_field="ats_correct",
            label="Spreads ATS",
            key="spread_ats",
        )
    )
    available = any(rows for rows, _ in props.values()) or bool(totals or spreads)
    assembled = assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=available,
    )
    assembled["by_model_version"] = {
        f"{rk}_mae": mae_by_model_version(
            props[rk][0], projected_field=proj_f, actual_field=actual_f
        )
        for rk, _bk, _label, _pc, _ac, proj_f, actual_f in _PROPS
    }
    return assembled


def _overview_parts(
    db: Session, *, start: date_type, end: date_type
) -> list[dict[str, Any]]:
    """One entry per published market: counts + breakdown + merge stats."""
    props = _prop_rows(db, start=start, end=end)
    totals, spreads = _game_rows(db, start=start, end=end)
    parts: list[dict[str, Any]] = []
    for rk, bk, label, _pc, _ac, _pf, actual_f in _PROPS:
        rows, merge = props[rk]
        bd = ou_call_graded_breakdown(
            rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field=actual_f,
            price_field="fanduel_price",
        )
        parts.append(
            {
                "key": bk,
                "label": label,
                "actual_field": actual_f,
                "merge": merge,
                "breakdown": bd,
            }
        )
    parts.append(
        {
            "key": "totals_ou",
            "label": "Game totals O/U",
            "actual_field": "actual_total",
            "breakdown": ou_call_graded_breakdown(
                totals,
                line_field="market_total",
                pick_field="pick",
                actual_field="actual_total",
            ),
        }
    )
    parts.append(
        {
            "key": "spread_ats",
            "label": "Spreads ATS",
            "actual_field": "actual_margin",
            "breakdown": edge_play_graded_breakdown(
                spreads, pick_field="ats_pick", correct_field="ats_correct"
            ),
        }
    )
    for p in parts:
        p["graded_correct"] = p["breakdown"]["graded_correct"]
        p["graded_total"] = p["breakdown"]["graded_total"]
    return parts


def _overview_item(parts: list[dict[str, Any]]) -> dict[str, Any]:
    return overview_item_from_markets(
        sport="nba",
        label="NBA",
        markets={p["label"]: (p["graded_correct"], p["graded_total"]) for p in parts},
    )


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window NBA accuracy — every published O/U and ATS market, one definition."""
    return _overview_item(_overview_parts(db, start=start, end=end))


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same window rules as ``season_overview``."""
    parts = _overview_parts(db, start=start, end=end)
    return {
        "sport": "nba",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": _overview_item(parts),
        "parts": parts,
    }
