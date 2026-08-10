# NFL ETL parity (YetiBets → YetAI)

Reference: `YetiBets/scripts/nfl/` (weekly QB + kicker path; no single daily shell like NHL).

## Celery orchestrator

| YetAI task | YetiBets equivalent |
|------------|---------------------|
| `run_nfl_update_pipeline` | Manual chain: actuals → lines → spread/totals → props |
| `nfl.collect_qb_actuals` | `collect_qb_actuals.py` |
| `nfl.collect_kicker_actuals` | `collect_kicker_actuals.py` |
| `nfl.store_game_actuals` | Finals → spread/totals actuals + Elo snapshot refresh |
| `nfl.update_game_lines` | Odds API `americanfootball_nfl` → `pred_nfl_game_lines` |
| `nfl.spread_projector` | Elo + PPG overlay → `pred_nfl_spread_projections` |
| `nfl.totals_projector` | Team PPG matchup → `pred_nfl_totals_projections` |
| `nfl.seed_elo_history` | One-off nflverse 2023–2025 REG seed → `pred_nfl_team_elo` |
| `nfl.qb_weekly` | `qb_dynamic_heroku.py` then `qb_betting_heroku.py` |
| `nfl.qb_dynamic` / `nfl.qb_betting` | Same modules, fireable individually for debugging |
| `nfl.kickers` | `kickers.py` → `pred_kickers` + `pred_kicker_predictions` |
| `yetiwatch.nfl` | YetiWatch news/signals for NFL props |

### `NFL_PHASES` (Beat: `nfl-update-pipeline-daily` 4:30 ET)

1. **actuals** — `nfl_collect_qb_actuals`, `nfl_collect_kicker_actuals`, `nfl_store_game_actuals`
2. **game_lines** — `nfl_update_game_lines`
3. **game_projections** — `nfl_spread_projector`, `nfl_totals_projector`
4. **predictions** — `nfl_yetiwatch`, `nfl_qb_weekly`, `nfl_kickers`

Failures in non-critical tasks still yield `partial_failure` on the orchestrator; QB weekly + kickers are **critical**.

## Modules (ported)

| Module | Tables / role |
|--------|----------------|
| `update_game_lines.py` | `pred_nfl_game_lines` (Odds API) |
| `spread_projector.py` | `pred_nfl_spread_projections` |
| `totals_projector.py` | `pred_nfl_totals_projections` |
| `store_game_actuals.py` | `pred_nfl_spread_actuals`, `pred_nfl_totals_actuals`, `pred_nfl_team_elo` |
| `seed_elo.py` / `seed_elo_history.py` | nflverse REG history → Elo seed |
| `team_names.py` | Odds ↔ nflverse name normalizer |
| `qb_dynamic.py` | `pred_qb_predictions` (yards from nflverse) |
| `qb_betting.py` | O/U lines + edges on `pred_qb_predictions` |
| `kickers.py` | `pred_kickers`, `pred_kicker_predictions` |
| `kicker_prediction.py` | Scoring helpers for kickers |
| `statistical_kicker_prediction.py` | CSV-backed stats (`data/nfl/*.csv`) |
| `collect_qb_actuals.py` | `pred_qb_actuals` |
| `collect_kicker_actuals.py` | `pred_kicker_actuals` |
| `nfl_common.py` | Week/season helpers |

Static data shipped in the image: `backend/data/nfl/` (weather, distance, FG history).

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres (`pred_qb_*`, `pred_kicker_*`, `pred_nfl_*`) |
| `ODDS_API_KEY` | QB passing O/U, kicker markets, NFL game lines |
| `REDIS_URL` | Celery broker (worker) |
| `NFL_SEASON` | Override season year (default **2026**) |

Python: `nfl-data-py` (see `requirements.txt`).

## API / UI

- `GET /api/v1/predictions/nfl` — `qb_predictions`, `kicker_predictions`, `spreads`, `totals`
- `/predictions/nfl` — frontend QB + kicker tables + game projection cards

## Validation

```bash
cd backend
PYTHONPATH=. python3 scripts/smoke_import_nfl_etl.py
PYTHONPATH=. python3 scripts/validate_nfl_pipeline.py   # needs DATABASE_URL
```

During NFL season, expect rows in `pred_qb_predictions` / `pred_kicker_predictions` for the current week after a successful pipeline run.

## Kicker ML ensemble (ported)

- Models: local `backend/models/nfl/*.pkl` **or** S3 prefix (recommended on Railway)
- `ml_kicker_ensemble.py` blends ML FG probability with statistical score in `kickers.py`

| Variable | Purpose |
|----------|---------|
| `NFL_MODELS_S3_PREFIX` | e.g. `s3://yetibets/nfl/` — loads `logistic_model.pkl`, `xgboost_model.pkl`, `main_scaler.pkl`, etc. |
| `NFL_KICKER_ML_BLEND_WEIGHT` | Blend weight (default `0.35`) |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Required when using S3 prefix |

## Backtest CLI

```bash
cd backend
PYTHONPATH=. python scripts/nfl_backtest.py --quick
PYTHONPATH=. python scripts/nfl_backtest.py --quick --write-baseline
```

Offline CI: `tests/test_nfl_backtest_regression.py` vs `tests/fixtures/nfl_backtest_quick_baseline.json`.

## Still deferred

- `advanced_qb_predictor.py` / QB **yards** ML ensemble (current path: tier table in `qb_dynamic.py`)
- `enhanced_qb_integration.py`, warehouse FG tables
- Midweek Beat refresh for line movement (daily 4:30 ET only for v1)

## Season / week

Single source: `nfl_common.py` — `get_nfl_season()` (`NFL_SEASON` env), `get_current_nfl_week()`.

## Ops: Elo cold start

Before Week 1 REG, run once (admin / manual enqueue):

```bash
celery -A app.celery_app call app.tasks.etl_pipeline.nfl.seed_elo_history
```

Or from Python: `from app.services.etl.nfl.seed_elo_history import run; run()`.
