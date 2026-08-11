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
| `nfl.sync_defense_schemes` | `defensive_schemes.yaml` → `pred_nfl_defense_scheme` |
| `nfl.anytime_td_projector` | Feature rows → λ → P(TD) → `pred_nfl_anytime_td_predictions` |
| `nfl.anytime_td_betting` | Odds API `player_anytime_td` attach on predictions |
| `nfl.anytime_td_actuals` | nflverse weekly TDs → grade vs predictions → `pred_nfl_anytime_td_actuals` |
| `yetiwatch.nfl` | YetiWatch news/signals for NFL props |

### `NFL_PHASES` (Beat: `nfl-update-pipeline-daily` 4:30 ET)

1. **actuals** — `nfl_collect_qb_actuals`, `nfl_collect_kicker_actuals`, `nfl_store_game_actuals`, `nfl_anytime_td_actuals`
2. **game_lines** — `nfl_update_game_lines`
3. **game_projections** — `nfl_spread_projector`, `nfl_totals_projector`
4. **anytime_td** — `nfl_sync_defense_schemes`, `nfl_anytime_td_projector`, `nfl_anytime_td_betting`
5. **predictions** — `nfl_yetiwatch`, `nfl_qb_weekly`, `nfl_kickers`

### Anytime TD admin slice

| Entry | Role |
|-------|------|
| `run_nfl_anytime_td_pipeline` | Admin enqueue + Beat `nfl-anytime-td-pipeline-midweek` (Tue–Fri 11:00 ET) |
| `NFL_ANYTIME_TD_PHASES` | actuals → schemes → projector → Odds (no QB/kickers) |

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
| `scheme_loader.py` | Load `defensive_schemes.yaml`; upsert `pred_nfl_defense_scheme` (encoded int/float; season rows `week=0`) |
| `sync_defense_schemes.py` | Celery wrapper for scheme YAML sync |
| `anytime_td_features.py` | Scheme multipliers from YAML string tags (not DB-encoded values) |
| `anytime_td_projector.py` | `pred_nfl_anytime_td_predictions` |
| `anytime_td_betting.py` | Market odds/edge on anytime TD predictions |
| `anytime_td_actuals.py` | `pred_nfl_anytime_td_actuals` (rush + rec TDs only; passing TDs excluded) |
| `nfl_common.py` | Week/season helpers |

Static data shipped in the image: `backend/data/nfl/` (weather, distance, FG history).

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres (`pred_qb_*`, `pred_kicker_*`, `pred_nfl_*`) |
| `ODDS_API_KEY` | QB passing O/U, kicker markets, NFL game lines, `player_anytime_td` |
| `REDIS_URL` | Celery broker (worker) |
| `NFL_SEASON` | Override season year (default **2026**) |
| `NFL_ANYTIME_TD_UI` | Show anytime-TD UI group when `1`/`true` (default off; requires backtest gate) |

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

**QB / kicker replay** (needs `DATABASE_URL`):

```bash
cd backend
PYTHONPATH=. python scripts/nfl_backtest.py --quick
PYTHONPATH=. python scripts/nfl_backtest.py --quick --write-baseline
```

Offline CI: `tests/test_nfl_backtest_regression.py` vs `tests/fixtures/nfl_backtest_quick_baseline.json`.

**Anytime TD gate** (offline `--quick` smoke; no Odds credits):

```bash
cd backend
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick --write-metrics
PYTHONPATH=. python scripts/nfl_anytime_td_backtest.py --quick --check-gate
```

Artifact: `backend/models/nfl/anytime_td_metrics.json`. Offline CI:
`tests/test_nfl_anytime_td_backtest.py`. Enable UI only when metrics pass gate
and `NFL_ANYTIME_TD_UI` / `NEXT_PUBLIC_NFL_ANYTIME_TD_UI` are set — see
`backend/docs/NFL_ANYTIME_TD.md`.

## Still deferred

- `advanced_qb_predictor.py` as a standalone warehouse port (current path:
  `qb_dynamic` tier-v2 + `qb_features` + GBM shadow in `qb_passing_yards_ml.py`)
  — full promote still gated on ≥10% MAE lift after retrain
- `enhanced_qb_integration.py`, warehouse FG tables
- Midweek Beat `nfl-anytime-td-pipeline-midweek` (Tue–Fri 11:00 ET) + admin enqueue card

## Season / week

Single source: `nfl_common.py` — `get_nfl_season()` (`NFL_SEASON` env), `get_current_nfl_week()`.

## Anytime TD + defensive schemes

- **Actuals grading** — `player_anytime_td` / design spec: player **scores** ≥1 TD (rushing or receiving). Passing TDs do not count for the passer.
- **Feature path** — `anytime_td_features.scheme_defense_adjustment` reads string tags from `defensive_schemes.yaml` (e.g. `cover_3`, `zone`, `high`).
- **DB persistence** — `scheme_loader` encodes tags to int/float on upsert (`cover_3`→3, `zone`→0.0, `high`→0.75). Use `decode_cover_base` / `decode_man_zone_lean` / `decode_pressure_lean` or `db_row_to_scheme_tags` when reading encoded rows back to tags.
- **Season scheme rows** — YAML sync upserts with `week=0` (`SEASON_LEVEL_WEEK`) so Postgres unique `(team_name, season, week)` is idempotent. Column stays nullable for future week-specific overrides.

## Ops: Elo cold start

Before Week 1 REG, run once (admin / manual enqueue):

```bash
celery -A app.celery_app call app.tasks.etl_pipeline.nfl.seed_elo_history
```

Or from Python: `from app.services.etl.nfl.seed_elo_history import run; run()`.
