# NBA ML operations

## Prop calibration (BKB-2.6)

Holdout residual quintiles on projected value → `P(actual > line)` via normal
approximation per bucket. Fitted during `run_train_props` and stored in model
metadata as `prop_calibration`.

**Gate:** every holdout bucket with ≥5 rows must have `|residual_mean| < 0.3`
(residual = `pred - actual`). When the gate fails, `passes_gate` is false and
inference does not attach `p_over`.

**Enable at inference** (default off):

```bash
export NBA_PROP_CALIBRATION_ENABLED=1
```

Requires `fanduel_line` on the projection row and stable calibration in
`xgb_<stat>_metadata.json` (`prop_calibration.passes_gate: true`).

`p_over` is written to `row.factors["p_over"]` when a `factors` JSON column
exists; otherwise attachment is a no-op until a column is added.

**Train + refresh metadata:**

```bash
cd backend
PYTHONPATH=. .venv/bin/python -m app.services.etl.nba.ml_training.run_train_props \
  --stat points --season-start 2024-10-01 --season-end 2025-04-15 --upload
```

**Tests:**

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest tests/test_nba_prop_calibration.py -q
```

See also `docs/NBA_ETL_PARITY.md` for ETL task mapping.
