# MLB Matchup Profiles (Phase 0–2)

Versioned batter/pitcher Statcast profile snapshots for strikeout integration (Phase 3).

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `MLB_PROFILES_ENABLED` | `0` | Enable ProfileStore consumers (Phase 3+) after backfill |
| `MLB_STATCAST_S3_PREFIX` | `s3://yetibets/mlb/statcast/pitches` | Raw pitch parquet store |
| `MLB_PROFILE_WINDOW_DEFAULT` | `season` | Default read window |

## Statcast backfill

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --start-year 2018 --end-year 2024
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --season 2024 --month 5
PYTHONPATH=. .venv/bin/python scripts/mlb_statcast_backfill.py --season 2024 --force
```

Partitions: `{prefix}/season=YYYY/month=MM/part.parquet` plus `season=YYYY/_manifest.json`.

## Profile rebuild

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_rebuild_profiles.py --as-of 2025-05-25
```

## Celery (admin)

- `app.tasks.etl_pipeline.mlb.statcast_backfill_season`
- `app.tasks.etl_pipeline.mlb.statcast_incremental`
- `app.tasks.etl_pipeline.mlb.rebuild_profiles`

Beat (UTC): incremental ~09:30, rebuild ~10:00 (before `mlb-projections-daily` at 14:00).

## Phase 3 — Strikeouts

When `MLB_PROFILES_ENABLED=1`, `lineup_matchup_adjusted_strikeouts` reads `ProfileStore` instead of live `fetch_pitcher_data` / `fetch_batter_performance_vs_pitches`. Logs `matchup_source` (`observed | shrunk | archetype | league | legacy_api`).

Backtest:

```bash
cd backend
PYTHONPATH=. python scripts/mlb_backtest.py --quick --use-profiles
```

Set `MLB_PROFILES_ENABLED=0` to force legacy API path.

## Phase 4 — Hits / HR contact

Batter profiles include `xwoba_by_pitch`, `iso_by_pitch`, `barrel_rate_by_pitch`. Hits board stores `profile_version` and `matchup_contact_score` on `pred_hitter` / `pred_homer`. HR daily features optionally merge `matchup_contact_score` when profiles are enabled.

## Verify

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py
```

## Migration

Alembic revision `20260526_mlb_profiles` — apply via Database Migrations workflow.
