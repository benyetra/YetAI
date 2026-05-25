# NHL ML ops

Offline backtest for stored predictions vs `pred_nhl_*_actuals` tables.

## Backtest CLI

Entry: `scripts/nhl_backtest.py` (package: `app/services/etl/nhl/backtest/`).

```bash
cd backend
PYTHONPATH=. python scripts/nhl_backtest.py --quick
PYTHONPATH=. python scripts/nhl_backtest.py --start-date 2025-11-01 --end-date 2025-12-31
PYTHONPATH=. python scripts/nhl_backtest.py --quick --write-baseline
```

Requires `DATABASE_URL` with joined prediction + actual rows in range.

Metrics:

| Market | MAE field | O/U vs line |
|--------|-----------|-------------|
| Goalie saves | `goalie_mae` | `saves_line` |
| Player SOG | `sog_mae` | `shots_line` |
| Team totals | `totals_mae` | `draftkings_ou_line` / `suggested_ou_line` |

Summarized output also includes aggregate `ou_hit_rate` across all graded rows with a line.

## CI regression gate

Committed fixture: `tests/fixtures/nhl_backtest_quick_baseline.json`.

CI runs `tests/test_nhl_backtest_regression.py` only (synthetic rows; no API or Postgres). Tolerances vs baseline:

- `goalie_mae`: +0.5
- `sog_mae`: +0.3
- `totals_mae`: +0.25
- `ou_hit_rate`: −0.03

Refresh after intentional model changes:

```bash
cd backend
PYTHONPATH=. python scripts/update_nhl_backtest_baseline.py
pytest tests/test_nhl_backtest_regression.py -q
git add tests/fixtures/nhl_backtest_quick_baseline.json
```

## Goalie saves ML (shadow → promote)

| Item | Path / env |
|------|------------|
| Inference | `app/services/etl/nhl/goalie_saves_ml.py` |
| Train CLI | `python -m app.services.etl.nhl.ml_training.train_goalie_model --start YYYY-MM-DD --end YYYY-MM-DD [--upload]` |
| S3 artifact | `s3://yetibets/nhl/ml_models/goalie_saves.pkl` (+ `_metadata.json`) |
| Local override | `NHL_GOALIE_MODEL_LOCAL=/path/to/dir` |
| Promote flag | `NHL_GOALIE_ML_ENABLED=1` (default off) |

**Shadow writes (flag unset):**

- `predicted_saves` = heuristic (`heuristic-v1`)
- `features_used.ml_shadow_saves` = ML regressor when model loads
- `model_version` = `heuristic-v1`

**Promotion gate (offline backtest):**

1. Replay slates with `scripts/nhl_backtest.py` after shadow rows exist.
2. Compare `goalie_metrics.methods.heuristic.mae` vs `goalie_metrics.methods.ml.mae`.
3. Promote when ML MAE is **≥ 5% lower** than heuristic MAE  
   (`ml_mae <= heuristic_mae * 0.95`), or document O/U tradeoff per roadmap.
4. Upload artifact, set `NHL_GOALIE_ML_ENABLED=1` on API/worker.

Unit tests: `tests/test_nhl_goalie_saves_ml.py` (synthetic fixture; no S3/DB).

## Player SOG ML (shadow → promote)

| Item | Path / env |
|------|------------|
| Inference | `app/services/etl/nhl/player_shots_ml.py` |
| Train CLI | `python -m app.services.etl.nhl.ml_training.train_player_shots_model --start YYYY-MM-DD --end YYYY-MM-DD [--upload]` |
| S3 artifact | `s3://yetibets/nhl/ml_models/player_sog.pkl` (+ `_metadata.json`) |
| Local override | `NHL_PLAYER_SOG_MODEL_LOCAL=/path/to/dir` |
| Promote flag | `NHL_PLAYER_SOG_ML_ENABLED=1` (default off) |

**Shadow writes (flag unset):**

- `predicted_shots` = heuristic (`heuristic-v1`)
- `features_used.ml_shadow_sog` = XGB regressor when model loads
- `model_version` = `heuristic-v1`

**Promotion gate (offline backtest):**

1. Replay slates with `scripts/nhl_backtest.py` after shadow rows exist.
2. Compare `sog_metrics.methods.heuristic.mae` vs `sog_metrics.methods.ml.mae`.
3. Promote when ML MAE is **≥ 5% lower** than heuristic MAE  
   (`ml_mae <= heuristic_mae * 0.95`), or document O/U tradeoff per roadmap.
4. Upload artifact, set `NHL_PLAYER_SOG_ML_ENABLED=1` on API/worker.

Unit tests: `tests/test_nhl_player_shots_ml.py` (synthetic fixture; no S3/DB).

## Team totals ML (shadow → promote)

| Item | Path / env |
|------|------------|
| Inference | `app/services/etl/nhl/team_totals_ml.py` |
| Train CLI | `python -m app.services.etl.nhl.ml_training.train_team_totals_model --start YYYY-MM-DD --end YYYY-MM-DD [--upload]` |
| S3 artifact | `s3://yetibets/nhl/ml_models/team_totals.pkl` (+ `_metadata.json`) |
| Local override | `NHL_TOTALS_MODEL_LOCAL=/path/to/dir` |
| Promote flag | `NHL_TOTALS_ML_ENABLED=1` (default off) |

**Shadow writes (flag unset):**

- `predicted_total_goals` = heuristic (`heuristic-v1`)
- `features_used.ml_shadow_total` = heuristic + GBM residual when model loads
- `model_version` = `heuristic-v1`

**Promotion gate (offline backtest):**

1. Replay slates with `scripts/nhl_backtest.py` after shadow rows exist.
2. Compare `totals_metrics.methods.heuristic.mae` vs `totals_metrics.methods.ml.mae`.
3. Promote when ML MAE is **≥ 5% lower** than heuristic MAE  
   (`ml_mae <= heuristic_mae * 0.95`), or document O/U tradeoff per roadmap.
4. Upload artifact, set `NHL_TOTALS_ML_ENABLED=1` on API/worker.

Unit tests: `tests/test_nhl_team_totals_ml.py` (synthetic fixture; no S3/DB).

See also [NHL_ETL_PARITY.md](./NHL_ETL_PARITY.md) and [ML_PROMOTION.md](./ML_PROMOTION.md).
