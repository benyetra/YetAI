# MLB Matchup Profiles (Phases 0–8)

Versioned batter/pitcher Statcast profile snapshots for strikeouts, contact boards, game MC, and cold-start archetypes.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `MLB_PROFILES_ENABLED` | code default `0`; **prod YetAI + celery-worker = `1`** | Enable ProfileStore consumers (Phase 3+) after backfill |
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

Beat (ET): statcast incremental 09:30, profile rebuild 05:00 (finishes before projections), `mlb-projections-daily` 14:00.

## Phase 3 — Strikeouts

When `MLB_PROFILES_ENABLED=1`, `lineup_matchup_adjusted_strikeouts` reads `ProfileStore` instead of live `fetch_pitcher_data` / `fetch_batter_performance_vs_pitches`. Logs `matchup_source` (`observed | shrunk | archetype | league | legacy_api`).

Backtest:

```bash
cd backend
PYTHONPATH=. python scripts/mlb_backtest.py --quick --use-profiles
PYTHONPATH=. python scripts/mlb_backtest.py --quick --mc-lineup-profiles
```

Set `MLB_PROFILES_ENABLED=0` to force legacy API path. `--mc-lineup-profiles` enables profile-backed game MC lineup lambdas in backtest (uses boxscore lineups when present).

## Phase 4 — Hits / HR contact

Batter profiles include `xwoba_by_pitch`, `iso_by_pitch`, `barrel_rate_by_pitch`. Hits board stores `profile_version` and `matchup_contact_score` on `pred_hitter` / `pred_homer`. HR daily features optionally merge `matchup_contact_score` when profiles are enabled.

## Phase 5 — Game MC lineup lambdas

When `MLB_PROFILES_ENABLED=1`, `enrich_predictions_with_monte_carlo` calls `attach_lineup_features_for_mc` (active roster via `projected_lineup`) before `apply_monte_carlo_to_prediction`. Team mus are adjusted via `profiles/lineup_runs.py`; worker logs:

`MC lineup_weighted game_id=… home_adj=… away_adj=… sources=…`

`sim_distribution.matchup_meta` includes `lineup_weighted`, `archetype_pct`, `matchup_sources`.

**Verify MC + profiles:**

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_monte_carlo.py
```

Check `with_lineup_weighted_mc` for today's slate after `mlb.game_projections` runs.

## Phase 6 — Archetypes

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/mlb_assign_archetypes.py --season 2025
```

Table `mlb_player_archetypes` (migration `20260526_mlb_archetypes`). Batters with &lt;50 pitches in snapshot use archetype priors in `matchup_k`.

## Phase 7 — PA sim pilot (non-production)

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_pa_sim_pilot.py
```

Module `profiles/pa_sim_pilot.py` — not wired into daily game MC until backtest sign-off.

## Verify & monitoring

```bash
cd backend
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py
PYTHONPATH=. .venv/bin/python scripts/prod_verify_mlb_profiles.py --json --min-batter-coverage 80
```

Coverage report: `profiles/monitoring.py` (`snapshot_coverage_report`).

After enablement, confirm hits `profile_version`, MC `with_lineup_weighted_mc`, and K matchup log sources.

## Migrations

| Revision | Purpose |
|----------|---------|
| `20260526_mlb_profiles` | Pitcher/batter snapshot tables |
| `20260526_hitter_profile_meta` | Hits/HR `profile_version` columns |
| `20260526_mlb_archetypes` | Season archetype assignments |

Apply via Database Migrations workflow before enabling `MLB_PROFILES_ENABLED=1`.
