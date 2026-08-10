# Task 5 Report: Actuals + Celery phases + scheme sync task

**Status:** DONE  
**Commit:** `f15fed76` — `feat(nfl): wire anytime TD into Celery NFL pipeline`

## Deliverables

| File | Role |
|------|------|
| `anytime_td_actuals.py` | Grade weekly TD stats vs predictions; pure helpers + injectable `player_stats` |
| `sync_defense_schemes.py` | Thin Celery wrapper → `scheme_loader.upsert_schemes_from_yaml` |
| `scheme_loader.py` | Added YAML→DB encoding + `upsert_schemes_from_yaml` (32 teams, season-level `week=NULL`) |
| `etl_pipeline.py` | Four new tasks + `anytime_td` phase in `NFL_PHASES` |
| `NFL_ETL_PARITY.md` | Documented new tasks and 5-phase structure |
| `test_nfl_anytime_td_pipeline.py` | Phase membership + actuals/scheme pure helpers (mocked I/O) |
| `test_nfl_pipeline_phases.py` | Updated expected phase order |

## Celery tasks

| Task | Service |
|------|---------|
| `nfl.sync_defense_schemes` | `sync_defense_schemes.run()` |
| `nfl.anytime_td_projector` | `anytime_td_projector.run()` |
| `nfl.anytime_td_betting` | `anytime_td_betting.run()` |
| `nfl.anytime_td_actuals` | `anytime_td_actuals.run()` |

## `NFL_PHASES` structure

```
actuals: qb_actuals, kicker_actuals, store_game_actuals, anytime_td_actuals
game_lines: update_game_lines
game_projections: spread_projector, totals_projector
anytime_td: sync_defense_schemes, anytime_td_projector, anytime_td_betting
predictions: yetiwatch, qb_weekly, kickers
```

## Key interfaces

### Actuals pure helpers

- `aggregate_player_td_count(stat)` — sum passing/rushing/receiving TDs
- `player_scored_anytime_td(td_count)` — `td_count >= 1`
- `grade_correct_prediction(scored, td_probability, recommendation)` — `OVER` → scored; `NO_PLAY` → `None`; else threshold 0.5
- `build_actual_upsert_row(player_stat, season, week, prediction)` — DB row builder
- `run(season, week, player_stats=None)` — upsert to `pred_nfl_anytime_td_actuals`

### Scheme sync

- `yaml_entry_to_db_row(abbr, entry, season)` — encodes `cover_3`→3, `man`/`zone`→1.0/0.0, pressure→0.25/0.5/0.75
- `upsert_schemes_from_yaml(season, week=None)` — 32 canonical team rows

## Tests

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_nfl_anytime_td_pipeline.py tests/test_nfl_pipeline_phases.py \
  tests/test_nfl_anytime_td_model.py tests/test_nfl_scheme_loader.py \
  tests/test_nfl_anytime_td_projector.py tests/test_nfl_anytime_td_betting.py \
  tests/test_nfl_anytime_td_features.py tests/test_nfl_anytime_td_models_import.py -q
# 46 passed
```

## Concerns / follow-ups

1. **Scheme tag encoding** — YAML strings mapped to int/float for DB columns; reverse mapping needed if API exposes raw tags.
2. **Actuals week** — Uses `get_current_nfl_week()` like existing QB actuals; may need explicit prior-week grading if pipeline timing drifts.
3. **nflverse fetch** — `fetch_player_td_stats_nflverse` is live I/O; production run depends on weekly data availability.
4. **Non-critical tasks** — Anytime TD Celery tasks are not in `CRITICAL_PIPELINE_TASKS` (QB/kickers remain critical).

---

## Review fix (Important findings)

**Status:** DONE  
**Commit:** `73b15b41` — `fix(nfl): anytime TD actuals scoring and scheme week upsert`

### Changes

1. **Anytime TD actuals** — `aggregate_player_td_count` sums `rushing_tds` + `receiving_tds` only (passing TDs excluded per `player_anytime_td` market).
2. **Scheme upsert idempotency** — Season YAML sync uses `SEASON_LEVEL_WEEK=0` (not `NULL`) for unique `(team_name, season, week)`.
3. **DB↔tag decoders** — Added `decode_cover_base`, `decode_man_zone_lean`, `decode_pressure_lean`, `db_row_to_scheme_tags` in `scheme_loader.py`. Features remain YAML-sourced string tags.
4. **Docs** — `NFL_ETL_PARITY.md` section on anytime TD + schemes; `ODDS_API_KEY` blurb includes `player_anytime_td`.

### Tests

```bash
cd backend && PYTHONPATH=. .venv/bin/python -m pytest \
  tests/test_nfl_anytime_td_pipeline.py tests/test_nfl_scheme_loader.py \
  tests/test_nfl_pipeline_phases.py -q
# 22 passed
```

### Remaining concerns

- Existing `week=NULL` scheme rows in DB (if any) won't dedupe with new `week=0` rows until cleaned up.
- Decode helpers unused by feature path today; ready for API/analytics readers.
