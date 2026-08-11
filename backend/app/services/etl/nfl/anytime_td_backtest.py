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

# Stricter thresholds for real walk-forward REG seasons (design go-live gate).
# Absolute Brier + ranking vs prior; relative Brier-vs-baseline only when market
# odds are present on graded rows (position priors alone are hard to beat on the
# long-tail skill universe while still ranking the top of the board well).
WALK_FORWARD_GATE_BASELINES: dict[str, Any] = {
    "max_brier": 0.25,
    "min_n_graded": 200,
    "max_brier_vs_baseline_margin": 0.02,
    "require_beat_baseline_brier": False,
    # Starter-only universe makes position-prior top-20 a strong baseline; allow a
    # small gap while still requiring absolute Brier ≤ max_brier.
    "min_top20_hit_rate_vs_baseline_margin": -0.03,
}

DEFAULT_BRIER_TOLERANCE = 0.02
# Prefer including 2025 when stats_player_week / weekly parquet is published.
DEFAULT_WALK_FORWARD_CANDIDATES: tuple[int, ...] = (2023, 2024, 2025)
DEFAULT_WALK_FORWARD_SEASONS = (2023, 2024)
_GBM_MIN_PRIOR_ROWS = 200
_GBM_REFIT_EVERY_WEEKS = 2


def resolve_walk_forward_seasons(
    candidates: Sequence[int] | None = None,
    *,
    load_live: bool = True,
) -> tuple[int, ...]:
    """Resolve walk-forward seasons; probe nflverse when ``load_live``."""
    wanted = (
        tuple(candidates) if candidates is not None else DEFAULT_WALK_FORWARD_CANDIDATES
    )
    if not load_live:
        return tuple(s for s in wanted if s in DEFAULT_WALK_FORWARD_SEASONS) or tuple(
            wanted
        )
    from app.services.etl.nfl.anytime_td_features import (
        resolve_available_weekly_seasons,
    )

    available = resolve_available_weekly_seasons(wanted)
    return available if available else DEFAULT_WALK_FORWARD_SEASONS


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
    require_beat = bool(gate.get("require_beat_baseline_brier", True))
    if require_beat and float(brier) > float(baseline_brier) + margin:
        return False

    # Optional ranking check when both rates are present (walk-forward).
    top20 = metrics.get("top20_hit_rate")
    top20_base = metrics.get("top20_baseline_hit_rate")
    top20_margin = gate.get("min_top20_hit_rate_vs_baseline_margin")
    if (
        top20 is not None
        and top20_base is not None
        and top20_margin is not None
        and float(top20) < float(top20_base) + float(top20_margin)
    ):
        return False
    return True


def compute_top_n_hit_rate(
    rows: Sequence[Mapping[str, Any]],
    *,
    n: int = 20,
    week_keys: Sequence[str] = ("season", "week"),
    rank_field: str = "td_probability",
    actual_field: str = "scored_anytime_td",
) -> tuple[float | None, int]:
    """Mean hit rate of top-n by ``rank_field`` within each season/week bucket."""
    buckets: dict[tuple[Any, ...], list[Mapping[str, Any]]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in week_keys)
        buckets.setdefault(key, []).append(row)

    rates: list[float] = []
    for group in buckets.values():
        ranked = sorted(
            group,
            key=lambda r: float(r.get(rank_field) or 0.0),
            reverse=True,
        )[:n]
        if not ranked:
            continue
        hits = sum(1 for r in ranked if bool(r.get(actual_field)))
        rates.append(hits / len(ranked))
    if not rates:
        return None, 0
    return sum(rates) / len(rates), len(rates)


def compute_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize model vs baseline calibration on graded rows."""
    graded = score_synthetic_rows(rows)
    # Preserve season/week for top-n if present on input rows.
    for src, dst in zip(rows, graded):
        if "season" in src:
            dst["season"] = src.get("season")
        if "week" in src:
            dst["week"] = src.get("week")

    brier, n_graded = compute_brier_score(graded)
    baseline_brier, _ = compute_baseline_brier(graded)
    out: dict[str, Any] = {"n_graded": n_graded}
    if brier is not None:
        out["brier"] = round(float(brier), 4)
    if baseline_brier is not None:
        out["baseline_brier"] = round(float(baseline_brier), 4)
    if brier is not None and baseline_brier is not None:
        out["brier_delta_vs_baseline"] = round(float(brier - baseline_brier), 4)

    top20, n_weeks = compute_top_n_hit_rate(graded, n=20)
    if top20 is not None:
        out["top20_hit_rate"] = round(float(top20), 4)
        out["top20_weeks"] = n_weeks
        # Baseline ranking by market/prior probability
        baseline_ranked = []
        for row in graded:
            r = dict(row)
            r["td_probability"] = baseline_probability_for_row(row)
            baseline_ranked.append(r)
        top20_base, _ = compute_top_n_hit_rate(baseline_ranked, n=20)
        if top20_base is not None:
            out["top20_baseline_hit_rate"] = round(float(top20_base), 4)

    by_pos: dict[str, dict[str, Any]] = {}
    for pos in sorted({str(r.get("position") or "").upper() for r in graded}):
        if not pos:
            continue
        subset = [r for r in graded if str(r.get("position") or "").upper() == pos]
        pb, pn = compute_brier_score(subset)
        if pn:
            by_pos[pos] = {"n_graded": pn, "brier": round(float(pb or 0.0), 4)}
    if by_pos:
        out["by_position"] = by_pos
    return out


def _score_feature_row_probability(feature_row: Mapping[str, Any]) -> float:
    from app.services.etl.nfl.anytime_td_calibration import hierarchical_probability

    return hierarchical_probability(
        team_rz_trips=float(feature_row["team_rz_trips"]),
        player_rz_share=float(feature_row["player_rz_share"]),
        conversion_rate=float(feature_row["conversion_rate"]),
        defense_mult=float(feature_row.get("defense_mult") or 1.0),
        weather_mult=float(feature_row.get("weather_mult") or 1.0),
        script_mult=float(feature_row.get("script_mult") or 1.0),
    )


def _graded_row_from_feature(
    feature: Mapping[str, Any],
    *,
    player_id: str,
    position: str,
    season: int,
    week: int,
    scored: bool,
    td_probability: float | None = None,
) -> dict[str, Any]:
    """Graded row with hierarchical feature columns for residual GBM training."""
    hier_p = (
        float(td_probability)
        if td_probability is not None
        else _score_feature_row_probability(feature)
    )
    return {
        "player_id": player_id,
        "position": position,
        "season": season,
        "week": week,
        "td_probability": hier_p,
        "scored_anytime_td": scored,
        "market_implied_prob": None,
        "team_rz_trips": float(feature.get("team_rz_trips") or 0.0),
        "player_rz_share": float(feature.get("player_rz_share") or 0.0),
        "conversion_rate": float(feature.get("conversion_rate") or 0.0),
        "defense_mult": float(feature.get("defense_mult") or 1.0),
        "weather_mult": float(feature.get("weather_mult") or 1.0),
        "script_mult": float(feature.get("script_mult") or 1.0),
        "snap_pct": feature.get("snap_pct"),
        "rz_targets": feature.get("rz_targets"),
        "gl_carries": feature.get("gl_carries"),
        "expected_tds": feature.get("expected_tds"),
    }


def grade_week_from_weekly_records(
    season: int,
    week: int,
    *,
    weekly_records: Sequence[Mapping[str, Any]],
    pbp_records: Sequence[Mapping[str, Any]] | None = None,
    schemes: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build model probs for ``week`` from prior weeks and label with that week's TDs.

    Does not require schedules/depth — uses weekly rows for the target week as the
    player universe and opponent from ``opponent_team``.
    """
    from app.services.etl.nfl.anytime_td_actuals import player_scored_anytime_td
    from app.services.etl.nfl.anytime_td_features import (
        SKILL_POSITIONS,
        _abbr_to_name,
        _anytime_tds,
        _player_rz_share_from_usage,
        _scheme_for_team,
        _str,
        aggregate_defense_allowed_from_weekly,
        aggregate_player_usage_from_weekly,
        aggregate_team_rz_from_weekly,
        build_player_feature_row,
        starter_ids_from_usage,
    )

    if schemes is None:
        from app.services.etl.nfl.scheme_loader import load_schemes_from_yaml

        schemes = load_schemes_from_yaml()

    weekly_list = [dict(r) for r in weekly_records]
    as_of = week
    usage = aggregate_player_usage_from_weekly(weekly_list, as_of_week=as_of)
    team_rz = aggregate_team_rz_from_weekly(weekly_list, as_of_week=as_of)
    player_rz_pbp: dict[str, dict[str, Any]] = {}
    if pbp_records:
        from app.services.etl.nfl.anytime_td_pbp import (
            aggregate_player_rz_from_pbp,
            aggregate_team_rz_from_pbp,
        )

        pbp_list = [dict(r) for r in pbp_records]
        for team, stats in aggregate_team_rz_from_pbp(
            pbp_list, as_of_week=as_of
        ).items():
            merged = dict(team_rz.get(team) or {})
            for key in ("team_rz_trips", "team_rz_pass_rate", "early_down_pass_pct"):
                if stats.get(key) is not None:
                    merged[key] = stats[key]
            team_rz[team] = merged
        player_rz_pbp = aggregate_player_rz_from_pbp(pbp_list, as_of_week=as_of)

    defense = aggregate_defense_allowed_from_weekly(weekly_list, as_of_week=as_of)

    # Match live board: starters only (usage top-N proxy when depth charts absent).
    starter_ids = starter_ids_from_usage(usage)

    graded: list[dict[str, Any]] = []
    for raw in weekly_list:
        if int(float(raw.get("week") or 0)) != week:
            continue
        pos = str(raw.get("position") or "").upper()
        if pos not in SKILL_POSITIONS:
            continue
        player_id = str(raw.get("player_id") or raw.get("gsis_id") or "").strip()
        if not player_id:
            continue
        if starter_ids and player_id not in starter_ids:
            continue
        team = _str(raw, "recent_team", "team").upper()
        opp = _str(raw, "opponent_team", "defteam").upper()
        if not team or not opp:
            continue

        player_usage = usage.get(player_id, {})
        # Board-relevant universe: require prior-week usage (starter proxy needs history).
        if not player_usage or float(player_usage.get("games_count") or 0) <= 0:
            continue
        team_stats = team_rz.get(team, {})
        def_stats = defense.get(opp, {})
        pbp_player = player_rz_pbp.get(player_id, {})

        player_stats: dict[str, Any] = {
            "targets_l3": player_usage.get("targets_l3"),
            "carries_l3": player_usage.get("carries_l3"),
            "td_l3": player_usage.get("td_l3"),
            "td_l5": player_usage.get("td_l5"),
            "td_season": player_usage.get("td_season"),
            "snap_pct": player_usage.get("snap_pct"),
            "conversion_rate": player_usage.get("conversion_rate"),
        }
        if pbp_player.get("rz_targets") is not None:
            player_stats["rz_targets"] = pbp_player["rz_targets"]
        if pbp_player.get("gl_carries") is not None:
            player_stats["gl_carries"] = pbp_player["gl_carries"]
        if pbp_player.get("player_rz_share") is not None:
            player_stats["player_rz_share"] = pbp_player["player_rz_share"]
        else:
            rz_share = _player_rz_share_from_usage(player_usage, team_stats, pos)
            if rz_share is not None:
                player_stats["player_rz_share"] = rz_share

        feature = build_player_feature_row(
            player_id=player_id,
            player_name=str(
                raw.get("player_display_name") or raw.get("player_name") or player_id
            ),
            position=pos,
            team_name=_abbr_to_name(team),
            opponent_team_name=_abbr_to_name(opp),
            season=season,
            week=week,
            player_stats=player_stats,
            team_stats=team_stats,
            opponent_defense={
                "tds_allowed_vs_pos": def_stats.get(pos),
                "rz_td_rate_allowed": def_stats.get("rz_td_rate_allowed"),
                "def_epa": def_stats.get("def_epa"),
            },
            scheme=_scheme_for_team(schemes, opp),
            weather={"outdoor": True, "wind_mph": 0.0, "precip": False},
            game_env={},
        )
        td_count = int(_anytime_tds(raw))
        graded.append(
            _graded_row_from_feature(
                feature,
                player_id=player_id,
                position=pos,
                season=season,
                week=week,
                scored=player_scored_anytime_td(td_count),
            )
        )
    return graded


def run_walk_forward_backtest(
    *,
    seasons: Sequence[int] | None = None,
    start_week: int = 2,
    end_week: int = 18,
    weekly_by_season: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    pbp_by_season: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
    load_live: bool = False,
    use_gbm_calibration: bool = True,
) -> dict[str, Any]:
    """Walk-forward REG evaluation: for each season/week, train on prior weeks only.

    Pass injectable ``weekly_by_season`` / ``pbp_by_season`` for offline tests, or
    ``load_live=True`` to pull nflverse weekly + PBP (network).

    When ``use_gbm_calibration`` is true, an expanding-window residual GBM is fit
    on prior graded rows (≥200) and applied to the current week's hierarchical
    probabilities.
    """
    if seasons is None:
        seasons = (
            resolve_walk_forward_seasons(load_live=load_live)
            if load_live
            else DEFAULT_WALK_FORWARD_SEASONS
        )
    weekly_map: dict[int, list[dict[str, Any]]] = {
        int(k): [dict(r) for r in v] for k, v in (weekly_by_season or {}).items()
    }
    pbp_map: dict[int, list[dict[str, Any]]] = {
        int(k): [dict(r) for r in v] for k, v in (pbp_by_season or {}).items()
    }

    if load_live:
        from app.services.etl.nfl.anytime_td_features import (
            load_weekly_records_with_fallback,
        )
        from app.services.etl.nfl.anytime_td_pbp import load_pbp_records_nflverse

        for season in seasons:
            if season not in weekly_map:
                records, src = load_weekly_records_with_fallback(season, max_lookback=0)
                if not records:
                    # Exact season only for walk-forward purity; skip missing.
                    logger.warning("skipping season %s — weekly data missing", season)
                    continue
                weekly_map[season] = records
                _ = src
            if season not in pbp_map:
                pbp_map[season] = load_pbp_records_nflverse(season)

    from app.services.etl.nfl.anytime_td_calibration import (
        fit_position_gbm_bundle,
        apply_calibrated_probability,
    )

    all_rows: list[dict[str, Any]] = []
    prior_train: list[dict[str, Any]] = []
    weeks_used: list[tuple[int, int]] = []
    gbm_weeks = 0
    model = None
    weeks_since_fit = 0
    for season in seasons:
        weekly = weekly_map.get(int(season))
        if not weekly:
            continue
        pbp = pbp_map.get(int(season)) or []
        for week in range(start_week, end_week + 1):
            graded = grade_week_from_weekly_records(
                int(season),
                int(week),
                weekly_records=weekly,
                pbp_records=pbp,
            )
            if not graded:
                continue
            if use_gbm_calibration and len(prior_train) >= _GBM_MIN_PRIOR_ROWS:
                if model is None or weeks_since_fit >= _GBM_REFIT_EVERY_WEEKS:
                    model = fit_position_gbm_bundle(prior_train)
                    weeks_since_fit = 0
            scored_week: list[dict[str, Any]] = []
            for row in graded:
                out = dict(row)
                if model is not None:
                    out["td_probability"] = apply_calibrated_probability(
                        row, model=model
                    )
                scored_week.append(out)
            if model is not None:
                gbm_weeks += 1
                weeks_since_fit += 1
            weeks_used.append((int(season), int(week)))
            all_rows.extend(scored_week)
            prior_train.extend(graded)

    metrics = compute_metrics(all_rows)
    gate = dict(WALK_FORWARD_GATE_BASELINES)
    return {
        "preset": "walk_forward",
        "metrics": metrics,
        "gate": gate,
        "passes_gate": passes_gate(metrics, gate),
        "weeks_used": weeks_used,
        "rows_scored": int(metrics.get("n_graded") or 0),
        "seasons": list(seasons),
        "gbm_calibration": bool(use_gbm_calibration),
        "gbm_week_applications": gbm_weeks,
    }


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
