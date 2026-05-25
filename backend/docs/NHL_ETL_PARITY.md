# NHL ETL parity (YetiBets → YetAI)

Reference: `YetiBets/scripts/nhl/` (most complete sport port in YetiBets).

## Celery orchestrator

| YetAI task | YetiBets equivalent |
|------------|---------------------|
| `run_nhl_update_pipeline` | `run_daily_automation.sh` + `collect_historical_data.py` (ingest) |
| `nhl.collect_ingest` | `collect_historical_data.py` default mode (games + goalie/team rollups) |
| `nhl.update_daily_stats` | `collect_historical_data.py --daily-update` / `update_daily_stats()` |
| `nhl.daily_predictions` | `automated_daily_predictions.py` |
| `nhl.collect_goalie_actuals` | `collect_goalie_actuals.py` (standalone; also inline in automation) |

### `NHL_PHASES` (beat / enqueue)

1. **ingest** — `nhl_collect_ingest`
2. **automation** — `nhl_daily_predictions` (goalie saves, player SOG, team totals O/U + lines + yesterday goalie actuals)

Individual steps remain in `ADMIN_FIREABLE_TASKS` for debugging.

## Prediction modules (ported)

| Module | Tables written |
|--------|----------------|
| `goalie_saves_model.py` | used by `daily_predictions` → `pred_nhl_goalie_predictions` |
| `player_shots_model.py` | → `pred_nhl_player_shots_predictions` |
| `team_totals_model.py` | → `pred_nhl_team_totals_predictions` |
| `generate_daily_predictions.py` | Odds API / DraftKings line helpers |

## Environment

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Postgres (`pred_nhl_*`) |
| `NHL_SEASON` | NHL API season id (`YYYYYYYY`, default `20252026` = 2025-26). Used by ingest, daily stats, and models via `app/services/etl/nhl/_config.py` |
| `ODDS_API_KEY` | The Odds API events/lines for goalie, SOG, totals |
| `REDIS_URL` | Celery broker (worker) |

| `NHL_GOALIE_MODEL_LOCAL` | Optional local dir with `goalie_saves.pkl` + metadata |
| `NHL_GOALIE_ML_ENABLED` | `1` to serve ML saves in production (default shadow only) |
| `NHL_PLAYER_SOG_MODEL_LOCAL` | Optional local dir with `player_sog.pkl` + metadata |
| `NHL_PLAYER_SOG_ML_ENABLED` | `1` to serve ML player SOG in production (default shadow only) |
| `NHL_TOTALS_MODEL_LOCAL` | Optional local dir with `team_totals.pkl` + metadata |
| `NHL_TOTALS_ML_ENABLED` | `1` to serve ML team totals in production (default shadow only) |

ML artifacts (optional): `s3://yetibets/nhl/ml_models/{goalie_saves,player_sog,team_totals}.pkl` — see [NHL_ML_OPS.md](./NHL_ML_OPS.md).

## API / UI

- `GET /api/v1/predictions/nhl` — `goalie_predictions`, `player_shots`, `team_totals`
- `/predictions/nhl` — frontend tables for all three

## Validation

```bash
cd backend
PYTHONPATH=. python3 scripts/validate_nhl_pipeline.py
PYTHONPATH=. python3 scripts/smoke_import_nhl_etl.py
```

## Odds edges (ported)

- `betting_edges.py` — saves / SOG / totals recommendations vs DraftKings lines
- `daily_predictions.py` — fetches player SOG lines via Odds API; no longer leaves `shots_line` / `betting_recommendation` null

## Backtest (ported)

- `app/services/etl/nhl/backtest/` + `scripts/nhl_backtest.py` — replay `pred_nhl_*_predictions` vs actuals; see [NHL_ML_OPS.md](./NHL_ML_OPS.md)
- CI: `tests/test_nhl_backtest_regression.py` (offline synthetic gate)

## Still deferred

- `confirm_starters.py` — pre-game starter confirmation (wired in `daily_predictions.py`)
- `collect_available_data.py` backfill CLI
- `poll_nhl_live` — still noop in `live_pollers.py`

## Season

Set `NHL_SEASON` when the league rolls (e.g. `20262027` for 2026-27). Default is `20252026` (2025-26) in `get_nhl_season()` (`_config.py`). Player SOG and team totals models use league averages from `pred_nhl_team_stats` when populated, with constants as fallback.
