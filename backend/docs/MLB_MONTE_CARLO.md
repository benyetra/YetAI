# MLB Monte Carlo (game-level MVP)

## Overview

`app/services/etl/mlb/monte_carlo.py` simulates team run totals with a **Negative Binomial** (or Poisson when dispersion=1) model, then aggregates:

- Home win probability
- Mean / std of total runs
- Total and margin percentiles (p10–p90)
- Per-team expected runs (`home_lambda`, `away_lambda`)

This is wired into the daily game projection pipeline after `predict_games()` and before market edge computation.

## Configuration

| Env | Default | Meaning |
|-----|---------|---------|
| `MLB_MC_ENABLED` | `1` | Set `0` to disable MC overlay |
| `MLB_MC_N_SIMS` | `10000` | Simulations per game |
| `MLB_MC_DISPERSION` | `1.35` | Over-dispersion vs Poisson (var = mu × dispersion) |
| `MLB_MC_SEED` | `42` | Base RNG seed (per-game offset by `game_id`) |
| `MLB_MC_BLEND_ML` | (code default 0.65) | Weight on ML total/win split vs feature heuristics |

## Storage

`pred_game_projections.sim_distribution` (JSON) holds the full `GameSimResult` summary. Primary columns (`home_win_prob`, `projected_total`, run splits) are **overwritten** with MC aggregates when MC is enabled.

`model_version` is suffixed with `+mc` when MC runs (see `resolve_mlb_game_projection_model_version`).

## API: P(over) at a total line

**Single game**

```http
GET /api/v1/predictions/mlb/p-over-total?game_id=746901&line=8.5&date=2026-05-25
```

Returns `p_over_total`, `p_under_total`, and the projection snapshot used for rates.

**Batch on `/mlb`**

```http
GET /api/v1/predictions/mlb?date=2026-05-25&total_line=8.5
```

Each `game_projections[]` row includes `p_over_total`, `p_under_total`, and `total_line`.

Empirical probability uses `MLB_MC_P_OVER_N_SIMS` (default 8000) re-simulations from
`sim_distribution.home_lambda` / `away_lambda`, or projected total + win prob if sim JSON is absent.

## Backtest

`BacktestModelRunner.predict_game()` attaches `mc_home_wp`, `mc_total`, `mc_sim` alongside
ensemble/heuristic point estimates. `BacktestScorer` reports a `monte_carlo` block under
`game_metrics` (Brier, ML accuracy, total MAE, O/U vs market line when historical totals exist).

Env: `MLB_MC_BACKTEST_N_SIMS` (default 5000).

## Smoke test (no DB)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_monte_carlo.py
```

## Unit tests

```bash
cd backend
PYTHONPATH=. pytest tests/test_mlb_monte_carlo.py -q
```

## Roadmap (not in MVP)

- Plate-appearance / bullpen-chain simulation
- Correlation matrices for SGP
- Backtest scorer comparing MC vs ensemble Brier/MAE
- Live in-game state updates (Module 11)
