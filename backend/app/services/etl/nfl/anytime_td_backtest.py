"""Offline/quick backtest for NFL anytime-TD predictions.

Quick mode uses a fixed synthetic sample (no DATABASE_URL or Odds credits).
Full replay joins ``pred_nfl_anytime_td_predictions`` to actuals when a DB
session is available.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_METRICS_PATH = BACKEND_ROOT / "models" / "nfl" / "anytime_td_metrics.json"

# Position priors when market implied prob is unavailable (design-spec fallback).
POSITION_ANYTIME_PRIOR: dict[str, float] = {
    "QB": 0.12,
    "RB": 0.35,
    "WR": 0.22,
    "TE": 0.25,
}

DEFAULT_GATE_BASELINES: dict[str, Any] = {
    "max_brier": 0.25,
    "min_n_graded": 4,
    "max_brier_vs_baseline_margin": 0.02,
}

DEFAULT_BRIER_TOLERANCE = 0.02

# Tiny fixed sample for CI / ``--quick`` smoke (model beats market/prior baseline).
QUICK_SYNTHETIC_ROWS: list[dict[str, Any]] = [
    {
        "player_id": "rb1",
        "position": "RB",
        "td_probability": 0.55,
        "scored_anytime_td": True,
        "market_implied_prob": 0.50,
    },
    {
        "player_id": "wr1",
        "position": "WR",
        "td_probability": 0.25,
        "scored_anytime_td": False,
        "market_implied_prob": 0.28,
    },
    {
        "player_id": "te1",
        "position": "TE",
        "td_probability": 0.40,
        "scored_anytime_td": True,
        "market_implied_prob": 0.38,
    },
    {
        "player_id": "wr2",
        "position": "WR",
        "td_probability": 0.18,
        "scored_anytime_td": False,
        "market_implied_prob": 0.20,
    },
    {
        "player_id": "rb2",
        "position": "RB",
        "td_probability": 0.30,
        "scored_anytime_td": False,
    },
    {
        "player_id": "wr3",
        "position": "WR",
        "td_probability": 0.45,
        "scored_anytime_td": True,
    },
    {
        "player_id": "qb1",
        "position": "QB",
        "td_probability": 0.12,
        "scored_anytime_td": False,
    },
    {
        "player_id": "te2",
        "position": "TE",
        "td_probability": 0.28,
        "scored_anytime_td": True,
    },
]


@dataclass(frozen=True)
class AnytimeTDBacktestResult:
    metrics: dict[str, Any]
    rows_scored: int
    weeks_used: list[tuple[int, int]] = field(default_factory=list)


def _binary_outcome(actual: Any) -> float | None:
    if actual is None:
        return None
    return 1.0 if bool(actual) else 0.0


def row_brier(probability: float, actual: bool) -> float:
    y = 1.0 if actual else 0.0
    return (float(probability) - y) ** 2


def baseline_probability_for_row(row: Mapping[str, Any]) -> float:
    market = row.get("market_implied_prob")
    if market is not None:
        return float(market)
    position = str(row.get("position") or "WR").upper()
    return float(POSITION_ANYTIME_PRIOR.get(position, POSITION_ANYTIME_PRIOR["WR"]))


def score_synthetic_rows(
    rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize synthetic/graded rows for metric computation."""
    out: list[dict[str, Any]] = []
    for row in rows:
        prob = row.get("td_probability")
        actual = row.get("scored_anytime_td")
        if prob is None or actual is None:
            continue
        out.append(
            {
                "player_id": row.get("player_id"),
                "position": row.get("position"),
                "td_probability": float(prob),
                "scored_anytime_td": bool(actual),
                "market_implied_prob": row.get("market_implied_prob"),
            }
        )
    return out


def compute_brier_score(
    rows: Sequence[Mapping[str, Any]],
    *,
    prob_field: str = "td_probability",
    actual_field: str = "scored_anytime_td",
) -> tuple[float | None, int]:
    scores: list[float] = []
    for row in rows:
        prob = row.get(prob_field)
        y = _binary_outcome(row.get(actual_field))
        if prob is None or y is None:
            continue
        scores.append((float(prob) - y) ** 2)
    if not scores:
        return None, 0
    return sum(scores) / len(scores), len(scores)


def compute_baseline_brier(
    rows: Sequence[Mapping[str, Any]]
) -> tuple[float | None, int]:
    scores: list[float] = []
    for row in rows:
        y = _binary_outcome(row.get("scored_anytime_td"))
        if y is None:
            continue
        base_p = baseline_probability_for_row(row)
        scores.append((base_p - y) ** 2)
    if not scores:
        return None, 0
    return sum(scores) / len(scores), len(scores)


def compute_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize model vs baseline calibration on graded rows."""
    graded = score_synthetic_rows(rows)
    brier, n_graded = compute_brier_score(graded)
    baseline_brier, _ = compute_baseline_brier(graded)
    out: dict[str, Any] = {"n_graded": n_graded}
    if brier is not None:
        out["brier"] = round(float(brier), 4)
    if baseline_brier is not None:
        out["baseline_brier"] = round(float(baseline_brier), 4)
    if brier is not None and baseline_brier is not None:
        out["brier_delta_vs_baseline"] = round(float(brier - baseline_brier), 4)
    return out


def passes_gate(metrics: Mapping[str, Any], baselines: Mapping[str, Any]) -> bool:
    """Return True when offline metrics meet the go-live calibration gate."""
    gate = (
        baselines.get("gate") if isinstance(baselines.get("gate"), dict) else baselines
    )

    max_brier = float(gate.get("max_brier", DEFAULT_GATE_BASELINES["max_brier"]))
    min_n = int(gate.get("min_n_graded", DEFAULT_GATE_BASELINES["min_n_graded"]))
    margin = float(
        gate.get(
            "max_brier_vs_baseline_margin",
            DEFAULT_GATE_BASELINES["max_brier_vs_baseline_margin"],
        )
    )

    brier = metrics.get("brier")
    n_graded = int(metrics.get("n_graded") or 0)
    if brier is None or n_graded < min_n:
        return False
    if float(brier) > max_brier:
        return False

    baseline_brier = metrics.get("baseline_brier")
    if baseline_brier is None:
        return False
    if float(brier) > float(baseline_brier) + margin:
        return False
    return True


def run_quick_backtest() -> dict[str, Any]:
    """Run the fixed synthetic sample used by CI and ``--quick`` CLI."""
    metrics = compute_metrics(QUICK_SYNTHETIC_ROWS)
    return {
        "preset": "quick",
        "metrics": metrics,
        "gate": dict(DEFAULT_GATE_BASELINES),
        "passes_gate": passes_gate(metrics, DEFAULT_GATE_BASELINES),
    }


def _load_metrics_payload(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def load_metrics_artifact(path: str | Path | None = None) -> dict[str, Any]:
    return _load_metrics_payload(path or DEFAULT_METRICS_PATH)


def write_metrics_artifact(
    metrics: Mapping[str, Any],
    *,
    path: str | Path | None = None,
    preset: str = "quick",
    gate: Mapping[str, Any] | None = None,
    description: str | None = None,
) -> Path:
    target = Path(path or DEFAULT_METRICS_PATH)
    gate_payload = dict(gate or DEFAULT_GATE_BASELINES)
    payload = {
        "description": description
        or (
            "NFL anytime-TD quick backtest (--quick). Synthetic offline sample; "
            "refresh after intentional model changes."
        ),
        "updated_at": date.today().isoformat(),
        "preset": preset,
        "gate": gate_payload,
        "metrics": dict(metrics),
        "passes_gate": passes_gate(metrics, gate_payload),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _merge_prediction_actual_rows(
    predictions: Sequence[Any],
    actuals: Sequence[Any],
) -> list[dict[str, Any]]:
    by_key = {(a.season, a.week, a.player_id): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for pred in predictions:
        key = (pred.season, pred.week, pred.player_id)
        actual = by_key.get(key)
        if actual is None:
            continue
        rows.append(
            {
                "player_id": pred.player_id,
                "position": pred.position,
                "td_probability": pred.td_probability,
                "scored_anytime_td": actual.scored_anytime_td,
                "market_implied_prob": pred.market_implied_prob,
                "season": pred.season,
                "week": pred.week,
            }
        )
    return rows


def run_backtest_replay(
    *,
    session: Any | None = None,
    season: int | None = None,
    start_week: int = 1,
    end_week: int = 18,
    quick: bool = False,
    max_weeks: int | None = None,
    synthetic_rows: Sequence[Mapping[str, Any]] | None = None,
) -> AnytimeTDBacktestResult:
    """Replay predictions vs actuals from DB and/or synthetic rows."""
    from app.services.etl.nfl.nfl_common import get_nfl_season

    rows: list[dict[str, Any]] = []
    weeks_used: list[tuple[int, int]] = []

    if synthetic_rows:
        rows.extend(score_synthetic_rows(synthetic_rows))

    if session is not None:
        from app.models.predictions_models import (
            NFLAnytimeTDActuals,
            NFLAnytimeTDPredictions,
        )

        resolved_season = season if season is not None else get_nfl_season()
        week_rows = (
            session.query(NFLAnytimeTDPredictions.season, NFLAnytimeTDPredictions.week)
            .filter(
                NFLAnytimeTDPredictions.season == resolved_season,
                NFLAnytimeTDPredictions.week >= start_week,
                NFLAnytimeTDPredictions.week <= end_week,
            )
            .distinct()
            .all()
        )
        weeks = sorted({(int(s), int(w)) for s, w in week_rows}, reverse=True)
        if quick:
            limit = max_weeks if max_weeks is not None else 4
            weeks_used = weeks[:limit]
        else:
            weeks_used = weeks

        if weeks_used:
            week_nums = {w for _, w in weeks_used}
            preds = (
                session.query(NFLAnytimeTDPredictions)
                .filter(
                    NFLAnytimeTDPredictions.season == resolved_season,
                    NFLAnytimeTDPredictions.week.in_(week_nums),
                )
                .all()
            )
            actuals = (
                session.query(NFLAnytimeTDActuals)
                .filter(
                    NFLAnytimeTDActuals.season == resolved_season,
                    NFLAnytimeTDActuals.week.in_(week_nums),
                )
                .all()
            )
            rows.extend(_merge_prediction_actual_rows(preds, actuals))

    metrics = compute_metrics(rows)
    return AnytimeTDBacktestResult(
        metrics=metrics,
        rows_scored=int(metrics.get("n_graded") or 0),
        weeks_used=weeks_used,
    )
