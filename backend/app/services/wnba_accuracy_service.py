"""Per-day WNBA projection accuracy → unified bucket shape.

Buckets:

- Game Totals O/U (market_total + recommendation)
- Game Totals MAE
- Spread Margin MAE
- Spread ATS (HOME/AWAY edge plays vs market line; pushes excluded)
- Points O/U (per-player; uses market_line + recommendation)
- Assists O/U (per-player)
- Rebounds O/U (per-player)

The per-player projections + actuals tables are populated by the
existing `generate_*_predictions.py` and `calculate_prediction_accuracy.py`
ETLs. This service just surfaces them in the accuracy summary.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    WNBAAssistsActuals,
    WNBAAssistsProjections,
    WNBAPointsActuals,
    WNBAPointsProjections,
    WNBAPRAActuals,
    WNBAPRAProjections,
    WNBAReboundsActuals,
    WNBAReboundsProjections,
    WNBASpreadActuals,
    WNBASpreadProjections,
    WNBAThreePtMadeActuals,
    WNBAThreePtMadeProjections,
    WNBATotalsActuals,
    WNBATotalsProjections,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    mae_bucket,
    ou_call_bucket,
    ou_call_graded_breakdown,
    edge_play_bucket,
    edge_play_graded_breakdown,
    edge_play_graded_counts,
    edge_row_result,
    ou_call_graded_counts,
    ou_row_result,
    overview_item_from_markets,
)


def _pick(recommendation: Optional[str]) -> Optional[str]:
    if not recommendation:
        return None
    head = recommendation.strip().split(" ", 1)[0].lower()
    return head if head in ("over", "under") else None


def _game_key(row) -> tuple:
    return (row.game_date, row.home_team_name, row.away_team_name)


def _spread_pick(recommendation: Optional[str]) -> Optional[str]:
    rec = (recommendation or "").strip().upper()
    return rec if rec in ("HOME", "AWAY") else None


def _ats(pick: Optional[str], actual_margin, market_spread_home):
    """(covered, push) for a HOME/AWAY pick; (None, False) when ungradable."""
    if pick is None or market_spread_home is None or actual_margin is None:
        return None, False
    threshold = -float(market_spread_home)
    if actual_margin == threshold:
        return None, True
    return (actual_margin > threshold) == (pick == "HOME"), False


def _totals_rows(proj, actuals) -> list[dict[str, Any]]:
    by_key = {_game_key(a): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_key.get(_game_key(p))
        rows.append(
            {
                "id": getattr(p, "id", None),
                "projected_total": p.projected_total,
                "market_total": p.market_total,
                "recommendation": _pick(p.recommendation),
                "actual_total": a.actual_total if a else None,
                "actual_home_score": getattr(a, "home_score", None),
                "actual_away_score": getattr(a, "away_score", None),
            }
        )
    return rows


def _winner(a) -> Optional[str]:
    won = getattr(a, "home_won", None)
    return None if won is None else ("home" if won else "away")


def _spread_rows(proj, actuals) -> list[dict[str, Any]]:
    by_key = {_game_key(a): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_key.get(_game_key(p))
        margin = a.actual_margin if a else None
        market = getattr(p, "market_spread_home", None)
        pick = _spread_pick(getattr(p, "recommendation", None))
        covered, push = _ats(pick, margin, market)
        rows.append(
            {
                "id": getattr(p, "id", None),
                "projected_margin": p.projected_margin,
                "market_spread_home": market,
                "recommendation": pick,
                "actual_margin": margin,
                "spread_correct": covered,
                "spread_push": push,
                "actual_home_score": getattr(a, "home_score", None),
                "actual_away_score": getattr(a, "away_score", None),
                "actual_winner": _winner(a),
            }
        )
    return rows


def _player_prop_rows_range(
    db: Session,
    start: date_type,
    end: date_type,
    projections_cls,
    actuals_cls,
    *,
    proj_field: str,
    actual_field: str,
) -> list[dict[str, Any]]:
    proj = (
        db.query(projections_cls)
        .filter(projections_cls.date >= start, projections_cls.date <= end)
        .all()
    )
    actuals = (
        db.query(actuals_cls)
        .filter(actuals_cls.date >= start, actuals_cls.date <= end)
        .all()
    )
    by_key = {(a.player_id, a.date): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_key.get((p.player_id, p.date))
        rows.append(
            {
                "id": getattr(p, "id", None),
                proj_field: getattr(p, proj_field),
                "market_line": p.market_line,
                "recommendation": _pick(p.recommendation),
                actual_field: getattr(a, actual_field) if a else None,
            }
        )
    return rows


def _player_prop_rows(
    db: Session,
    target_date: date_type,
    projections_cls,
    actuals_cls,
    *,
    proj_field: str,
    actual_field: str,
) -> list[dict[str, Any]]:
    """Build per-player rows for a points/assists/rebounds prop.

    Both projection and actuals tables have a `date` column (not `game_date`)
    via the WNBA _make_prop_projection / _make_prop_actuals factory.
    """
    proj = db.query(projections_cls).filter(projections_cls.date == target_date).all()
    actuals = db.query(actuals_cls).filter(actuals_cls.date == target_date).all()
    by_pid = {a.player_id: a for a in actuals}

    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_pid.get(p.player_id)
        rows.append(
            {
                "id": getattr(p, "id", None),
                proj_field: getattr(p, proj_field),
                "market_line": p.market_line,
                "recommendation": _pick(p.recommendation),
                actual_field: getattr(a, actual_field) if a else None,
                # grading ran for this prop today: a missing actual is a DNP
                "actual_expected": bool(actuals),
            }
        )
    return rows


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the WNBA accuracy summary for `target_date`."""

    # --- Game totals ----------------------------------------------------
    totals_proj = (
        db.query(WNBATotalsProjections)
        .filter(WNBATotalsProjections.game_date == target_date)
        .all()
    )
    totals_actuals = (
        db.query(WNBATotalsActuals)
        .filter(WNBATotalsActuals.game_date == target_date)
        .all()
    )
    totals_rows = _totals_rows(totals_proj, totals_actuals)

    # --- Spread ---------------------------------------------------------
    spread_proj = (
        db.query(WNBASpreadProjections)
        .filter(WNBASpreadProjections.game_date == target_date)
        .all()
    )
    spread_actuals = (
        db.query(WNBASpreadActuals)
        .filter(WNBASpreadActuals.game_date == target_date)
        .all()
    )
    spread_rows = _spread_rows(spread_proj, spread_actuals)

    # --- Per-player props ----------------------------------------------
    points_rows = _player_prop_rows(
        db,
        target_date,
        WNBAPointsProjections,
        WNBAPointsActuals,
        proj_field="projected_points",
        actual_field="actual_points",
    )
    assists_rows = _player_prop_rows(
        db,
        target_date,
        WNBAAssistsProjections,
        WNBAAssistsActuals,
        proj_field="projected_assists",
        actual_field="actual_assists",
    )
    rebounds_rows = _player_prop_rows(
        db,
        target_date,
        WNBAReboundsProjections,
        WNBAReboundsActuals,
        proj_field="projected_rebounds",
        actual_field="actual_rebounds",
    )
    threes_rows = _player_prop_rows(
        db,
        target_date,
        WNBAThreePtMadeProjections,
        WNBAThreePtMadeActuals,
        proj_field="projected_three_pt_made",
        actual_field="actual_three_pt_made",
    )
    pra_rows = _player_prop_rows(
        db,
        target_date,
        WNBAPRAProjections,
        WNBAPRAActuals,
        proj_field="projected_pra",
        actual_field="actual_pra",
    )

    buckets: list[AccuracyBucket] = [
        ou_call_bucket(
            totals_rows,
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
            projected_field="projected_total",
            label="Game Totals O/U",
            key="totals_ou",
        ),
        mae_bucket(
            totals_rows,
            projected_field="projected_total",
            actual_field="actual_total",
            label="Game Totals",
            key="totals_mae",
            unit_label="pts",
        ),
        mae_bucket(
            spread_rows,
            projected_field="projected_margin",
            actual_field="actual_margin",
            label="Spread Margin",
            key="spread_mae",
            unit_label="pts",
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
            points_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_points",
            projected_field="projected_points",
            label="Player Points O/U",
            key="player_points_ou",
        ),
        ou_call_bucket(
            assists_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_assists",
            projected_field="projected_assists",
            label="Player Assists O/U",
            key="player_assists_ou",
        ),
        ou_call_bucket(
            rebounds_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_rebounds",
            projected_field="projected_rebounds",
            label="Player Rebounds O/U",
            key="player_rebounds_ou",
        ),
        ou_call_bucket(
            threes_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_three_pt_made",
            projected_field="projected_three_pt_made",
            label="Player 3PM O/U",
            key="player_three_pt_made_ou",
        ),
        ou_call_bucket(
            pra_rows,
            line_field="market_line",
            pick_field="recommendation",
            actual_field="actual_pra",
            projected_field="projected_pra",
            label="Player PRA O/U",
            key="player_pra_ou",
        ),
    ]

    available = bool(
        totals_rows
        or spread_rows
        or points_rows
        or assists_rows
        or rebounds_rows
        or threes_rows
        or pra_rows
    )
    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=available,
    )


def _wnba_season_overview_row_sets(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, list[dict[str, Any]]]:
    """Row dicts for the WNBA overview sources (totals, spread ATS, props)."""
    totals_proj = (
        db.query(WNBATotalsProjections)
        .filter(
            WNBATotalsProjections.game_date >= start,
            WNBATotalsProjections.game_date <= end,
        )
        .all()
    )
    totals_actuals = (
        db.query(WNBATotalsActuals)
        .filter(
            WNBATotalsActuals.game_date >= start,
            WNBATotalsActuals.game_date <= end,
        )
        .all()
    )
    totals_rows = _totals_rows(totals_proj, totals_actuals)

    spread_proj = (
        db.query(WNBASpreadProjections)
        .filter(
            WNBASpreadProjections.game_date >= start,
            WNBASpreadProjections.game_date <= end,
        )
        .all()
    )
    spread_actuals = (
        db.query(WNBASpreadActuals)
        .filter(
            WNBASpreadActuals.game_date >= start,
            WNBASpreadActuals.game_date <= end,
        )
        .all()
    )
    spread_rows = _spread_rows(spread_proj, spread_actuals)

    points_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAPointsProjections,
        WNBAPointsActuals,
        proj_field="projected_points",
        actual_field="actual_points",
    )
    assists_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAAssistsProjections,
        WNBAAssistsActuals,
        proj_field="projected_assists",
        actual_field="actual_assists",
    )
    rebounds_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAReboundsProjections,
        WNBAReboundsActuals,
        proj_field="projected_rebounds",
        actual_field="actual_rebounds",
    )
    threes_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAThreePtMadeProjections,
        WNBAThreePtMadeActuals,
        proj_field="projected_three_pt_made",
        actual_field="actual_three_pt_made",
    )
    pra_rows = _player_prop_rows_range(
        db,
        start,
        end,
        WNBAPRAProjections,
        WNBAPRAActuals,
        proj_field="projected_pra",
        actual_field="actual_pra",
    )
    return {
        "totals": totals_rows,
        "spread": spread_rows,
        "points": points_rows,
        "assists": assists_rows,
        "rebounds": rebounds_rows,
        "three_pt_made": threes_rows,
        "pra": pra_rows,
    }


def _overview_markets(r: dict[str, list[dict[str, Any]]]) -> dict[str, tuple[int, int]]:
    """One entry per published market that has a line and an over/under or side call."""
    markets = {
        "Game totals O/U": ou_call_graded_counts(
            r["totals"],
            line_field="market_total",
            pick_field="recommendation",
            actual_field="actual_total",
        ),
        "Spread ATS": edge_play_graded_counts(
            r["spread"], pick_field="recommendation", correct_field="spread_correct"
        ),
    }
    for name, key, actual in (
        ("Points O/U", "points", "actual_points"),
        ("Assists O/U", "assists", "actual_assists"),
        ("Rebounds O/U", "rebounds", "actual_rebounds"),
        ("3PM O/U", "three_pt_made", "actual_three_pt_made"),
        ("PRA O/U", "pra", "actual_pra"),
    ):
        markets[name] = ou_call_graded_counts(
            r[key],
            line_field="market_line",
            pick_field="recommendation",
            actual_field=actual,
        )
    return markets


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window WNBA accuracy — game totals O/U, spread ATS and player props O/U."""
    r = _wnba_season_overview_row_sets(db, start=start, end=end)
    return overview_item_from_markets(
        sport="wnba", label="WNBA", markets=_overview_markets(r)
    )


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same row sets as ``season_overview``."""
    r = _wnba_season_overview_row_sets(db, start=start, end=end)
    specs = [
        (
            "game_totals_ou",
            "Game totals O/U",
            "totals",
            "market_total",
            "recommendation",
            "actual_total",
        ),
        (
            "points_ou",
            "Points O/U",
            "points",
            "market_line",
            "recommendation",
            "actual_points",
        ),
        (
            "assists_ou",
            "Assists O/U",
            "assists",
            "market_line",
            "recommendation",
            "actual_assists",
        ),
        (
            "rebounds_ou",
            "Rebounds O/U",
            "rebounds",
            "market_line",
            "recommendation",
            "actual_rebounds",
        ),
        (
            "three_pt_made_ou",
            "3PM O/U",
            "three_pt_made",
            "market_line",
            "recommendation",
            "actual_three_pt_made",
        ),
        (
            "pra_ou",
            "PRA O/U",
            "pra",
            "market_line",
            "recommendation",
            "actual_pra",
        ),
    ]
    parts_out: list[dict[str, Any]] = []
    for key, label, rk, lf, pf, af in specs:
        rows = r[rk]
        bd = ou_call_graded_breakdown(
            rows, line_field=lf, pick_field=pf, actual_field=af
        )
        c, t = bd["graded_correct"], bd["graded_total"]
        parts_out.append(
            {
                "key": key,
                "label": label,
                "kind": "ou",
                "breakdown": bd,
                "graded_correct": c,
                "graded_total": t,
            }
        )
    sbd = edge_play_graded_breakdown(
        r["spread"], pick_field="recommendation", correct_field="spread_correct"
    )
    parts_out.insert(
        1,
        {
            "key": "spread_ats",
            "label": "Spread ATS",
            "kind": "edge",
            "breakdown": sbd,
            "graded_correct": sbd["graded_correct"],
            "graded_total": sbd["graded_total"],
        },
    )
    return {
        "sport": "wnba",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview_item_from_markets(
            sport="wnba", label="WNBA", markets=_overview_markets(r)
        ),
        "parts": parts_out,
    }


# ---------------------------------------------------------------------------
# Past-view per-row results (H-4): same rows + shared row graders as the tiles
# ---------------------------------------------------------------------------

# GET /api/v1/predictions/wnba list key -> (projections, actuals, projected, actual)
_PROP_PAST = {
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
    "three_point": (
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


def _game_rows(db: Session, proj_cls, act_cls, target_date: date_type):
    proj = db.query(proj_cls).filter(proj_cls.game_date == target_date).all()
    actuals = db.query(act_cls).filter(act_cls.game_date == target_date).all()
    return proj, actuals


def past_row_results(
    db: Session, *, target_date: date_type
) -> dict[str, dict[int, dict[str, Any]]]:
    """{response_key: {projection_row_id: {"actual", "result", ...}}} for one past date."""
    out: dict[str, dict[int, dict[str, Any]]] = {}

    for key, (proj_cls, act_cls, proj_field, actual_field) in _PROP_PAST.items():
        rows = _player_prop_rows(
            db,
            target_date,
            proj_cls,
            act_cls,
            proj_field=proj_field,
            actual_field=actual_field,
        )
        out[key] = {
            r["id"]: {
                "actual": r[actual_field],
                "result": ou_row_result(
                    line=r["market_line"],
                    pick=r["recommendation"],
                    actual=r[actual_field],
                    actual_expected=r["actual_expected"],
                ),
            }
            for r in rows
            if r["id"] is not None
        }

    totals_rows = _totals_rows(
        *_game_rows(db, WNBATotalsProjections, WNBATotalsActuals, target_date)
    )
    out["totals"] = {
        r["id"]: {
            "actual": r["actual_total"],
            "result": ou_row_result(
                line=r["market_total"],
                pick=r["recommendation"],
                actual=r["actual_total"],
            ),
            "actual_home_score": r["actual_home_score"],
            "actual_away_score": r["actual_away_score"],
            "actual_total": r["actual_total"],
            "actual_total_runs": r["actual_total"],
        }
        for r in totals_rows
        if r["id"] is not None
    }
    spread_rows = _spread_rows(
        *_game_rows(db, WNBASpreadProjections, WNBASpreadActuals, target_date)
    )
    out["spreads"] = {
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
    return out
