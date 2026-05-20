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
| `ODDS_API_KEY` | The Odds API events/lines for goalie, SOG, totals |
| `REDIS_URL` | Celery broker (worker) |

Optional: none required for HR-style ML (NHL uses rule/DB models, not S3 pickles).

## API / UI

- `GET /api/v1/predictions/nhl` — `goalie_predictions`, `player_shots`, `team_totals`
- `/predictions/nhl` — frontend tables for all three

## Validation

```bash
cd backend
PYTHONPATH=. python3 scripts/validate_nhl_pipeline.py
PYTHONPATH=. python3 scripts/smoke_import_nhl_etl.py
```

## Not ported (defer)

- `confirm_starters.py` — pre-game starter confirmation
- `generate_daily_predictions.py` `main()` — goalie-only odds path (overlaps automation)
- `backtest_predictions.py`, `collect_available_data.py` backfill CLI
- `poll_nhl_live` — still noop in `live_pollers.py`

## Season

Current season id in code: `20252026` (2025-26). Update in `collect_historical_data` / `daily_predictions` when NHL rolls season.
