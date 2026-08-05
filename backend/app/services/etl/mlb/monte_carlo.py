"""MLB game-level Monte Carlo simulation (MVP).

Simulates team run totals from expected rates (Negative Binomial / Poisson),
producing win probability, total-run distribution, and margin percentiles.

Aligned with sportsbook PRD Module 6 (game-level MVP; not plate-appearance yet).
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

DEFAULT_N_SIMS = int(os.getenv("MLB_MC_N_SIMS", "10000"))
DEFAULT_DISPERSION = float(os.getenv("MLB_MC_DISPERSION", "1.35"))
DEFAULT_SEED = int(os.getenv("MLB_MC_SEED", "42"))


@dataclass(frozen=True)
class TeamRunRates:
    """Expected runs for each team (9-inning baseline)."""

    home_mu: float
    away_mu: float


@dataclass
class GameSimResult:
    """Aggregated Monte Carlo outputs for one game."""

    n_sims: int
    home_win_prob: float
    away_win_prob: float
    projected_total_mean: float
    projected_total_std: float
    home_runs_mean: float
    away_runs_mean: float
    run_line_mean: float
    percentiles_total: dict[str, float] = field(default_factory=dict)
    percentiles_margin: dict[str, float] = field(default_factory=dict)
    home_lambda: float = 0.0
    away_lambda: float = 0.0
    dispersion: float = DEFAULT_DISPERSION
    tie_rate: float = 0.0
    ml_baseline: dict[str, float] | None = None
    matchup_meta: dict[str, Any] | None = None

    def to_storage_dict(self) -> dict[str, Any]:
        """JSON-serializable summary for ``pred_game_projections.sim_distribution``."""
        d = asdict(self)
        if d.get("matchup_meta") is None:
            d.pop("matchup_meta", None)
        return d


def expected_runs_from_features(features: dict[str, Any]) -> TeamRunRates:
    """Derive per-team expected runs from the same inputs as game heuristics."""
    home_runs = float(features.get("home_recent_runs_avg", 4.5))
    away_runs = float(features.get("away_recent_runs_avg", 4.5))

    home_pitcher_adj = (4.50 - float(features.get("away_starter_era", 4.5))) * 0.3
    away_pitcher_adj = (4.50 - float(features.get("home_starter_era", 4.5))) * 0.3

    home_mu = max(0.5, home_runs - home_pitcher_adj)
    away_mu = max(0.5, away_runs - away_pitcher_adj)

    pf = float(features.get("park_factor", 1.0))
    scale = pf if pf > 0 else 1.0
    home_mu *= scale
    away_mu *= scale

    home_mu += (float(features.get("home_bullpen_fatigue", 0.5)) - 0.5) * 0.25
    away_mu += (float(features.get("away_bullpen_fatigue", 0.5)) - 0.5) * 0.25

    weather_adj = float(features.get("weather_run_adj", 0.0)) / 2.0
    home_mu += weather_adj
    away_mu += weather_adj

    ump = float(features.get("umpire_run_adj", 0.0)) / 2.0
    home_mu += ump
    away_mu += ump

    home_mu += float(features.get("away_ttop_adj", 0.0)) * 0.15
    away_mu += float(features.get("home_ttop_adj", 0.0)) * 0.15

    home_mu -= float(features.get("injury_impact_home", 0.0)) * 0.2
    away_mu -= float(features.get("injury_impact_away", 0.0)) * 0.2

    home_mu += float(features.get("home_travel_adj", 0.0)) * 0.08
    away_mu += float(features.get("away_travel_adj", 0.0)) * 0.08

    return TeamRunRates(home_mu=round(home_mu, 3), away_mu=round(away_mu, 3))


def expected_runs_from_projection(
    projected_total: float,
    home_win_prob: float,
) -> TeamRunRates:
    """Split a total + win probability into per-team run expectations."""
    total = max(float(projected_total), 1.0)
    wp = min(max(float(home_win_prob), 0.05), 0.95)
    # Win prob maps to run share (not 1:1 — stronger teams score more when favored).
    home_share = 0.5 + 0.32 * (wp - 0.5)
    home_share = min(max(home_share, 0.35), 0.65)
    home_mu = total * home_share
    away_mu = total - home_mu
    return TeamRunRates(home_mu=round(home_mu, 3), away_mu=round(away_mu, 3))


def resolve_team_rates(
    features: dict[str, Any],
    *,
    projected_total: float | None = None,
    home_win_prob: float | None = None,
    blend_ml: float = 0.65,
) -> TeamRunRates:
    """Blend feature-based rates with ML point projections when available."""
    feat_rates = expected_runs_from_features(features)
    if projected_total is None or home_win_prob is None:
        return feat_rates
    ml_rates = expected_runs_from_projection(projected_total, home_win_prob)
    w = min(max(blend_ml, 0.0), 1.0)
    return TeamRunRates(
        home_mu=round((1 - w) * feat_rates.home_mu + w * ml_rates.home_mu, 3),
        away_mu=round((1 - w) * feat_rates.away_mu + w * ml_rates.away_mu, 3),
    )


def _sample_runs(
    mu: float,
    n: int,
    rng: np.random.Generator,
    dispersion: float,
) -> np.ndarray:
    mu = max(float(mu), 0.01)
    var = mu * max(float(dispersion), 1.0)
    if var <= mu + 1e-6:
        return rng.poisson(mu, size=n).astype(np.int32)
    # NegBin parameterization: mean=mu, var=mu*k  => r = mu^2/(var-mu), p=r/(r+mu)
    r = (mu * mu) / max(var - mu, 0.01)
    p = r / (r + mu)
    p = min(max(p, 1e-6), 1.0 - 1e-6)
    return rng.negative_binomial(r, p, size=n).astype(np.int32)


def _resolve_extra_inning_runs(
    home: np.ndarray,
    away: np.ndarray,
    rates: TeamRunRates,
    rng: np.random.Generator,
    dispersion: float,
    max_extra: int = 3,
) -> tuple[np.ndarray, np.ndarray]:
    """Break ties with extra-inning Poisson slices (rare; keeps win prob well-defined)."""
    tied = home == away
    if not np.any(tied):
        return home, away
    inning_mu_home = rates.home_mu / 9.0
    inning_mu_away = rates.away_mu / 9.0
    h = home.copy()
    a = away.copy()
    for _ in range(max_extra):
        still = h == a
        if not np.any(still):
            break
        n = int(np.sum(still))
        h[still] += _sample_runs(inning_mu_home, n, rng, 1.0)
        a[still] += _sample_runs(inning_mu_away, n, rng, 1.0)
    return h, a


def simulate_game(
    rates: TeamRunRates,
    *,
    n_sims: int = DEFAULT_N_SIMS,
    dispersion: float = DEFAULT_DISPERSION,
    seed: int | None = None,
    ml_baseline: dict[str, float] | None = None,
    matchup_meta: dict[str, Any] | None = None,
) -> GameSimResult:
    """Run Monte Carlo for one game; return distribution summaries."""
    n_sims = max(int(n_sims), 100)
    rng = np.random.default_rng(seed)

    home_runs = _sample_runs(rates.home_mu, n_sims, rng, dispersion)
    away_runs = _sample_runs(rates.away_mu, n_sims, rng, dispersion)
    home_runs, away_runs = _resolve_extra_inning_runs(
        home_runs, away_runs, rates, rng, dispersion
    )

    totals = home_runs.astype(np.float64) + away_runs.astype(np.float64)
    margins = home_runs.astype(np.float64) - away_runs.astype(np.float64)

    home_wins = home_runs > away_runs
    tie_rate = float(np.mean(home_runs == away_runs))

    pct_keys = (10, 25, 50, 75, 90)
    pct_total = {f"p{k}": float(np.percentile(totals, k)) for k in pct_keys}
    pct_margin = {f"p{k}": float(np.percentile(margins, k)) for k in pct_keys}

    home_wp = float(np.mean(home_wins))

    return GameSimResult(
        n_sims=n_sims,
        home_win_prob=round(home_wp, 4),
        away_win_prob=round(1.0 - home_wp, 4),
        projected_total_mean=round(float(np.mean(totals)), 2),
        projected_total_std=round(float(np.std(totals)), 2),
        home_runs_mean=round(float(np.mean(home_runs)), 2),
        away_runs_mean=round(float(np.mean(away_runs)), 2),
        run_line_mean=round(float(np.mean(margins)), 2),
        percentiles_total=pct_total,
        percentiles_margin=pct_margin,
        home_lambda=rates.home_mu,
        away_lambda=rates.away_mu,
        dispersion=dispersion,
        tie_rate=round(tie_rate, 5),
        ml_baseline=ml_baseline,
        matchup_meta=matchup_meta,
    )


def probability_over_total_at_line(
    line: float,
    *,
    rates: TeamRunRates | None = None,
    sim: GameSimResult | None = None,
    n_sims: int | None = None,
    seed: int | None = None,
    dispersion: float | None = None,
) -> float:
    """Empirical P(total runs > line) from Monte Carlo samples."""
    line_f = float(line)
    n = int(n_sims or int(os.getenv("MLB_MC_P_OVER_N_SIMS", "8000")))
    disp = float(dispersion if dispersion is not None else DEFAULT_DISPERSION)

    if rates is None and sim is not None:
        rates = TeamRunRates(home_mu=sim.home_lambda, away_mu=sim.away_lambda)
        disp = sim.dispersion

    if rates is None:
        return 0.5

    rng = np.random.default_rng(seed)
    home_runs = _sample_runs(rates.home_mu, n, rng, disp)
    away_runs = _sample_runs(rates.away_mu, n, rng, disp)
    home_runs, away_runs = _resolve_extra_inning_runs(
        home_runs, away_runs, rates, rng, disp
    )
    totals = home_runs.astype(np.float64) + away_runs.astype(np.float64)
    return round(float(np.mean(totals > line_f)), 4)


def probability_over_total(sim: GameSimResult, line: float) -> float:
    """P(total runs > line) using stored sim lambdas (empirical re-sim)."""
    return probability_over_total_at_line(
        line,
        sim=sim,
        dispersion=sim.dispersion,
    )


def rates_from_game_row(row: dict[str, Any]) -> TeamRunRates:
    """Rebuild team rates from persisted projection / sim_distribution."""
    sim = row.get("sim_distribution") or {}
    if sim.get("home_lambda") is not None and sim.get("away_lambda") is not None:
        return TeamRunRates(
            home_mu=float(sim["home_lambda"]),
            away_mu=float(sim["away_lambda"]),
        )
    return expected_runs_from_projection(
        float(row.get("projected_total") or 9.0),
        float(row.get("home_win_prob") or 0.5),
    )


def p_over_total_for_game_row(
    row: dict[str, Any],
    line: float,
    *,
    n_sims: int | None = None,
    seed: int | None = None,
) -> float:
    """API/backtest helper: P(over) at ``line`` for a game projection row."""
    sim = row.get("sim_distribution") or {}
    dispersion = sim.get("dispersion")
    game_id = row.get("game_id")
    resolved_seed = seed
    if resolved_seed is None and game_id is not None:
        resolved_seed = DEFAULT_SEED + int(game_id)
    rates = rates_from_game_row(row)
    return probability_over_total_at_line(
        line,
        rates=rates,
        n_sims=n_sims,
        seed=resolved_seed,
        dispersion=dispersion,
    )


def run_monte_carlo_backtest(
    features: dict[str, Any],
    predicted_home_wp: float,
    predicted_total: float,
    *,
    game_id: int | None = None,
    n_sims: int | None = None,
) -> dict[str, Any]:
    """Run MC for backtest without replacing ensemble/heuristic point estimates."""
    n = int(n_sims or int(os.getenv("MLB_MC_BACKTEST_N_SIMS", "5000")))
    seed = DEFAULT_SEED + int(game_id or 0)
    rates = resolve_team_rates(
        features,
        projected_total=predicted_total,
        home_win_prob=predicted_home_wp,
    )
    matchup_meta = None
    as_of = features.get("as_of_date") or features.get("game_date")
    if as_of is not None:
        from datetime import date as date_type

        if isinstance(as_of, str):
            as_of = date_type.fromisoformat(str(as_of)[:10])
        from app.services.etl.mlb.profiles.lineup_runs import (
            attach_lineup_features_for_mc,
            maybe_adjust_rates_from_lineups,
        )

        attach_lineup_features_for_mc(features, features)
        if features.get("game_id") is None and game_id is not None:
            features["game_id"] = game_id
        rates, matchup_meta = maybe_adjust_rates_from_lineups(features, rates, as_of)
    sim = simulate_game(
        rates,
        n_sims=n,
        seed=seed,
        ml_baseline={
            "home_win_prob": float(predicted_home_wp),
            "projected_total": float(predicted_total),
        },
        matchup_meta=matchup_meta,
    )
    out = {
        "mc_home_wp": sim.home_win_prob,
        "mc_total": sim.projected_total_mean,
        "mc_total_std": sim.projected_total_std,
        "mc_home_runs": sim.home_runs_mean,
        "mc_away_runs": sim.away_runs_mean,
        "mc_sim": sim.to_storage_dict(),
    }
    if matchup_meta and matchup_meta.get("lineup_weighted"):
        out["mc_lineup_weighted"] = True
    return out


def monte_carlo_enabled() -> bool:
    return os.getenv("MLB_MC_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def apply_monte_carlo_to_prediction(
    pred: dict[str, Any],
    features: dict[str, Any],
    *,
    n_sims: int | None = None,
    seed: int | None = None,
) -> GameSimResult | None:
    """Overlay MC outputs onto a game prediction dict (in place)."""
    if not monte_carlo_enabled():
        return None

    ml_baseline = {
        "home_win_prob": float(pred.get("home_win_prob", 0.5)),
        "projected_total": float(pred.get("projected_total", 9.0)),
    }
    rates = resolve_team_rates(
        features,
        projected_total=ml_baseline["projected_total"],
        home_win_prob=ml_baseline["home_win_prob"],
    )
    matchup_meta = None
    as_of = features.get("as_of_date") or features.get("game_date")
    if as_of is not None:
        from datetime import date as date_type

        if isinstance(as_of, str):
            as_of = date_type.fromisoformat(str(as_of)[:10])
        from app.services.etl.mlb.profiles.lineup_runs import (
            maybe_adjust_rates_from_lineups,
        )

        rates, matchup_meta = maybe_adjust_rates_from_lineups(features, rates, as_of)
        from app.services.ballpark_pal.inject_game import maybe_apply_bpp_run_priors

        rates, bpp_meta = maybe_apply_bpp_run_priors(
            features,
            rates,
            as_of,
            game_id=pred.get("game_id"),
        )
        if bpp_meta:
            matchup_meta = {**(matchup_meta or {}), "bpp": bpp_meta}

    sim = simulate_game(
        rates,
        n_sims=n_sims or DEFAULT_N_SIMS,
        seed=(seed if seed is not None else DEFAULT_SEED) + int(pred.get("game_id", 0)),
        ml_baseline=ml_baseline,
        matchup_meta=matchup_meta,
    )

    pred["home_win_prob"] = sim.home_win_prob
    pred["away_win_prob"] = sim.away_win_prob
    pred["projected_total"] = round(sim.projected_total_mean, 1)
    pred["home_projected_runs"] = round(sim.home_runs_mean, 1)
    pred["away_projected_runs"] = round(sim.away_runs_mean, 1)
    pred["run_line"] = round(sim.run_line_mean, 1)
    pred["sim_distribution"] = sim.to_storage_dict()
    pred["projection_source"] = "monte_carlo"
    return sim


def enrich_predictions_with_monte_carlo(
    predictions: list[dict[str, Any]],
    games: list[dict[str, Any]],
    *,
    build_features=None,
) -> int:
    """Run MC for each prediction; returns count enriched."""
    if not monte_carlo_enabled():
        return 0

    if build_features is None:
        from app.services.etl.mlb.game_model import build_game_features

        build_features = build_game_features

    game_by_id = {g["game_id"]: g for g in games}
    enriched = 0
    for pred in predictions:
        game = game_by_id.get(pred.get("game_id"))
        if not game:
            continue
        features = build_features(game)
        if not features:
            continue
        from app.services.etl.mlb.profiles.lineup_runs import (
            attach_lineup_features_for_mc,
        )

        attach_lineup_features_for_mc(game, features)
        for key in (
            "home_lineup",
            "away_lineup",
            "home_lineup_ids",
            "away_lineup_ids",
            "home_pitcher_id",
            "away_pitcher_id",
            "home_pitcher_hand",
            "away_pitcher_hand",
            "game_date",
        ):
            if key in game and key not in features:
                features[key] = game[key]
        if "game_date" not in features and game.get("date"):
            features["game_date"] = game["date"]
        if apply_monte_carlo_to_prediction(pred, features) is not None:
            enriched += 1
    if enriched:
        logger.info(
            "Monte Carlo enriched %s/%s games (n_sims=%s)",
            enriched,
            len(predictions),
            DEFAULT_N_SIMS,
        )
    return enriched
