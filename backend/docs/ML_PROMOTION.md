# ML model promotion playbook

Shared workflow for promoting trained prediction models from offline evaluation to production inference. MLB is the reference implementation; other sports follow the same stages with sport-specific paths and gates.

## Pipeline overview

```text
backtest / walk-forward eval
        → holdout metrics (MAE, Brier, accuracy)
        → promote artifact to S3 (+ optional *_metadata.json)
        → Celery / daily ETL smoke (writes rows with model_version)
        → accuracy monitoring (by model_version in Postgres)
```

| Stage | Purpose | MLB entry points |
|-------|---------|------------------|
| Backtest | Historical replay, compare configs | `scripts/mlb_backtest.py`, `app/services/etl/mlb/backtest/` — see [MLB_ML_OPS.md](./MLB_ML_OPS.md) |
| Holdout eval | Out-of-sample gates before upload | `app/services/etl/mlb/game_model_eval.py` (game win/total), strikeout retrain via `strikeout_training.py` |
| S3 promote | Production artifact + metadata | `s3://yetibets/mlb/game_model_win.pkl`, `game_model_total.pkl`, `strikeout_model.pkl`; optional `*_metadata.json` sidecars |
| Smoke | Verify imports + write path | `scripts/smoke_mlb_strikeouts.py`, `run_game_projection_pipeline`, admin `ml-ops-status` |
| Monitor | Grade picks by version tag | `mlb_accuracy_service`, backtest run index under `scripts/mlb_backtest_results/runs/` |

## model_version on prediction writes

Production rows should carry a short tag (≤20 chars) in `model_version` so accuracy and backtests can segment by artifact generation.

| Table | Column | Resolver |
|-------|--------|----------|
| `pred_strikeout_projections` | `model_version` | `resolve_mlb_strikeout_model_version()` in `app/services/ml_model_version.py` |
| `pred_game_projections` | `model_version` | `resolve_mlb_game_projection_model_version()` |

Resolution order:

1. Environment override (`MLB_STRIKEOUT_MODEL_VERSION`, `MLB_GAME_MODEL_VERSION`)
2. S3 sidecar JSON (`mlb/strikeout_model_metadata.json`, `mlb/game_model_metadata.json`) — same pattern as WNBA `xgb_<stat>_metadata.json`
3. Artifact date from S3 `LastModified` or local pickle mtime (`gb-20260525`, `ens-20260525`)
4. Stable defaults: `heuristic-v1` (no game ML), `gb-cal-v1` / `ens-<n>f` (ML loaded)

Example metadata sidecar (optional, recommended on next retrain):

```json
{
  "model_version": "gb-2026-05-25",
  "train_date": "2026-05-25",
  "training_run_id": "celery-retrain-abc123",
  "holdout_mae": 1.4
}
```

## WNBA reference gates (template for other sports)

WNBA prop models use hard MAE gates in `app/services/etl/wnba/ml_training/validate_model.py` before `upload_to_s3.py` writes artifacts:

| Stat | MAE gate |
|------|----------|
| points | ≤ 4.5 |
| assists | ≤ 1.5 |
| rebounds | ≤ 2.0 |

MLB game promotion should mirror this pattern in `game_model_eval.py` (Brier / ML accuracy lifts, deferred feature promotion). Strikeout retrain uses a minimum joined-row count (`MLB_STRIKEOUT_MIN_JOINED_ROWS`, default 50) before `classification_model.train_and_persist()`.

## CI: fast ML unit gate

Workflow: `.github/workflows/ml-model-quality.yml`

Runs offline tests only (no network):

```bash
cd backend
pytest tests/test_mlb_deferred_features.py tests/test_wnba_ml_training.py tests/test_ml_model_version.py -q
```

### CI baselines (MLB quick backtest)

Offline regression gate: `tests/test_mlb_backtest_regression.py` (no network).

| Item | Path |
|------|------|
| Baseline fixture | `tests/fixtures/mlb_backtest_quick_baseline.json` |
| Summarize / compare | `app/services/etl/mlb/backtest/metrics.py` — `summarize_backtest_metrics`, `check_metrics_against_baseline` |
| Default tolerances | Brier +0.02, moneyline accuracy −0.03, hit MAE +0.5 (when present) |

The test module uses **synthetic** scorer output to assert worse/same/better behavior against the fixture. CI does not run `mlb_backtest.py`.

**Refresh baseline** after an intentional model change (local network required):

```bash
cd backend
PYTHONPATH=. python scripts/update_mlb_backtest_baseline.py
pytest tests/test_mlb_backtest_regression.py -q
git add tests/fixtures/mlb_backtest_quick_baseline.json
```

Use `--dry-run` to preview metrics without writing the file. See [MLB_ML_OPS.md](./MLB_ML_OPS.md).

### Adding other sport MAE / Brier baselines

1. Add a test module that loads a committed metrics JSON fixture and calls the same compare helpers (or sport-specific gates).
2. Register the file in `ml-model-quality.yml` under `pytest` args.
3. Document the fixture path and refresh script here.

Do not call live S3, Postgres, or sport APIs from this job; keep gates deterministic.

## Operational checklist (MLB)

1. Run holdout / backtest; record `model_version` label in run JSON (`--model-version` on backtest CLI).
2. Upload pickles (+ metadata JSON with `model_version` / `train_date`).
3. Trigger daily pipeline or Celery smoke; confirm new rows show the expected tag.
4. After games complete, check accuracy tiles; compare versions in SQL:

   ```sql
   SELECT model_version, COUNT(*)
   FROM pred_game_projections
   WHERE date = CURRENT_DATE
   GROUP BY 1;
   ```

5. Only then treat the artifact as promoted for auto-pick / public API surfaces.

See [MLB_ML_OPS.md](./MLB_ML_OPS.md) for admin endpoints, retrain commands, and HR rebuild stages.

## MLB matchup profiles (Statcast tensors)

Promotion is **infrastructure + backfill**, not a single pickle. Stages:

1. Apply Alembic `20260526_mlb_profiles` → `20260526_mlb_archetypes` on staging/prod.
2. S3 Statcast backfill (`scripts/mlb_statcast_backfill.py` or `mlb-statcast-backfill` workflow).
3. `scripts/mlb_rebuild_profiles.py --as-of <slate-date>`.
4. `scripts/mlb_assign_archetypes.py --season <year>` (optional but recommended).
5. `scripts/prod_verify_mlb_profiles.py --min-batter-coverage 80` (tune threshold).
6. Set `MLB_PROFILES_ENABLED=1` on API + celery-worker; smoke strikeouts + game MC.
7. Monitor `batter_reliability_coverage_pct` and ingest lag; PA pilot stays off prod MC until Phase 7 sign-off.

Docs: [MLB_MATCHUP_PROFILES.md](./MLB_MATCHUP_PROFILES.md).
