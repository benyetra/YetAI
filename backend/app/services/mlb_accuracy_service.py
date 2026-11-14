"""Per-day MLB projection accuracy → unified bucket shape.

Buckets:
- Pitcher Ks O/U, Projected Hits, Projected Home Runs (prop boards)
- Game Moneyline, Spread, Total (edge plays from game projections)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date as date_type
from typing import Any

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    GameActuals,
    GameProjections,
    HitActuals,
    HomerActuals,
    ProjectedHits,
    ProjectedHomers,
    StrikeoutActuals,
    StrikeoutProjections,
)
from app.services.accuracy_shared import (
    assemble,
    edge_play_bucket,
    edge_row_result,
    edge_play_graded_breakdown,
    edge_play_graded_counts,
    hit_rate_bucket,
    hit_rate_graded_breakdown,
    hit_rate_graded_counts,
    hit_rate_row_result,
    ou_call_bucket,
    ou_call_graded_breakdown,
    ou_call_graded_counts,
    ou_row_result,
    overview_item_from_markets,
)
from app.services.mlb_game_picks import enrich_game_projection_row


def _strikeout_accuracy_by_model_version(
    k_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]] | None:
    """Per-model_version O/U buckets when projections carry model_version."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in k_rows:
        version = row.get("model_version")
        if version:
            grouped[str(version)].append(row)
    if not grouped:
        return None
    return {
        version: ou_call_bucket(
            rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_strikeouts",
            projected_field="projected_strikeouts",
            label=f"Pitcher Ks O/U ({version})",
            key="pitcher_ks_ou",
        ).to_dict()
        for version, rows in sorted(grouped.items())
    }


def _batter_rows(
    db: Session,
    *,
    model: Any,
    actuals_model: Any,
    projected_field: str,
    actual_field: str,
    start: date_type,
    end: date_type,
) -> list[dict[str, Any]]:
    """Batter-board rows with ``actual`` set only when grading actually ran.

    ``actual_hits``/``actual_homers`` default to 0 on the projection row, so a
    rained-out, scratched or not-yet-graded batter looks like a real miss. A
    row is graded only when the actuals table has a row for (date, batter_id);
    otherwise its actual is None (ungraded, or dnp when that date was graded).
    """
    graded = {
        (a.date, str(a.batter_id))
        for a in db.query(actuals_model)
        .filter(actuals_model.date >= start, actuals_model.date <= end)
        .all()
    }
    graded_dates = {d for d, _ in graded}
    rows: list[dict[str, Any]] = []
    for r in db.query(model).filter(model.date >= start, model.date <= end).all():
        has_actual = (r.date, str(r.batter_id)) in graded
        rows.append(
            {
                "id": getattr(r, "id", None),
                projected_field: getattr(r, projected_field),
                actual_field: getattr(r, actual_field) if has_actual else None,
                "actual_expected": r.date in graded_dates,
            }
        )
    return rows


def _hits_rows(db: Session, *, start: date_type, end: date_type):
    return _batter_rows(
        db,
        model=ProjectedHits,
        actuals_model=HitActuals,
        projected_field="projected_hits",
        actual_field="actual_hits",
        start=start,
        end=end,
    )


def _homer_rows(db: Session, *, start: date_type, end: date_type):
    return _batter_rows(
        db,
        model=ProjectedHomers,
        actuals_model=HomerActuals,
        projected_field="projected_homers",
        actual_field="actual_homers",
        start=start,
        end=end,
    )


def _merge_game_rows_range(
    db: Session, *, start: date_type, end: date_type
) -> list[dict[str, Any]]:
    """Join game projections with final scores across a date range."""
    projections = (
        db.query(GameProjections)
        .filter(GameProjections.date >= start, GameProjections.date <= end)
        .all()
    )
    actuals_by_gid = {
        a.game_id: a
        for a in db.query(GameActuals)
        .filter(GameActuals.date >= start, GameActuals.date <= end)
        .all()
    }
    rows: list[dict[str, Any]] = []
    for proj in projections:
        row = {c.name: getattr(proj, c.name) for c in proj.__table__.columns}
        actual = actuals_by_gid.get(proj.game_id)
        if actual:
            row.update(
                {
                    "actual_home_score": actual.home_score,
                    "actual_away_score": actual.away_score,
                    "actual_total_runs": actual.total_runs,
                    "actual_winner": actual.winner,
                    "ml_correct": actual.ml_correct,
                    "spread_correct": actual.spread_correct,
                    "total_correct": actual.total_correct,
                }
            )
        rows.append(enrich_game_projection_row(row))
    return rows


def _merge_game_rows(db: Session, *, target_date: date_type) -> list[dict[str, Any]]:
    """Join game projections with final scores for grading buckets."""
    projections = (
        db.query(GameProjections).filter(GameProjections.date == target_date).all()
    )
    actuals_by_gid = {
        a.game_id: a
        for a in db.query(GameActuals).filter(GameActuals.date == target_date).all()
    }
    rows: list[dict[str, Any]] = []
    for proj in projections:
        row = {c.name: getattr(proj, c.name) for c in proj.__table__.columns}
        actual = actuals_by_gid.get(proj.game_id)
        if actual:
            row.update(
                {
                    "actual_home_score": actual.home_score,
                    "actual_away_score": actual.away_score,
                    "actual_total_runs": actual.total_runs,
                    "actual_winner": actual.winner,
                    "ml_correct": actual.ml_correct,
                    "spread_correct": actual.spread_correct,
                    "total_correct": actual.total_correct,
                }
            )
        rows.append(enrich_game_projection_row(row))
    return rows


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Fetch the day's MLB projections + actuals, return the bucketed summary."""
    proj_rows = (
        db.query(StrikeoutProjections)
        .filter(StrikeoutProjections.date == target_date)
        .all()
    )
    actuals_by_pid = {
        r.pitcher_id: r
        for r in db.query(StrikeoutActuals)
        .filter(StrikeoutActuals.date == target_date)
        .all()
    }
    k_rows: list[dict[str, Any]] = []
    for p in proj_rows:
        a = actuals_by_pid.get(p.pitcher_id)
        k_rows.append(
            {
                "projected_strikeouts": p.projected_strikeouts,
                "fanduel_line": p.fanduel_line,
                "fanduel_over_under": p.fanduel_over_under,
                "actual_strikeouts": a.actual_strikeouts if a else None,
                "model_version": getattr(p, "model_version", None),
            }
        )

    hits_rows = _hits_rows(db, start=target_date, end=target_date)
    homer_rows = _homer_rows(db, start=target_date, end=target_date)

    game_rows = _merge_game_rows(db, target_date=target_date)

    buckets = [
        ou_call_bucket(
            k_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_strikeouts",
            projected_field="projected_strikeouts",
            label="Pitcher Ks O/U",
            key="pitcher_ks_ou",
        ),
        hit_rate_bucket(
            hits_rows,
            actual_field="actual_hits",
            projected_field="projected_hits",
            threshold=1,
            label="Projected Hits (board hit rate, no line)",
            key="projected_hits",
            secondary="Last-10 board: batters projected for ≥1 hit · no line, not in season model %",
        ),
        hit_rate_bucket(
            homer_rows,
            actual_field="actual_homers",
            projected_field="projected_homers",
            threshold=1,
            label="Projected Home Runs (board hit rate, no line)",
            key="projected_homers",
            secondary="Last-10 board: batters projected for ≥1 HR · no line, not in season model %",
        ),
        edge_play_bucket(
            game_rows,
            pick_field="ml_recommendation",
            correct_field="ml_correct",
            label="Game Moneyline",
            key="game_moneyline",
            secondary="ML edge plays (HOME/AWAY)",
        ),
        edge_play_bucket(
            game_rows,
            pick_field="spread_recommendation",
            correct_field="spread_correct",
            label="Game Spread",
            key="game_spread",
            secondary="Spread edge plays vs market line",
        ),
        ou_call_bucket(
            game_rows,
            line_field="market_total",
            pick_field="total_recommendation",
            actual_field="actual_total_runs",
            projected_field="projected_total",
            label="Game Total",
            key="game_total",
        ),
    ]

    out = assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=bool(k_rows or hits_rows or homer_rows or game_rows),
    )
    by_version = _strikeout_accuracy_by_model_version(k_rows)
    if by_version:
        out["strikeout_by_model_version"] = by_version
    return out


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Season (or arbitrary window) MLB accuracy — one combined hit rate."""
    proj_rows = (
        db.query(StrikeoutProjections)
        .filter(
            StrikeoutProjections.date >= start,
            StrikeoutProjections.date <= end,
        )
        .all()
    )
    actuals_by_pid = {
        (getattr(r, "date", None), r.pitcher_id): r
        for r in db.query(StrikeoutActuals)
        .filter(
            StrikeoutActuals.date >= start,
            StrikeoutActuals.date <= end,
        )
        .all()
    }
    k_rows: list[dict[str, Any]] = []
    for p in proj_rows:
        a = actuals_by_pid.get((getattr(p, "date", None), p.pitcher_id))
        k_rows.append(
            {
                "projected_strikeouts": p.projected_strikeouts,
                "fanduel_line": p.fanduel_line,
                "fanduel_over_under": p.fanduel_over_under,
                "actual_strikeouts": a.actual_strikeouts if a else None,
            }
        )

    hits_rows = _hits_rows(db, start=start, end=end)
    homer_rows = _homer_rows(db, start=start, end=end)

    game_rows = _merge_game_rows_range(db, start=start, end=end)

    # Headline = published calls with a line (Ks O/U, game ML/spread/total).
    # Batter boards (last-10-game counts, no line) are diagnostics only.
    return overview_item_from_markets(
        sport="mlb",
        label="MLB",
        markets=_headline_markets(k_rows, game_rows),
    )


def _headline_markets(
    k_rows: list[dict[str, Any]], game_rows: list[dict[str, Any]]
) -> dict[str, tuple[int, int]]:
    return {
        "Pitcher Ks O/U": ou_call_graded_counts(
            k_rows,
            line_field="fanduel_line",
            pick_field="fanduel_over_under",
            actual_field="actual_strikeouts",
        ),
        "Game moneyline": edge_play_graded_counts(
            game_rows, pick_field="ml_recommendation", correct_field="ml_correct"
        ),
        "Game spread": edge_play_graded_counts(
            game_rows,
            pick_field="spread_recommendation",
            correct_field="spread_correct",
        ),
        "Game total O/U": ou_call_graded_counts(
            game_rows,
            line_field="market_total",
            pick_field="total_recommendation",
            actual_field="actual_total_runs",
        ),
    }


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same row sets as ``season_overview``."""
    proj_rows = (
        db.query(StrikeoutProjections)
        .filter(
            StrikeoutProjections.date >= start,
            StrikeoutProjections.date <= end,
        )
        .all()
    )
    actuals_by_pid = {
        (getattr(r, "date", None), r.pitcher_id): r
        for r in db.query(StrikeoutActuals)
        .filter(
            StrikeoutActuals.date >= start,
            StrikeoutActuals.date <= end,
        )
        .all()
    }
    k_rows: list[dict[str, Any]] = []
    for p in proj_rows:
        a = actuals_by_pid.get((getattr(p, "date", None), p.pitcher_id))
        k_rows.append(
            {
                "projected_strikeouts": p.projected_strikeouts,
                "fanduel_line": p.fanduel_line,
                "fanduel_over_under": p.fanduel_over_under,
                "actual_strikeouts": a.actual_strikeouts if a else None,
            }
        )

    hits_rows = _hits_rows(db, start=start, end=end)
    homer_rows = _homer_rows(db, start=start, end=end)

    game_rows = _merge_game_rows_range(db, start=start, end=end)

    part_specs: list[tuple[str, str, dict[str, Any]]] = [
        (
            "pitcher_k_ou",
            "Pitcher Ks O/U",
            {
                "kind": "ou",
                "rows": k_rows,
                "line_field": "fanduel_line",
                "pick_field": "fanduel_over_under",
                "actual_field": "actual_strikeouts",
                "extra": {"strikeout_projection_rows": len(proj_rows)},
            },
        ),
        (
            "projected_hits",
            "Projected Hits (≥1)",
            {
                "kind": "hit_rate",
                "rows": hits_rows,
                "actual_field": "actual_hits",
                "projected_field": "projected_hits",
                "threshold": 1.0,
                "headline": False,
            },
        ),
        (
            "projected_homers",
            "Projected HR (≥1)",
            {
                "kind": "hit_rate",
                "rows": homer_rows,
                "actual_field": "actual_homers",
                "projected_field": "projected_homers",
                "threshold": 1.0,
                "headline": False,
            },
        ),
        (
            "game_ml_edge",
            "Game ML edge",
            {
                "kind": "edge",
                "rows": game_rows,
                "pick_field": "ml_recommendation",
                "correct_field": "ml_correct",
            },
        ),
        (
            "game_spread_edge",
            "Game spread edge",
            {
                "kind": "edge",
                "rows": game_rows,
                "pick_field": "spread_recommendation",
                "correct_field": "spread_correct",
            },
        ),
        (
            "game_total_ou",
            "Game total O/U",
            {
                "kind": "ou",
                "rows": game_rows,
                "line_field": "market_total",
                "pick_field": "total_recommendation",
                "actual_field": "actual_total_runs",
            },
        ),
    ]

    parts_out: list[dict[str, Any]] = []
    headline: dict[str, tuple[int, int]] = {}
    for key, label, spec in part_specs:
        rows = spec["rows"]
        if spec["kind"] == "ou":
            bd = ou_call_graded_breakdown(
                rows,
                line_field=spec["line_field"],
                pick_field=spec["pick_field"],
                actual_field=spec["actual_field"],
            )
            c, t = bd["graded_correct"], bd["graded_total"]
            extra = spec.get("extra") or {}
        elif spec["kind"] == "hit_rate":
            bd = hit_rate_graded_breakdown(
                rows,
                actual_field=spec["actual_field"],
                projected_field=spec["projected_field"],
                threshold=spec["threshold"],
            )
            c, t = bd["graded_hits"], bd["graded_total"]
            extra = {}
        else:
            bd = edge_play_graded_breakdown(
                rows,
                pick_field=spec["pick_field"],
                correct_field=spec["correct_field"],
            )
            c, t = bd["graded_correct"], bd["graded_total"]
            extra = {}
        in_headline = spec.get("headline", True)
        if in_headline:
            headline[label] = (c, t)
        entry: dict[str, Any] = {
            "key": key,
            "label": label,
            "kind": spec["kind"],
            "in_headline": in_headline,
            "breakdown": bd,
            "graded_correct": c,
            "graded_total": t,
        }
        if extra:
            entry["extra"] = extra
        parts_out.append(entry)

    return {
        "sport": "mlb",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview_item_from_markets(
            sport="mlb", label="MLB", markets=headline
        ),
        "parts": parts_out,
    }


def past_row_results(
    db: Session, *, target_date: date_type
) -> dict[str, dict[int, dict[str, Any]]]:
    """Per-row results for the past view, keyed by GET /predictions/mlb list key.

    Built from the same merged rows and shared row functions as
    ``daily_accuracy`` so a row and its tile cannot disagree. Game rows carry
    ``ml_result`` / ``spread_result`` / ``total_result`` (``result`` = the total
    O/U call) plus the actual_* score fields the frontend mapper reads.
    """
    k_proj = (
        db.query(StrikeoutProjections)
        .filter(StrikeoutProjections.date == target_date)
        .all()
    )
    k_actuals = {
        r.pitcher_id: r
        for r in db.query(StrikeoutActuals)
        .filter(StrikeoutActuals.date == target_date)
        .all()
    }
    strikeouts: dict[int, dict[str, Any]] = {}
    for p in k_proj:
        a = k_actuals.get(p.pitcher_id)
        actual = a.actual_strikeouts if a else None
        strikeouts[p.id] = {
            "actual": actual,
            "result": ou_row_result(
                line=p.fanduel_line,
                pick=p.fanduel_over_under,
                actual=actual,
                actual_expected=bool(k_actuals),
            ),
        }

    games: dict[int, dict[str, Any]] = {}
    for row in _merge_game_rows(db, target_date=target_date):
        scored = row.get("actual_home_score") is not None
        push = False
        if scored and row.get("market_spread") is not None:
            margin = row["actual_home_score"] - row["actual_away_score"]
            push = margin + float(row["market_spread"]) == 0
        total_result = ou_row_result(
            line=row.get("market_total"),
            pick=row.get("total_recommendation"),
            actual=row.get("actual_total_runs"),
        )
        games[row["id"]] = {
            "actual_home_score": row.get("actual_home_score"),
            "actual_away_score": row.get("actual_away_score"),
            "actual_total_runs": row.get("actual_total_runs"),
            "actual_winner": row.get("actual_winner"),
            "ml_result": edge_row_result(
                pick=row.get("ml_recommendation"), correct_flag=row.get("ml_correct")
            ),
            "spread_result": edge_row_result(
                pick=row.get("spread_recommendation"),
                correct_flag=row.get("spread_correct"),
                push=push,
            ),
            "total_result": total_result,
            "result": total_result,
        }

    def batter(rows: list[dict[str, Any]], proj_f: str, act_f: str):
        return {
            r["id"]: {
                "actual": r[act_f],
                "result": hit_rate_row_result(
                    projected=r[proj_f],
                    actual=r[act_f],
                    threshold=1,
                    actual_expected=r["actual_expected"],
                ),
            }
            for r in rows
        }

    return {
        "strikeout_projections": strikeouts,
        "game_projections": games,
        "projected_hits": batter(
            _hits_rows(db, start=target_date, end=target_date),
            "projected_hits",
            "actual_hits",
        ),
        "projected_homers": batter(
            _homer_rows(db, start=target_date, end=target_date),
            "projected_homers",
            "actual_homers",
        ),
    }
