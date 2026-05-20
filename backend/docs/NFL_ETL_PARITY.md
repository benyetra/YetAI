# NFL ETL parity (YetiBets → YetAI)

Reference: `YetiBets/scripts/nfl/` (weekly QB + kicker path; no single daily shell like NHL).

## Celery orchestrator

| YetAI task | YetiBets equivalent |
|------------|---------------------|
| `run_nfl_update_pipeline` | Manual chain: actuals scripts → `qb_dynamic_heroku.py` → `qb_betting_heroku.py` → `kickers.py` |
| `nfl.collect_qb_actuals` | `collect_qb_actuals.py` |
| `nfl.collect_kicker_actuals` | `collect_kicker_actuals.py` |
| `nfl.qb_weekly` | `qb_dynamic_heroku.py` then `qb_betting_heroku.py` |
| `nfl.qb_dynamic` / `nfl.qb_betting` | Same modules, fireable individually for debugging |
| `nfl.kickers` | `kickers.py` → `pred_kickers` + `pred_kicker_predictions` |

### `NFL_PHASES` (manual enqueue / future Beat)

1. **actuals** — `nfl_collect_qb_actuals`, `nfl_collect_kicker_actuals`
2. **predictions** — `nfl_qb_weekly`, `nfl_kickers`

Failures in non-critical tasks still yield `partial_failure` on the orchestrator; QB weekly + kickers are **critical**.

## Modules (ported)

| Module | Tables / role |
|--------|----------------|
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
| `DATABASE_URL` | Postgres (`pred_qb_*`, `pred_kicker_*`) |
| `ODDS_API_KEY` | QB passing O/U and kicker market lines |
| `REDIS_URL` | Celery broker (worker) |

Python: `nfl-data-py` (see `requirements.txt`).

## API / UI

- `GET /api/v1/predictions/nfl` — `qb_predictions`, `kicker_predictions` (already wired)
- `/predictions/nfl` — frontend QB + kicker tables

## Validation

```bash
cd backend
PYTHONPATH=. python3 scripts/smoke_import_nfl_etl.py
PYTHONPATH=. python3 scripts/validate_nfl_pipeline.py   # needs DATABASE_URL
```

During NFL season, expect rows in `pred_qb_predictions` / `pred_kicker_predictions` for the current week after a successful pipeline run.

## Not ported (defer)

- `ml_pipeline.py` / ensemble `.pkl` models under YetiBets `models/nfl/`
- `advanced_qb_predictor.py`, `enhanced_qb_integration.py`, warehouse FG tables
- Backtest / retrain CLIs, Discord notifications
- Celery Beat schedule for NFL (orchestrator is enqueue-only until schedule is defined)

## Season / week

Week detection lives in `kickers.get_current_nfl_week()` and `nfl_common.py`. Actuals collectors default season `2025` in CLI paths — align with active NFL season when rolling forward.
